"""Slot conflict checks for single-channel and package (ChannelGroup) tariffs."""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from typing import List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone

from channels_app.models import AvailabilitySlot, Channel, Tariff
from orders.models import OrderItem

ACTIVE_ORDER_STATUSES = (
    'draft',
    'waiting_banner',
    'waiting_managers',
    'waiting_customer_confirm',
    'waiting_payment',
    'paid',
    'completed',
)
ACTIVE_ITEM_STATUSES = ('cart', 'pending', 'approved', 'edited')

MANUAL_BUSY_NOTE = 'رزرو خارج از سیستم (پنل مدیر)'


def effective_window(item: OrderItem) -> Tuple[datetime, datetime]:
    start = item.manager_edited_start or item.requested_start
    if item.manager_edited_start is not None:
        hours = item.booked_duration()
        end = start + timedelta(hours=hours)
    else:
        end = item.requested_end
    return start, end


def ranges_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


def slot_bounds(tariff: Tariff, day: date) -> Tuple[datetime, datetime]:
    hour = tariff.start_hour if tariff.start_hour is not None else 0
    start = timezone.make_aware(datetime.combine(day, dtime(hour=hour)))
    return start, start + timedelta(hours=int(tariff.duration_hours or 0))


def is_past_slot(tariff: Tariff, day: date, now: Optional[datetime] = None) -> bool:
    """ساعت شروع این روز گذشته است؛ دیگر فروخته نمی‌شود."""
    now = now or timezone.now()
    start, _end = slot_bounds(tariff, day)
    return start <= now


def _channel_ids_for(tariff: Tariff, channel: Optional[Channel] = None) -> List[int]:
    if tariff.group_id:
        return list(tariff.group.channels.values_list('id', flat=True))
    if channel is not None:
        return [channel.id]
    if tariff.channel_id:
        return [tariff.channel_id]
    return []


def item_channel_ids(item: OrderItem) -> set:
    ids = set()
    raw = item.booked_channel_ids or []
    if isinstance(raw, list):
        for value in raw:
            try:
                ids.add(int(value))
            except (TypeError, ValueError):
                continue
    if ids:
        return ids
    if item.channel_id:
        ids.add(item.channel_id)
    tariff = getattr(item, 'tariff', None)
    if tariff is not None and tariff.group_id:
        ids.update(tariff.group.channels.values_list('id', flat=True))
    elif tariff is not None and tariff.channel_id:
        ids.add(tariff.channel_id)
    return ids


def _exclude_items(qs, exclude_item_id: Optional[int], exclude_item_ids: Optional[set] = None):
    if exclude_item_id is not None:
        qs = qs.exclude(id=exclude_item_id)
    if exclude_item_ids:
        qs = qs.exclude(id__in=exclude_item_ids)
    return qs


def channel_window_conflict(
    tariff: Tariff,
    start: datetime,
    end: datetime,
    exclude_item_id: Optional[int] = None,
    channel: Optional[Channel] = None,
    exclude_item_ids: Optional[set] = None,
) -> bool:
    """تعرفهٔ دیگرِ همان کانال، اگر بازه‌اش روی این ساعت بیفتد، روز را می‌بندد."""
    ch_ids = _channel_ids_for(tariff, channel)
    if not ch_ids:
        return False
    qs = (
        OrderItem.objects.select_related('tariff', 'tariff__group', 'order', 'channel')
        .filter(
            manager_status__in=ACTIVE_ITEM_STATUSES,
            order__status__in=ACTIVE_ORDER_STATUSES,
        )
        .filter(
            Q(channel_id__in=ch_ids)
            | Q(tariff__channel_id__in=ch_ids)
            | Q(tariff__group__channels__id__in=ch_ids)
        )
        .distinct()
    )
    qs = _exclude_items(qs, exclude_item_id, exclude_item_ids)
    wanted = set(ch_ids)
    for item in qs:
        if item.tariff_id == tariff.id:
            continue
        if not (item_channel_ids(item) & wanted):
            continue
        other_start, other_end = effective_window(item)
        if ranges_overlap(start, end, other_start, other_end):
            return True
    return False


def same_local_day(a: datetime, b: datetime) -> bool:
    if timezone.is_aware(a):
        a = timezone.localtime(a)
    if timezone.is_aware(b):
        b = timezone.localtime(b)
    return a.date() == b.date()


def has_slot_conflict(
    tariff: Tariff,
    start: datetime,
    end: datetime,
    exclude_item_id: Optional[int] = None,
    channel: Optional[Channel] = None,
    exclude_item_ids: Optional[set] = None,
) -> bool:
    qs = OrderItem.objects.select_related('tariff', 'order').filter(
        tariff=tariff,
        manager_status__in=ACTIVE_ITEM_STATUSES,
        order__status__in=ACTIVE_ORDER_STATUSES,
    )
    qs = _exclude_items(qs, exclude_item_id, exclude_item_ids)

    for item in qs:
        other_start, other_end = effective_window(item)
        if tariff.start_hour is not None:
            if same_local_day(start, other_start):
                return True
        elif ranges_overlap(start, end, other_start, other_end):
            return True

    if channel_window_conflict(
        tariff,
        start,
        end,
        exclude_item_id=exclude_item_id,
        channel=channel,
        exclude_item_ids=exclude_item_ids,
    ):
        return True

    if tariff.group_id:
        blocked_qs = AvailabilitySlot.objects.filter(is_available=False).filter(
            Q(group=tariff.group) | Q(tariff=tariff)
        )
    else:
        ch = channel or tariff.channel
        blocked_qs = AvailabilitySlot.objects.filter(is_available=False).filter(
            Q(channel=ch) | Q(tariff=tariff)
        )

    # برای تعرفه با ساعت ثابت: فقط همان روز محلی نوبت مسدود شود
    # (بازهٔ کامل ۰ تا ۲۴ باعث پر شدن اشتباه روز قبل می‌شد)
    if tariff.start_hour is not None:
        day = timezone.localtime(start).date() if timezone.is_aware(start) else start.date()
        for slot in blocked_qs.filter(
            start__lt=end + timedelta(days=1), end__gt=start - timedelta(days=1)
        ):
            slot_day = (
                timezone.localtime(slot.start).date()
                if timezone.is_aware(slot.start)
                else slot.start.date()
            )
            if slot_day == day:
                return True
        return False

    return blocked_qs.filter(start__lt=end, end__gt=start).exists()


