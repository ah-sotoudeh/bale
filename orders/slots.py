"""DB-level day locks for a tariff. Works on MySQL and SQLite (no partial indexes)."""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

OCCUPYING = frozenset({'cart', 'pending', 'approved', 'edited'})


class SlotConflict(Exception):
    pass


def item_day(item):
    start = item.manager_edited_start or item.requested_start
    if start is None:
        return None
    if timezone.is_aware(start):
        start = timezone.localtime(start)
    return start.date()


def sync_item_lock(item) -> bool:
    from channels_app.models import Tariff
    from orders.models import SlotReservation

    if not item.pk:
        return True
    if item.manager_status not in OCCUPYING or item.execution_status == 'cancelled':
        SlotReservation.objects.filter(order_item_id=item.pk).delete()
        return True
    day = item_day(item)
    if day is None or not item.tariff_id:
        return True
    try:
        with transaction.atomic():
            Tariff.objects.select_for_update().get(pk=item.tariff_id)
            clash = (
                SlotReservation.objects.filter(tariff_id=item.tariff_id, slot_date=day)
                .exclude(order_item_id=item.pk)
                .exists()
            )
            if clash:
                return False
            lock = SlotReservation.objects.select_for_update().filter(order_item_id=item.pk).first()
            if lock:
                lock.tariff_id = item.tariff_id
                lock.slot_date = day
                lock.availability_id = None
                lock.save(update_fields=['tariff', 'slot_date', 'availability'])
                return True
            SlotReservation.objects.create(
                tariff_id=item.tariff_id,
                slot_date=day,
                order_item_id=item.pk,
            )
            return True
    except IntegrityError:
        return False


def hold_manual_day(tariff, day, availability) -> bool:
    from channels_app.models import Tariff
    from orders.models import SlotReservation

    try:
        with transaction.atomic():
            Tariff.objects.select_for_update().get(pk=tariff.pk)
            if SlotReservation.objects.filter(tariff_id=tariff.pk, slot_date=day).exists():
                return False
            SlotReservation.objects.create(
                tariff_id=tariff.pk,
                slot_date=day,
                availability=availability,
            )
            return True
    except IntegrityError:
        return False
