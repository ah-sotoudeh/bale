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
    'pending',
    'waiting_managers',
    'waiting_customer_confirm',
    'waiting_payment',
    'completed',
)
ACTIVE_ITEM_STATUSES = ('cart', 'pending', 'approved', 'edited')

MANUAL_BUSY_NOTE = 'رزرو خارج از سیستم (پنل مدیر)'


def effective_window(item: OrderItem) -> Tuple[datetime, datetime]:
    start = item.manager_edited_start or item.requested_start
    if item.manager_edited_start is not None:
        hours = item.tariff.duration_hours if item.tariff_id else 0
        end = start + timedelta(hours=hours)
    else:
        end = item.requested_end
    return start, end


def ranges_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


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
) -> bool:
    qs = OrderItem.objects.select_related('tariff', 'order').filter(
        tariff=tariff,
        manager_status__in=ACTIVE_ITEM_STATUSES,
        order__status__in=ACTIVE_ORDER_STATUSES,
    )
    if exclude_item_id is not None:
        qs = qs.exclude(id=exclude_item_id)

    for item in qs:
        other_start, other_end = effective_window(item)
        if tariff.start_hour is not None:
            if same_local_day(start, other_start):
                return True
        elif ranges_overlap(start, end, other_start, other_end):
            return True

    busy_q = Q(is_available=False, start__lt=end, end__gt=start)
    if tariff.group_id:
        blocked = AvailabilitySlot.objects.filter(busy_q).filter(
            Q(group=tariff.group) | Q(tariff=tariff)
        )
    else:
        ch = channel or tariff.channel
        blocked = AvailabilitySlot.objects.filter(busy_q).filter(
            Q(channel=ch) | Q(tariff=tariff)
        )
    return blocked.exists()


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

    hour = tariff.start_hour if tariff.start_hour is not None else 0
    duration = tariff.duration_hours
    day = from_date
    while day <= to_date:
        start = timezone.make_aware(datetime.combine(day, dtime(hour=hour)))
        end = start + timedelta(hours=duration)
        if not has_slot_conflict(tariff, start, end, channel=channel or tariff.channel):
            yield day
        day = day + timedelta(days=1)


def day_status_map(tariff: Tariff, days: int = 14) -> List[Tuple[date, bool]]:
    """List of (day, is_free) for the next `days` calendar days."""
    today = timezone.localdate()
    until = today + timedelta(days=max(1, days) - 1)
    free_set = set(free_days_for_tariff(tariff, today, until))
    out: List[Tuple[date, bool]] = []
    d = today
    while d <= until:
        out.append((d, d in free_set))
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
    """Block the whole local day for this tariff's channel/group."""
    start = timezone.make_aware(datetime.combine(day, dtime(0, 0)))
    end = start + timedelta(days=1)
    return mark_external_busy(
        start,
        end,
        channel=tariff.channel if not tariff.group_id else None,
        group=tariff.group if tariff.group_id else None,
        tariff=tariff,
        note=MANUAL_BUSY_NOTE,
    )
