"""Slot conflict and external-busy checks for ad bookings.

Rules:
- An OrderItem occupies [effective_start, effective_end).
- effective_start = manager_edited_start or requested_start
- effective_end = effective_start + tariff.duration_hours
  (if start was edited) else requested_end
- Active bookings: order status in waiting_managers/waiting_payment/completed/pending
  and item manager_status in pending/approved/edited (not rejected)
- Conflict if same channel + same tariff and time ranges overlap
- When tariff.start_hour is set, also treat same calendar day as the same slot
- AvailabilitySlot with is_available=False blocks overlapping windows
  (optionally scoped to a tariff)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from django.db.models import Q
from django.utils import timezone

from channels_app.models import AvailabilitySlot, Channel, Tariff
from orders.models import OrderItem

ACTIVE_ORDER_STATUSES = ('pending', 'waiting_managers', 'waiting_payment', 'completed')
ACTIVE_ITEM_STATUSES = ('pending', 'approved', 'edited')


def effective_window(item: OrderItem) -> Tuple[datetime, datetime]:
    start = item.manager_edited_start or item.requested_start
    if item.manager_edited_start is not None:
        hours = item.tariff.duration_hours if item.tariff_id else 0
        end = start + timedelta(hours=hours)
    else:
        end = item.requested_end
    return start, end


def ranges_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def same_local_day(a: datetime, b: datetime) -> bool:
    if timezone.is_aware(a):
        a = timezone.localtime(a)
    if timezone.is_aware(b):
        b = timezone.localtime(b)
    return a.date() == b.date()


def has_slot_conflict(
    channel: Channel,
    tariff: Tariff,
    start: datetime,
    end: datetime,
    exclude_item_id: Optional[int] = None,
) -> bool:
    """True if another active booking or external busy slot overlaps."""
    qs = (
        OrderItem.objects.select_related('tariff', 'order')
        .filter(
            channel=channel,
            tariff=tariff,
            manager_status__in=ACTIVE_ITEM_STATUSES,
            order__status__in=ACTIVE_ORDER_STATUSES,
        )
    )
    if exclude_item_id is not None:
        qs = qs.exclude(id=exclude_item_id)

    for item in qs:
        other_start, other_end = effective_window(item)
        if tariff.start_hour is not None:
            # One turn per tariff per calendar day
            if same_local_day(start, other_start):
                return True
        elif ranges_overlap(start, end, other_start, other_end):
            return True

    blocked = AvailabilitySlot.objects.filter(
        channel=channel,
        is_available=False,
        start__lt=end,
        end__gt=start,
    ).filter(Q(tariff__isnull=True) | Q(tariff=tariff))
    return blocked.exists()


def mark_external_busy(
    channel: Channel,
    start: datetime,
    end: datetime,
    tariff: Optional[Tariff] = None,
    note: str = 'رزرو خارج از سیستم',
) -> AvailabilitySlot:
    """Manager marks a window full (taken outside the bot)."""
    return AvailabilitySlot.objects.create(
        channel=channel,
        tariff=tariff,
        start=start,
        end=end,
        is_available=False,
        note=note,
    )


def free_days_for_tariff(
    channel: Channel,
    tariff: Tariff,
    from_date,
    to_date,
):
    """Yield dates in [from_date, to_date] that are not occupied for this tariff."""
    from datetime import date, datetime, time as dtime

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
        if not has_slot_conflict(channel, tariff, start, end):
            yield day
        day = day + timedelta(days=1)
