"""Customer cart → order lifecycle helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from channels_app.models import Channel, Tariff
from integrations import bale_client as bc
from orders.availability import has_slot_conflict
from orders.models import ManagerResponse, Order, OrderItem
from users.models import User

logger = logging.getLogger(__name__)

MANAGER_HOURS = int(os.environ.get('MANAGER_RESPONSE_HOURS', '12'))


def get_or_create_draft(customer: User) -> Order:
    order = (
        Order.objects.filter(customer=customer, status='draft')
        .order_by('-id')
        .first()
    )
    if order:
        return order
    return Order.objects.create(customer=customer, status='draft')


def clear_draft(customer: User) -> None:
    Order.objects.filter(customer=customer, status='draft').delete()


def slot_for_day(tariff: Tariff, day) -> tuple:
    hour = tariff.start_hour if tariff.start_hour is not None else 0
    start = timezone.make_aware(datetime.combine(day, dtime(hour=hour)))
    end = start + timedelta(hours=tariff.duration_hours)
    return start, end


def add_to_cart(
    customer: User,
    tariff: Tariff,
    day,
) -> Dict[str, Any]:
    start, end = slot_for_day(tariff, day)
    channel = tariff.channel
    if tariff.group_id:
        channel = tariff.group.channels.order_by('id').first()
    if not channel:
        return {'ok': False, 'error': 'no_channel'}

    if has_slot_conflict(tariff, start, end, channel=channel):
        return {'ok': False, 'error': 'slot_conflict'}

    order = get_or_create_draft(customer)
    if order.banner_message_id:
        # keep banner
        pass

    item = OrderItem.objects.create(
        order=order,
        channel=channel,
        tariff=tariff,
        requested_start=start,
        requested_end=end,
        price=tariff.price,
        manager=channel.manager or (tariff.group.manager if tariff.group_id else None),
        manager_status='cart',
    )
    order.recompute_total()
    return {'ok': True, 'order': order, 'item': item}


def cart_summary(order: Order) -> str:
    items = list(order.items.filter(manager_status='cart').select_related('tariff', 'channel', 'tariff__group'))
    if not items:
        return 'سبد خرید خالی است.'
    lines = ['🛒 سبد خرید:']
    for i, it in enumerate(items, 1):
        t = it.tariff
        owner = t.group.name if t.group_id else (it.channel.name if it.channel else '?')
        day = timezone.localtime(it.requested_start).strftime('%Y-%m-%d')
        lines.append(f'{i}. {owner} | {t.name} | {day} | {it.price:,} ت')
    lines.append(f'\nجمع: {order.total_amount:,} تومان')
    lines.append(f'{len(items)} آیتم')
    return '\n'.join(lines)


def set_banner(order: Order, from_chat_id: str, message_id: str, caption: str = '') -> None:
    order.banner_from_chat_id = str(from_chat_id)
    order.banner_message_id = str(message_id)
    order.banner_caption = caption or ''
    order.save(update_fields=['banner_from_chat_id', 'banner_message_id', 'banner_caption'])


@transaction.atomic
def checkout(order: Order) -> Dict[str, Any]:
    items = list(order.items.filter(manager_status='cart').select_related('tariff', 'channel', 'manager'))
    if not items:
        return {'ok': False, 'error': 'empty_cart'}
    if not order.banner_message_id:
        return {'ok': False, 'error': 'no_banner'}

    for it in items:
        if has_slot_conflict(
            it.tariff, it.requested_start, it.requested_end, channel=it.channel, exclude_item_id=it.id
        ):
            return {'ok': False, 'error': 'slot_conflict', 'item_id': it.id}

    deadline = timezone.now() + timedelta(hours=MANAGER_HOURS)
    order.status = 'waiting_managers'
    order.managers_deadline = deadline
    order.recompute_total()
    order.save()

    for it in items:
        it.manager_status = 'pending'
        it.save(update_fields=['manager_status'])

    # notify managers
    for it in items:
        _notify_manager(order, it)

    return {'ok': True, 'order': order, 'deadline': deadline, 'count': len(items)}


def _notify_manager(order: Order, item: OrderItem) -> None:
    if not item.manager or not item.manager.bale_user_id:
        return
    mid = item.manager.bale_user_id
    if order.banner_message_id and order.banner_from_chat_id:
        try:
            bc.forward_message(mid, order.banner_from_chat_id, int(order.banner_message_id))
        except Exception:
            logger.exception('forward banner failed')

    t = item.tariff
    owner = t.group.name if t.group_id else (item.channel.name if item.channel else '?')
    start = timezone.localtime(item.requested_start)
    kb = bc.inline_keyboard([
        [
            {'text': '✅ تأیید', 'callback_data': f'approve:{item.id}'},
            {'text': '❌ رد', 'callback_data': f'reject:{item.id}'},
        ],
        [{'text': '✏️ پیشنهاد زمان دیگر', 'callback_data': f'editask:{item.id}'}],
    ])
    bc.send_message(
        mid,
        f'📢 درخواست تبلیغ\n'
        f'هدف: {owner}\n'
        f'تعرفه: {t.name}\n'
        f'زمان: {start}\n'
        f'مبلغ: {item.price:,} تومان\n'
        f'آیتم #{item.id} | سفارش #{order.id}\n'
        f'مهلت پاسخ: {MANAGER_HOURS} ساعت',
        reply_markup=kb,
    )


def process_manager_item(
    item_id: int,
    manager_bale_id: str,
    action: str,
    new_start: Optional[datetime] = None,
) -> Dict[str, Any]:
    action = (action or '').lower()
    try:
        item = OrderItem.objects.select_related(
            'order', 'order__customer', 'channel', 'tariff', 'manager'
        ).get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'item_not_found'}

    try:
        manager = User.objects.get(bale_user_id=str(manager_bale_id))
    except User.DoesNotExist:
        return {'ok': False, 'error': 'manager_not_found'}

    if item.manager_id and item.manager_id != manager.id:
        return {'ok': False, 'error': 'not_item_manager'}
    if item.manager_status != 'pending':
        return {'ok': False, 'error': 'already_handled'}

    order = item.order
    if action == 'approve':
        if has_slot_conflict(
            item.tariff, item.requested_start, item.requested_end,
            channel=item.channel, exclude_item_id=item.id,
        ):
            return {'ok': False, 'error': 'slot_conflict'}
        item.manager_status = 'approved'
        item.save()
        ManagerResponse.objects.create(order_item=item, manager=manager, action='approve')
    elif action == 'reject':
        item.manager_status = 'rejected'
        item.save()
        ManagerResponse.objects.create(order_item=item, manager=manager, action='reject')
    elif action == 'edit':
        if not new_start:
            return {'ok': False, 'error': 'need_new_start'}
        new_end = new_start + timedelta(hours=item.tariff.duration_hours)
        if has_slot_conflict(
            item.tariff, new_start, new_end, channel=item.channel, exclude_item_id=item.id
        ):
            return {'ok': False, 'error': 'slot_conflict'}
        item.manager_edited_start = new_start
        item.manager_status = 'edited'
        item.save()
        ManagerResponse.objects.create(
            order_item=item, manager=manager, action='edit',
            payload={'new_start': new_start.isoformat()},
        )
        _ask_customer_confirm(order, item)
    else:
        return {'ok': False, 'error': 'invalid_action'}

    return maybe_finalize_order(order.id)


def _ask_customer_confirm(order: Order, item: OrderItem) -> None:
    cust = order.customer.bale_user_id
    if not cust:
        return
    start = timezone.localtime(item.manager_edited_start)
    kb = bc.inline_keyboard([
        [
            {'text': '✅ قبول زمان جدید', 'callback_data': f'custok:{item.id}'},
            {'text': '❌ رد زمان', 'callback_data': f'custno:{item.id}'},
        ]
    ])
    t = item.tariff
    owner = t.group.name if t.group_id else (item.channel.name if item.channel else '?')
    bc.send_message(
        cust,
        f'✏️ مدیر برای «{owner}» زمان جدید پیشنهاد داد:\n'
        f'{start}\n'
        f'آیتم #{item.id}',
        reply_markup=kb,
    )
    if order.status == 'waiting_managers':
        order.status = 'waiting_customer_confirm'
        order.save(update_fields=['status'])


def customer_confirm_edit(item_id: int, customer_bale_id: str, accept: bool) -> Dict[str, Any]:
    try:
        item = OrderItem.objects.select_related('order', 'order__customer', 'tariff').get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'item_not_found'}
    if str(item.order.customer.bale_user_id) != str(customer_bale_id):
        return {'ok': False, 'error': 'not_customer'}
    if item.manager_status != 'edited':
        return {'ok': False, 'error': 'not_awaiting'}

    if accept:
        item.manager_status = 'approved'
        if item.manager_edited_start:
            item.requested_start = item.manager_edited_start
            item.requested_end = item.manager_edited_start + timedelta(
                hours=item.tariff.duration_hours
            )
        item.save()
    else:
        item.manager_status = 'customer_declined'
        item.save()

    return maybe_finalize_order(item.order_id)


def expire_timed_out_items() -> int:
    """Mark pending items past deadline as expired. Returns count."""
    now = timezone.now()
    qs = OrderItem.objects.filter(
        manager_status='pending',
        order__status__in=('waiting_managers', 'waiting_customer_confirm'),
        order__managers_deadline__lt=now,
    )
    n = 0
    order_ids = set()
    for it in qs.select_related('order'):
        it.manager_status = 'expired'
        it.save(update_fields=['manager_status'])
        order_ids.add(it.order_id)
        n += 1
    for oid in order_ids:
        maybe_finalize_order(oid)
    return n


def maybe_finalize_order(order_id: int) -> Dict[str, Any]:
    """When no pending/edited left, notify customer once and request payment if needed."""
    try:
        order = Order.objects.prefetch_related('items__tariff', 'items__channel').get(id=order_id)
    except Order.DoesNotExist:
        return {'ok': False, 'error': 'order_not_found'}

    if order.status not in ('waiting_managers', 'waiting_customer_confirm'):
        return {'ok': True, 'order_status': order.status, 'skipped': True}

    items = list(order.items.exclude(manager_status='cart'))
    still = [i for i in items if i.manager_status in ('pending', 'edited')]
    if still:
        return {'ok': True, 'pending_left': len(still), 'order_status': order.status}

    approved = [i for i in items if i.manager_status == 'approved']
    rejected = [i for i in items if i.manager_status in ('rejected', 'expired', 'customer_declined')]

    lines = [f'📋 نتیجه سفارش #{order.id}:']
    for i in approved:
        t = i.tariff
        owner = t.group.name if t.group_id else (i.channel.name if i.channel else '?')
        lines.append(f'✅ {owner} — {t.name} — {i.price:,} ت')
    for i in rejected:
        t = i.tariff
        owner = t.group.name if t.group_id else (i.channel.name if i.channel else '?')
        st = {'rejected': 'رد مدیر', 'expired': 'مهلت تمام', 'customer_declined': 'رد زمان'}.get(
            i.manager_status, i.manager_status
        )
        lines.append(f'❌ {owner} — {t.name} ({st})')

    cust = order.customer.bale_user_id
    if not approved:
        order.status = 'rejected'
        order.total_amount = 0
        order.save()
        lines.append('\nهیچ آیتمی تأیید نشد. سفارش بسته شد.')
        if cust:
            bc.send_message(cust, '\n'.join(lines))
        return {'ok': True, 'order_status': 'rejected'}

    total = sum(i.price for i in approved)
    order.total_amount = total
    order.status = 'waiting_payment'
    order.save()

    lines.append(f'\nمبلغ قابل پرداخت: {total:,} تومان')
    lines.append('برای شبیه‌سازی پرداخت دکمه زیر را بزنید.')
    kb = bc.payment_done_keyboard(order.id)
    if cust:
        bc.send_message(cust, '\n'.join(lines), reply_markup=kb)
        from orders.services import process_payment_paid  # noqa: F401 — payment via callback

        payment = bc.create_payment_request(
            chat_id=cust,
            amount=total,
            title=f'پرداخت سفارش #{order.id}',
            description=f'تبلیغ — سفارش #{order.id}',
            payload=f'order-{order.id}',
        )
        if payment.get('payment_url'):
            bc.send_message(cust, f'لینک پرداخت: {payment["payment_url"]}', reply_markup=kb)

    return {'ok': True, 'order_status': 'waiting_payment', 'total': total}
