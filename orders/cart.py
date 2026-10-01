"""Customer cart → order lifecycle helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional

from django.db import OperationalError, transaction
from django.utils import timezone

from channels_app.models import Tariff
from bot_flow.messages import fa_money, fa_num
from integrations import bale_client as bc
from orders.availability import has_slot_conflict
from orders.models import CustomerDraft, ManagerResponse, Order, OrderItem
from orders.slots import SlotConflict
from users.models import User

logger = logging.getLogger(__name__)

MANAGER_HOURS = int(os.environ.get('MANAGER_RESPONSE_HOURS', '12'))
PAYMENT_HOLD_HOURS = int(os.environ.get('PAYMENT_HOLD_HOURS', '24'))


@transaction.atomic
def get_or_create_draft(customer: User) -> Order:
    User.objects.select_for_update().get(pk=customer.pk)
    lock = CustomerDraft.objects.select_related('order').filter(customer=customer).first()
    if lock:
        if lock.order.status == 'draft':
            return lock.order
        lock.delete()
    order = Order.objects.filter(customer=customer, status='draft').order_by('-id').first()
    if order is None:
        order = Order.objects.create(customer=customer, status='draft')
    CustomerDraft.objects.create(customer=customer, order=order)
    return order


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
    if not tariff.is_active:
        return {'ok': False, 'error': 'inactive_tariff'}
    start, end = slot_for_day(tariff, day)
    channel = tariff.channel
    if tariff.group_id:
        channel_ids = list(tariff.group.channels.values_list('id', flat=True))
        channel = tariff.group.channels.order_by('id').first()
    else:
        channel_ids = [tariff.channel_id] if tariff.channel_id else []
        channel = tariff.channel
    if not channel:
        return {'ok': False, 'error': 'no_channel'}

    if has_slot_conflict(tariff, start, end, channel=channel):
        return {'ok': False, 'error': 'slot_conflict'}

    order = get_or_create_draft(customer)

    try:
        item = OrderItem.objects.create(
            order=order,
            channel=channel,
            tariff=tariff,
            requested_start=start,
            requested_end=end,
            price=tariff.price,
            manager=channel.manager or (tariff.group.manager if tariff.group_id else None),
            manager_status='cart',
            duration_hours=tariff.duration_hours,
            booked_channel_ids=channel_ids,
        )
    except SlotConflict:
        return {'ok': False, 'error': 'slot_conflict'}
    order.recompute_total()
    return {'ok': True, 'order': order, 'item': item}


def cart_summary(order: Order) -> str:
    items = list(
        order.items.filter(manager_status='cart').select_related(
            'tariff', 'channel', 'tariff__group'
        )
    )
    if not items:
        return 'هنوز روزی انتخاب نکرده‌اید.'
    lines = ['روزهای انتخاب‌شده:']
    for i, it in enumerate(items, 1):
        t = it.tariff
        owner = t.group.name if t.group_id else (it.channel.name if it.channel else '?')
        day = timezone.localtime(it.requested_start).strftime('%Y-%m-%d')
        lines.append(f'{i}. {owner} | {t.name} | {day} | {it.price:,} ت')
    lines.append(f'\nجمع: {order.total_amount:,} تومان')
    lines.append(f'{len(items)} روز')
    return '\n'.join(lines)


def set_banner(order: Order, from_chat_id: str, message_id: str, caption: str = '') -> None:
    order.banner_from_chat_id = str(from_chat_id)
    order.banner_message_id = str(message_id)
    order.banner_caption = caption or ''
    order.save(update_fields=['banner_from_chat_id', 'banner_message_id', 'banner_caption'])


@transaction.atomic
def checkout(order: Order) -> Dict[str, Any]:
    items = list(
        order.items.filter(manager_status='cart').select_related('tariff', 'channel', 'manager')
    )
    if not items:
        return {'ok': False, 'error': 'empty_cart'}
    if not order.banner_message_id:
        return {'ok': False, 'error': 'no_banner'}

    for it in items:
        if has_slot_conflict(
            it.tariff,
            it.requested_start,
            it.requested_end,
            channel=it.channel,
            exclude_item_id=it.id,
        ):
            return {'ok': False, 'error': 'slot_conflict', 'item_id': it.id}

    order.recompute_total()
    CustomerDraft.objects.filter(order=order).delete()

    for it in items:
        it.manager_status = 'pending'
        it.save(update_fields=['manager_status'])

    banner = order.customer_banner
    ready = bool(banner and banner.from_linkbank)
    if not ready:
        order.status = 'waiting_banner'
        order.managers_deadline = None
        order.save()
        cust = order.customer.bale_user_id
        if cust:
            bc.send_message(
                cust,
                f'سفارش {fa_num(order.id)} ثبت شد.\n'
                'بنر هنوز در انتظار بررسی است. تا تأیید پشتیبانی، برای کانال‌دار فرستاده نمی‌شود '
                'و پولی از شما کم نمی‌شود.',
            )
        return {'ok': True, 'order': order, 'count': len(items), 'held_for_banner': True}

    deadline = timezone.now() + timedelta(hours=MANAGER_HOURS)
    order.status = 'waiting_managers'
    order.managers_deadline = deadline
    order.save()

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
    from bot_flow.jalali import format_slot

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
        f'درخواست تبلیغ تازه\n'
        f'کانال: {owner}\n'
        f'طرح: {t.name}\n'
        f'زمان: {format_slot(start)}\n'
        f'مبلغ: {fa_money(item.price)}\n'
        f'نوبت {fa_num(item.id)} از سفارش {fa_num(order.id)}\n'
        f'تا {fa_num(MANAGER_HOURS)} ساعت برای پاسخ وقت دارید. '
        f'قبول یا رد شما فقط همین کانال را عوض می‌کند.',
        reply_markup=kb,
    )


def _manager_may_answer(manager: User, item: OrderItem) -> bool:
    """فقط مدیر همان نوبت، یا صاحب کانال/مجموعه اگر مدیر نوبت خالی باشد."""
    if item.manager_id:
        return item.manager_id == manager.id
    if item.channel_id and item.channel and item.channel.manager_id == manager.id:
        return True
    tariff = item.tariff
    if tariff is None:
        return False
    if tariff.channel_id and tariff.channel and tariff.channel.manager_id == manager.id:
        return True
    if tariff.group_id and tariff.group and tariff.group.manager_id == manager.id:
        return True
    return False


def process_manager_item(
    item_id: int,
    manager_bale_id: str,
    action: str,
    new_start: Optional[datetime] = None,
) -> Dict[str, Any]:
    action = (action or '').lower()
    try:
        item = OrderItem.objects.select_related(
            'order', 'order__customer', 'channel', 'tariff', 'tariff__channel',
            'tariff__group', 'manager',
        ).get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'item_not_found'}

    try:
        manager = User.objects.get(bale_user_id=str(manager_bale_id))
    except User.DoesNotExist:
        return {'ok': False, 'error': 'manager_not_found'}

    if not _manager_may_answer(manager, item):
        return {'ok': False, 'error': 'not_item_manager'}
    if item.manager_status != 'pending':
        return {'ok': False, 'error': 'already_handled'}

    order = item.order
    if action == 'approve':
        if has_slot_conflict(
            item.tariff,
            item.requested_start,
            item.requested_end,
            channel=item.channel,
            exclude_item_id=item.id,
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
        new_end = new_start + timedelta(hours=item.booked_duration())
        if has_slot_conflict(
            item.tariff, new_start, new_end, channel=item.channel, exclude_item_id=item.id
        ):
            return {'ok': False, 'error': 'slot_conflict'}
        item.manager_edited_start = new_start
        item.manager_status = 'edited'
        try:
            item.save()
        except SlotConflict:
            return {'ok': False, 'error': 'slot_conflict'}
        ManagerResponse.objects.create(
            order_item=item,
            manager=manager,
            action='edit',
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
        f'مدیر «{owner}» به‌جای زمان قبلی، این زمان را پیشنهاد کرده:\n'
        f'{start}\n'
        f'نوبت {fa_num(item.id)}. قبول یا رد، فقط همین کانال را عوض می‌کند.',
        reply_markup=kb,
    )
    if order.status == 'waiting_managers':
        order.status = 'waiting_customer_confirm'
        order.save(update_fields=['status'])


def customer_confirm_edit(item_id: int, customer_bale_id: str, accept: bool) -> Dict[str, Any]:
    try:
        item = OrderItem.objects.select_related('order', 'order__customer', 'tariff').get(
            id=item_id
        )
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
            item.requested_end = item.manager_edited_start + timedelta(hours=item.booked_duration())
        try:
            item.save()
        except SlotConflict:
            return {'ok': False, 'error': 'slot_conflict'}
    else:
        item.manager_status = 'customer_declined'
        item.save()

    return maybe_finalize_order(item.order_id)


def expire_timed_out_items() -> int:
    """Mark pending items past deadline as expired. Returns count."""
    try:
        now = timezone.now()
        qs = OrderItem.objects.filter(
            manager_status__in=('pending', 'edited'),
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
    except OperationalError as e:
        logger.warning(
            'expire_timed_out_items skipped (DB schema outdated?). Run migrate. %s', e
        )
        return 0


def maybe_finalize_order(order_id: int) -> Dict[str, Any]:
    try:
        order = Order.objects.prefetch_related('items__tariff', 'items__channel').get(
            id=order_id
        )
    except Order.DoesNotExist:
        return {'ok': False, 'error': 'order_not_found'}

    if order.status not in ('waiting_managers', 'waiting_customer_confirm'):
        return {'ok': True, 'order_status': order.status, 'skipped': True}

    items = list(order.items.exclude(manager_status='cart'))
    pending = [i for i in items if i.manager_status == 'pending']
    edited = [i for i in items if i.manager_status == 'edited']
    if pending or edited:
        if not edited and order.status == 'waiting_customer_confirm':
            order.status = 'waiting_managers'
            order.save(update_fields=['status'])
        return {
            'ok': True,
            'pending_left': len(pending) + len(edited),
            'order_status': order.status,
        }

    approved = [i for i in items if i.manager_status == 'approved']
    rejected = [
        i
        for i in items
        if i.manager_status in ('rejected', 'expired', 'customer_declined')
    ]

    lines = [f'نتیجه سفارش {fa_num(order.id)}:']
    for i in approved:
        t = i.tariff
        owner = t.group.name if t.group_id else (i.channel.name if i.channel else 'کانال')
        lines.append(f'قبول شد: {owner} — {t.name} — {fa_money(i.price)}')
    for i in rejected:
        t = i.tariff
        owner = t.group.name if t.group_id else (i.channel.name if i.channel else 'کانال')
        st = {
            'rejected': 'مدیر نپذیرفت',
            'expired': 'مهلت پاسخ تمام شد',
            'customer_declined': 'زمان پیشنهادی را نپذیرفتید',
        }.get(i.manager_status, 'انجام نشد')
        lines.append(f'انجام نشد: {owner} — {t.name} ({st})')

    cust = order.customer.bale_user_id
    if not approved:
        order.status = 'rejected'
        order.total_amount = 0
        order.save()
        lines.append('\nهیچ کانالی این سفارش را نپذیرفت و سفارش بسته شد. روزها آزاد شدند.')
        if cust:
            bc.send_message(cust, '\n'.join(lines))
        return {'ok': True, 'order_status': 'rejected'}

    total = sum(i.price for i in approved)
    order.total_amount = total
    order.status = 'waiting_payment'
    order.managers_deadline = timezone.now() + timedelta(hours=PAYMENT_HOLD_HOURS)
    order.save()

    from bot_flow.access import is_debug_user

    from orders.bale_pay import WALLET_MAX_TOMAN, payment_parts

    parts = payment_parts(total)
    lines.append(f'\nمبلغ قابل پرداخت: {fa_money(total)}')
    if len(parts) > 1:
        lines.append(
            f'سقف هر انتقال کیف‌پول {fa_money(WALLET_MAX_TOMAN)} است. '
            f'این مبلغ در {fa_num(len(parts))} درخواست جدا می‌آید:'
        )
        for index, part in enumerate(parts, start=1):
            lines.append(f'{fa_num(index)}. {fa_money(part)}')
        lines.append('سفارش بعد از پرداخت همهٔ درخواست‌ها ثبت می‌شود.')
    lines.append(
        f'تا {fa_num(PAYMENT_HOLD_HOURS)} ساعت برای پرداخت وقت دارید. '
        'بعد از آن، روزها دوباره آزاد می‌شوند.'
    )
    kb = None
    debug = bool(cust and is_debug_user(cust))
    if debug:
        lines.append('این حساب آزمایشی است. دکمهٔ زیر پرداخت را بدون فاکتور ثبت می‌کند.')
        kb = bc.payment_done_keyboard(order.id)
    if cust:
        bc.send_message(cust, '\n'.join(lines), reply_markup=kb)
        from orders.bale_pay import announce_invoices, send_order_invoices

        payment = send_order_invoices(order, cust)
        announce_invoices(cust, payment)

    return {'ok': True, 'order_status': 'waiting_payment', 'total': total}


def _release_open_items(order: Order, manager_status: str) -> list:
    touched = []
    for item in order.items.select_related('manager', 'channel', 'tariff'):
        if item.manager_status not in ('cart', 'pending', 'approved', 'edited'):
            continue
        item.manager_status = manager_status
        item.execution_status = 'cancelled'
        item.save()
        touched.append(item)
    return touched


REFUND_CUTOFF = timedelta(hours=2)


def _open_items(order: Order):
    return [
        it
        for it in order.items.all()
        if it.manager_status not in ('rejected', 'expired', 'customer_declined')
        and it.execution_status not in ('cancelled', 'executed')
    ]


def publish_start(order: Order):
    starts = [it.effective_start for it in _open_items(order) if it.effective_start]
    return min(starts) if starts else None


def refund_window_open(order: Order) -> bool:
    start = publish_start(order)
    if start is None:
        return False
    return timezone.now() <= start - REFUND_CUTOFF


def release_orders_waiting_on_banner(banner) -> int:
    """بعد از تأیید بنر، سفارش‌های منتظر را برای کانال‌دار می‌فرستد."""
    n = 0
    orders = Order.objects.filter(
        customer_id=banner.customer_id,
        status='waiting_banner',
        customer_banner=banner,
    )
    for order in orders:
        order.status = 'waiting_managers'
        order.managers_deadline = timezone.now() + timedelta(hours=MANAGER_HOURS)
        order.save(update_fields=['status', 'managers_deadline'])
        for it in order.items.filter(manager_status='pending'):
            _notify_manager(order, it)
        cust = order.customer.bale_user_id
        if cust:
            bc.send_message(
                cust,
                f'بنر تأیید شد. سفارش {fa_num(order.id)} برای کانال‌ها فرستاده شد. '
                'پرداخت بعد از قبول کانال است.',
            )
        n += 1
    return n


def cancel_orders_waiting_on_banner(banner) -> int:
    n = 0
    orders = list(
        Order.objects.filter(
            customer_id=banner.customer_id,
            status='waiting_banner',
            customer_banner=banner,
        )
    )
    for order in orders:
        cancel_customer_order(order)
        n += 1
    return n


def _refunded_so_far(item_id: int) -> int:
    from django.db.models import Sum

    from wallet.models import WalletLedger

    return int(
        WalletLedger.objects.filter(ref=f'item:{item_id}', entry_type='refund').aggregate(s=Sum('amount'))[
            's'
        ]
        or 0
    )


def refund_paid_order(order: Order, amount: Optional[int] = None, *, reason: str = '') -> Dict[str, Any]:
    """بازگشت پول پرداخت‌شده به اعتبار مشتری. مبلغ خالی یعنی کل سفارش."""
    from wallet.services import credit

    note = (reason or f'بازگشت سفارش {fa_num(order.id)} به اعتبار')[:255]
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related('customer').get(pk=order.pk)
        if order.status != 'paid':
            return {'ok': False, 'error': 'not_paid'}
        items = _open_items(order)
        remaining = 0
        for it in items:
            already = _refunded_so_far(it.id)
            remaining += max(0, int(it.price) - already)
        if remaining <= 0:
            return {'ok': False, 'error': 'already_refunded'}
        pay = remaining if amount is None else min(int(amount), remaining)
        if pay <= 0:
            return {'ok': False, 'error': 'bad_amount'}
        full = pay >= remaining
        left = pay
        credited = 0
        for it in items:
            if left <= 0:
                break
            already = _refunded_so_far(it.id)
            room = max(0, int(it.price) - already)
            chunk = min(room, left)
            if chunk <= 0:
                continue
            credit(
                order.customer,
                chunk,
                'refund',
                ref=f'item:{it.id}',
                note=note,
                idempotency_key=f'refund:item:{it.id}:{int(already) + chunk}'[:80],
            )
            credited += chunk
            left -= chunk
            if full or chunk >= room:
                it.manager_status = 'customer_declined'
                it.execution_status = 'cancelled'
                it.save()
        if full:
            order.status = 'cancelled'
            order.total_amount = 0
            order.save(update_fields=['status', 'total_amount'])
    cust = order.customer.bale_user_id
    if cust:
        bc.send_message(
            cust,
            f'{fa_money(credited)} بابت سفارش {fa_num(order.id)} به اعتبار شما در لینک‌بان برگشت.',
        )
    if full:
        told = set()
        for it in order.items.select_related('manager'):
            mid = it.manager.bale_user_id if it.manager else ''
            if not mid or mid in told:
                continue
            told.add(mid)
            bc.send_message(
                mid,
                f'سفارش {fa_num(order.id)} لغو شد و روزش آزاد است. مبلغ به اعتبار مشتری برگشت.',
            )
    return {'ok': True, 'credited': credited, 'full': full, 'order_status': order.status}


def cancel_customer_order(order: Order) -> Dict[str, Any]:
    """پیش از پرداخت روز آزاد می‌شود. بعد از پرداخت، تا ۲ ساعت مانده به انتشار به اعتبار برمی‌گردد."""
    if order.status == 'cancelled':
        return {'ok': True, 'order_status': 'cancelled', 'already': True}
    if order.status == 'paid':
        if not refund_window_open(order):
            from bot_flow.jalali import format_slot

            start = publish_start(order)
            when = format_slot(timezone.localtime(start)) if start else ''
            return {
                'ok': False,
                'error': 'too_late',
                'message': (
                    'از ۲ ساعت پیش از انتشار دیگر لغو نمی‌شود. '
                    + (f'زمان انتشار: {when}. ' if when else '')
                    + 'اگر مشکلی هست، اعتراض ثبت کنید.'
                ),
            }
        return refund_paid_order(order, reason=f'لغو سفارش {fa_num(order.id)} توسط مشتری')
    if order.status not in (
        'draft',
        'waiting_banner',
        'waiting_managers',
        'waiting_customer_confirm',
        'waiting_payment',
    ):
        return {'ok': False, 'error': 'not_cancellable'}
    touched = _release_open_items(order, 'customer_declined')
    order.status = 'cancelled'
    order.total_amount = 0
    order.save(update_fields=['status', 'total_amount'])
    CustomerDraft.objects.filter(order=order).delete()
    cust = order.customer.bale_user_id
    if cust:
        bc.send_message(
            cust,
            f'سفارش {fa_num(order.id)} لغو شد و روزهایش برای دیگران آزاد شد.',
        )
    told = set()
    for item in touched:
        mid = item.manager.bale_user_id if item.manager else ''
        if not mid or mid in told:
            continue
        told.add(mid)
        bc.send_message(
            mid,
            f'مشتری سفارش {fa_num(order.id)} را پیش از پرداخت لغو کرد. آن روز آزاد است.',
        )
    return {'ok': True, 'order_status': 'cancelled', 'released': len(touched)}


def retire_tariff(tariff: Tariff) -> bool:
    """تعرفهٔ دارای سفارش یا رزرو حذف نمی‌شود تا ردیف‌های مدیر پاک نشود.

    True یعنی فقط خاموش شد و داده‌ها ماندند.
    """
    from orders.models import SlotReservation

    kept = (
        OrderItem.objects.filter(tariff=tariff).exists()
        or SlotReservation.objects.filter(tariff=tariff).exists()
    )
    if kept:
        if tariff.is_active:
            tariff.is_active = False
            tariff.save(update_fields=['is_active'])
        return True
    tariff.delete()
    return False


def cancel_unpaid_orders() -> int:
    """سفارش آمادهٔ پرداخت که مهلتش گذشته، روز را برای مشتری بعدی آزاد می‌کند."""
    now = timezone.now()
    n = 0
    qs = Order.objects.filter(
        status='waiting_payment',
        managers_deadline__isnull=False,
        managers_deadline__lt=now,
    ).select_related('customer')
    for order in qs:
        _release_open_items(order, 'expired')
        order.status = 'cancelled'
        order.total_amount = 0
        order.save(update_fields=['status', 'total_amount'])
        cust = order.customer.bale_user_id
        if cust:
            bc.send_message(
                cust,
                f'مهلت پرداخت سفارش {fa_num(order.id)} تمام شد و روزها دوباره آزاد شدند.',
            )
        n += 1
    return n