def mark_external_busy(
    start: datetime,
    end: datetime,
    *,
    channel: Optional[Channel] = None,
    group=None,
    tariff: Optional[Tariff] = None,
    note: str = MANUAL_BUSY_NOTE,
) -> AvailabilitySlot:
    return AvailabilitySlot.objects.create(
        channel=channel,
        group=group,
        tariff=tariff,
        start=start,
        end=end,
        is_available=False,
        note=note or MANUAL_BUSY_NOTE,
    )


def free_days_for_tariff(tariff: Tariff, from_date, to_date, channel: Optional[Channel] = None):
    if isinstance(from_date, datetime):
        from_date = timezone.localtime(from_date).date() if timezone.is_aware(from_date) else from_date.date()
    if isinstance(to_date, datetime):
        to_date = timezone.localtime(to_date).date() if timezone.is_aware(to_date) else to_date.date()

    day = from_date
    while day <= to_date:
        if is_past_slot(tariff, day):
            day = day + timedelta(days=1)
            continue
        start, end = slot_bounds(tariff, day)
        if not has_slot_conflict(tariff, start, end, channel=channel or tariff.channel):
            yield day
        day = day + timedelta(days=1)


WHY_UNAVAILABLE = {
    'past': 'این ساعت گذشته است و دیگر نمی‌شود این روز را برداشت.',
    'full': 'این روز پر است.',
    'banner-hold': 'اول بنر روی کانال بنرها',
}


def classify_day(tariff: Tariff, day: date, now: Optional[datetime] = None) -> str:
    """free، full، یا past. بنرِ مشتری جداست."""
    if is_past_slot(tariff, day, now=now):
        return 'past'
    start, end = slot_bounds(tariff, day)
    if has_slot_conflict(tariff, start, end, channel=tariff.channel):
        return 'full'
    return 'free'


def viewer_has_ready_banner(user) -> bool:
    """بنر روی کانال بنرها تنها چیزی است که روز را از حالت بنر خارج می‌کند."""
    from orders.banner_publish import banner_stage
    from orders.models import CustomerBanner

    banners = CustomerBanner.objects.filter(customer=user, is_active=True)
    return any(banner_stage(banner) == 'ready' for banner in banners)


def day_status_for_viewer(tariff: Tariff, day: date, *, ready_banner: bool) -> str:
    """اگر روز خالی است ولی بنر آماده نیست، دلیل قفل banner-hold است."""
    status = classify_day(tariff, day)
    if status == 'free' and not ready_banner:
        return 'banner-hold'
    return status


def unavailable_why(status: str) -> str:
    return WHY_UNAVAILABLE.get(status, '')


def day_status_map(tariff: Tariff, days: int = 14) -> List[Tuple[date, str]]:
    """List of (day, status) for the next `days` calendar days. status is free/full/past."""
    today = timezone.localdate()
    until = today + timedelta(days=max(1, days) - 1)
    out: List[Tuple[date, str]] = []
    d = today
    while d <= until:
        out.append((d, classify_day(tariff, d)))
        d += timedelta(days=1)
    return out


def _manual_busy_q(tariff: Tariff) -> Q:
    q = Q(is_available=False)
    if tariff.group_id:
        q &= Q(group=tariff.group) | Q(tariff=tariff)
    else:
        q &= Q(channel=tariff.channel) | Q(tariff=tariff)
    return q


def list_manual_busy_slots(tariff: Tariff, from_date: Optional[date] = None) -> List[AvailabilitySlot]:
    """Slots marked manually by manager (external busy), from today onward."""
    if from_date is None:
        from_date = timezone.localdate()
    start_bound = timezone.make_aware(datetime.combine(from_date, dtime(0, 0)))
    return list(
        AvailabilitySlot.objects.filter(
            _manual_busy_q(tariff),
            end__gt=start_bound,
            note__icontains='خارج از سیستم',
        )
        .order_by('start')[:40]
    )


def clear_manual_busy_slot(slot_id: int, tariff: Tariff) -> bool:
    slot = (
        AvailabilitySlot.objects.filter(id=slot_id)
        .filter(_manual_busy_q(tariff), note__icontains='خارج از سیستم')
        .first()
    )
    if not slot:
        return False
    slot.delete()
    return True


def mark_tariff_day_busy(tariff: Tariff, day: date) -> AvailabilitySlot:
    """Block only this tariff's slot on the given local day (not neighboring days)."""
    from orders.slots import SlotConflict, hold_manual_day

    hour = tariff.start_hour if tariff.start_hour is not None else 0
    duration = max(1, int(tariff.duration_hours or 1))
    start = timezone.make_aware(datetime.combine(day, dtime(hour=hour, minute=0, second=0)))
    end = start + timedelta(hours=duration)
    slot = mark_external_busy(
        start,
        end,
        channel=tariff.channel if not tariff.group_id else None,
        group=tariff.group if tariff.group_id else None,
        tariff=tariff,
        note=MANUAL_BUSY_NOTE,
    )
    if not hold_manual_day(tariff, day, slot):
        slot.delete()
        raise SlotConflict()
    return slot
