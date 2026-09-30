"""درگاه کیف‌پول بله: createInvoiceLink، pre_checkout و successful_payment.

سقف هر انتقال کیف‌پول یک میلیون تومان است. مبلغ بیشتر چند فاکتور جدا می‌شود
و سفارش فقط بعد از رسیدن همهٔ بخش‌ها پرداخت‌شده حساب می‌شود.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from bot_flow.messages import fa_money, fa_num
from integrations import bale_client as bc
from orders.models import Order
from orders.services import process_payment_paid
from wallet.models import WalletLedger

logger = logging.getLogger(__name__)

# سقف هر درخواست پول در کیف‌پول بازو، به تومان.
WALLET_MAX_TOMAN = 1_000_000

_PAYLOAD = re.compile(r'^order-(\d+)(?:-p(\d+)-(\d+))?$')


def payment_parts(amount_toman: int) -> list[int]:
    """مبلغ را به قطعه‌های حداکثر یک میلیون تومان می‌شکند."""
    try:
        left = int(amount_toman)
    except (TypeError, ValueError):
        return []
    if left <= 0:
        return []
    if left <= WALLET_MAX_TOMAN:
        return [left]
    parts: list[int] = []
    while left > 0:
        chunk = min(WALLET_MAX_TOMAN, left)
        parts.append(chunk)
        left -= chunk
    return parts


def parse_invoice_payload(payload: str) -> Optional[Dict[str, Any]]:
    match = _PAYLOAD.match(str(payload or '').strip())
    if not match:
        return None
    order_id = int(match.group(1))
    if match.group(2) is None:
        return {'order_id': order_id, 'part': None, 'amount': None}
    return {
        'order_id': order_id,
        'part': int(match.group(2)),
        'amount': int(match.group(3)),
    }


def _part_key(order_id: int, index: int) -> str:
    return f'inv:{order_id}:{index}'[:80]


def paid_part_amounts(order: Order) -> Dict[int, int]:
    prefix = f'inv:{order.id}:'
    found: Dict[int, int] = {}
    rows = WalletLedger.objects.filter(
        user_id=order.customer_id,
        idempotency_key__startswith=prefix,
    )
    for row in rows:
        tail = (row.idempotency_key or '')[len(prefix):]
        if not tail.isdigit():
            continue
        try:
            found[int(tail)] = int(row.note or 0)
        except (TypeError, ValueError):
            continue
    return found


def order_is_fully_paid(order: Order) -> bool:
    parts = payment_parts(order.total_amount)
    got = paid_part_amounts(order)
    return bool(parts) and all(got.get(index) == amount for index, amount in enumerate(parts, start=1))


def _slice_for(order: Order, parsed: Dict[str, Any]) -> Optional[tuple[int, int]]:
    """شمارهٔ بخش و مبلغ تومان، اگر با جمع سفارش بخواند."""
    parts = payment_parts(order.total_amount)
    if not parts:
        return None
    if parsed.get('part') is None:
        if len(parts) != 1:
            return None
        return 1, parts[0]
    index = int(parsed['part'])
    if index < 1 or index > len(parts):
        return None
    if int(parsed.get('amount') or 0) != parts[index - 1]:
        return None
    return index, parts[index - 1]


def _payload_for(order_id: int, index: int, amount: int, part_count: int) -> str:
    if part_count == 1:
        return f'order-{order_id}'
    return f'order-{order_id}-p{index}-{amount}'


def _title_for(order_id: int, index: int, part_count: int) -> str:
    if part_count == 1:
        return f'سفارش {order_id}'[:32]
    return f'سفارش {order_id} بخش {index}'[:32]


def _description_for(order_id: int, index: int, amount: int, part_count: int) -> str:
    if part_count == 1:
        return f'پرداخت تبلیغ، سفارش {order_id}'[:255]
    return (
        f'بخش {index} از {part_count}، سفارش {order_id}، {amount:,} تومان'
    )[:255]


def record_paid_part(order: Order, index: int, amount: int) -> bool:
    """True یعنی این بخش تازه ثبت شد. ردیف با مبلغ صفر است تا موجودی کیف پول عوض نشود."""
    key = _part_key(order.id, index)
    if WalletLedger.objects.filter(idempotency_key=key).exists():
        return False
    try:
        WalletLedger.objects.create(
            user=order.customer,
            amount=0,
            entry_type='adjust',
            ref=f'order-{order.id}',
            note=str(int(amount)),
            idempotency_key=key,
        )
    except IntegrityError:
        return False
    return True


def _invoice_recently_sent(order_id: int, index: int) -> bool:
    from datetime import timedelta

    from django.utils import timezone

    row = WalletLedger.objects.filter(idempotency_key=f'invsent:{order_id}:{index}').first()
    if not row or not row.created_at:
        return False
    return timezone.now() - row.created_at < timedelta(minutes=20)


def _mark_invoice_sent(order: Order, index: int) -> None:
    from django.utils import timezone

    key = f'invsent:{order.id}:{index}'
    row = WalletLedger.objects.filter(idempotency_key=key).first()
    if row:
        row.created_at = timezone.now()
        row.save(update_fields=['created_at'])
        return
    WalletLedger.objects.create(
        user=order.customer,
        amount=0,
        entry_type='adjust',
        ref=f'order-{order.id}',
        note='invoice-sent',
        idempotency_key=key,
    )


def send_order_invoices(order: Order, chat_id: str) -> Dict[str, Any]:
    """فاکتورهای مانده را می‌فرستد. هر کدام حداکثر یک میلیون تومان است."""
    parts = payment_parts(order.total_amount)
    paid = paid_part_amounts(order)
    sent = 0
    failed = 0
    skipped = 0
    for index, amount in enumerate(parts, start=1):
        if paid.get(index) == amount:
            skipped += 1
            continue
        if _invoice_recently_sent(order.id, index):
            skipped += 1
            continue
        result = bc.create_payment_request(
            chat_id=str(chat_id),
            amount=amount,
            title=_title_for(order.id, index, len(parts)),
            description=_description_for(order.id, index, amount, len(parts)),
            payload=_payload_for(order.id, index, amount, len(parts)),
        )
        if result.get('ok'):
            sent += 1
            _mark_invoice_sent(order, index)
        else:
            failed += 1
    return {
        'ok': bool(parts) and failed == 0 and sent + skipped == len(parts),
        'sent': sent,
        'failed': failed,
        'skipped': skipped,
        'parts': len(parts),
    }


def announce_invoices(chat_id: str, result: Dict[str, Any]) -> None:
    sent = int(result.get('sent') or 0)
    parts = int(result.get('parts') or 0)
    failed = int(result.get('failed') or 0)
    if sent and parts <= 1:
        bc.send_message(
            str(chat_id),
            'فاکتور بالا را با کیف پول بله بپردازید. تا پرداخت، پولی در امانت نیست.',
        )
    elif sent:
        bc.send_message(
            str(chat_id),
            f'{fa_num(sent)} فاکتور کیف‌پول آمد. هر کدام را جدا پرداخت کنید. '
            'سفارش بعد از پرداخت همهٔ بخش‌ها ثبت می‌شود.',
        )
    if failed and sent:
        bc.send_message(
            str(chat_id),
            'بعضی فاکتورها نرسید. از سفارش‌ها دوباره پرداخت را بزنید.',
        )


def invoice_for_order(order: Order) -> Dict[str, Any]:
    if order.status == 'paid' or order_is_fully_paid(order):
        if order.status == 'waiting_payment' and order_is_fully_paid(order):
            process_payment_paid(order.id)
        return {'ok': False, 'error': 'already_paid'}
    if order.status != 'waiting_payment':
        return {'ok': False, 'error': 'not_waiting_payment'}
    parts = payment_parts(order.total_amount)
    if not parts:
        return {'ok': False, 'error': 'bad_amount'}
    paid = paid_part_amounts(order)
    pending = [(index, amount) for index, amount in enumerate(parts, start=1) if paid.get(index) != amount]
    index, amount = pending[0]
    link = bc.create_invoice_link(
        title=_title_for(order.id, index, len(parts)),
        description=_description_for(order.id, index, amount, len(parts)),
        payload=_payload_for(order.id, index, amount, len(parts)),
        amount_toman=amount,
    )
    if not link.get('ok'):
        return link
    message = ''
    if len(parts) > 1:
        message = (
            f'این بخش {fa_num(index)} از {fa_num(len(parts))} است، {fa_money(amount)}. '
            'بعد از پرداخت، برای بخش بعد دوباره پرداخت را بزنید.'
        )
    return {
        'ok': True,
        'invoice_params': link['invoice_params'],
        'amount_toman': amount,
        'amount_rial': link.get('amount_rial'),
        'order_id': order.id,
        'part': index,
        'parts': len(parts),
        'message': message,
    }


def handle_pre_checkout(query: Dict[str, Any]) -> None:
    qid = str(query.get('id') or '')
    parsed = parse_invoice_payload(str(query.get('invoice_payload') or ''))
    try:
        amount = int(query.get('total_amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if not parsed:
        bc.answer_pre_checkout_query(qid, False, 'سفارش نامعتبر است')
        return
    try:
        order = Order.objects.get(id=parsed['order_id'])
    except Order.DoesNotExist:
        bc.answer_pre_checkout_query(qid, False, 'سفارش پیدا نشد')
        return
    if order.status == 'paid':
        bc.answer_pre_checkout_query(qid, False, 'این سفارش قبلاً پرداخت شده است')
        return
    if order.status in ('cancelled', 'rejected'):
        bc.answer_pre_checkout_query(qid, False, 'این سفارش لغو شده است')
        return
    if order.managers_deadline and order.managers_deadline < timezone.now():
        bc.answer_pre_checkout_query(qid, False, 'مهلت پرداخت این سفارش تمام شده')
        return
    if order.status != 'waiting_payment':
        bc.answer_pre_checkout_query(qid, False, 'سفارش آماده پرداخت نیست')
        return
    if parsed.get('part') is None and len(payment_parts(order.total_amount)) > 1:
        bc.answer_pre_checkout_query(qid, False, 'این سفارش چند فاکتور دارد. هر فاکتور را جدا پرداخت کنید.')
        return
    sliced = _slice_for(order, parsed)
    if not sliced:
        bc.answer_pre_checkout_query(qid, False, 'مبلغ با فاکتور یکی نیست')
        return
    index, part_amount = sliced
    if paid_part_amounts(order).get(index) == part_amount:
        bc.answer_pre_checkout_query(qid, False, 'این بخش قبلاً پرداخت شده است')
        return
    if amount != bc.toman_to_rial(part_amount):
        bc.answer_pre_checkout_query(qid, False, 'مبلغ با فاکتور یکی نیست')
        return
    bc.answer_pre_checkout_query(qid, True)


def _payment_charge_id(pay: Dict[str, Any]) -> str:
    return str(
        pay.get('telegram_payment_charge_id') or pay.get('provider_payment_charge_id') or ''
    ).strip()[:48]


def remember_payment_charge(order: Order, pay: Dict[str, Any]) -> bool:
    """True یعنی این کد پیگیری تازه است."""
    cid = _payment_charge_id(pay)
    if not cid:
        return False
    key = f'charge:{cid}'[:80]
    if WalletLedger.objects.filter(idempotency_key=key).exists():
        return False
    try:
        WalletLedger.objects.create(
            user=order.customer,
            amount=0,
            entry_type='adjust',
            ref=f'order-{order.id}',
            note=cid,
            idempotency_key=key,
        )
    except IntegrityError:
        return False
    return True


def _credit_extra_payment(order: Order, paid_rial: int, pay: Dict[str, Any], chat_id: str = '') -> None:
    if not remember_payment_charge(order, pay):
        return
    toman = int(paid_rial) // 10
    if toman <= 0:
        return
    from wallet.services import credit

    credit(
        order.customer,
        toman,
        'refund',
        ref=f'order:{order.id}',
        note=f'پرداخت تکراری سفارش {fa_num(order.id)} به اعتبار برگشت',
        idempotency_key=f'extra:{_payment_charge_id(pay)}'[:80],
    )
    if chat_id:
        bc.send_message(
            chat_id,
            f'این سفارش قبلاً پرداخت شده بود. {fa_money(toman)} به اعتبار شما در لینک‌بان برگشت.',
        )


def handle_successful_payment(message: Dict[str, Any]) -> None:
    pay = message.get('successful_payment') or {}
    parsed = parse_invoice_payload(str(pay.get('invoice_payload') or ''))
    chat_id = str((message.get('chat') or {}).get('id') or '')
    if not parsed:
        logger.warning('successful_payment ignored payload')
        return
    try:
        paid_rial = int(pay.get('total_amount') or 0)
    except (TypeError, ValueError):
        paid_rial = 0

    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(id=parsed['order_id'])
        except Order.DoesNotExist:
            if chat_id:
                bc.send_message(chat_id, 'پرداخت رسید ولی سفارش پیدا نشد.')
            return
        if order.status == 'paid':
            _credit_extra_payment(order, paid_rial, pay, chat_id)
            return
        if order.status != 'waiting_payment':
            if chat_id:
                bc.send_message(chat_id, 'پرداخت رسید ولی این سفارش آمادهٔ ثبت نبود.')
            return
        if parsed.get('part') is None and len(payment_parts(order.total_amount)) > 1:
            if chat_id:
                bc.send_message(chat_id, 'این سفارش چند فاکتور دارد. هر فاکتور را جدا پرداخت کنید.')
            return
        sliced = _slice_for(order, parsed)
        if not sliced or paid_rial != bc.toman_to_rial(sliced[1]):
            if chat_id:
                bc.send_message(chat_id, 'مبلغ این پرداخت با فاکتور یکی نیست.')
            return
        index, part_amount = sliced
        fresh = record_paid_part(order, index, part_amount)
        remember_payment_charge(order, pay)
        complete = order_is_fully_paid(order)
        parts = payment_parts(order.total_amount)
        got = paid_part_amounts(order)

    if complete:
        result = process_payment_paid(order.id)
        if result.get('ok'):
            return
        if chat_id:
            bc.send_message(chat_id, 'همهٔ بخش‌ها رسید ولی ثبت سفارش کامل نشد. پشتیبانی را خبر کنید.')
        return

    if not chat_id:
        return
    if not fresh:
        bc.send_message(chat_id, f'بخش {fa_num(index)} قبلاً ثبت شده بود.')
        return
    left = [amount for n, amount in enumerate(parts, start=1) if got.get(n) != amount]
    bc.send_message(
        chat_id,
        f'بخش {fa_num(index)} از {fa_num(len(parts))} ثبت شد ({fa_money(part_amount)}).\n'
        f'مانده: {fa_money(sum(left))}.\n'
        f'{fa_num(len(left))} درخواست دیگر را هم پرداخت کنید.',
    )
