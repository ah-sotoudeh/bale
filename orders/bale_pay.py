"""درگاه کیف‌پول بله: createInvoiceLink، pre_checkout و successful_payment."""
from __future__ import annotations

import logging
from typing import Any, Dict

from integrations import bale_client as bc
from orders.models import Order
from orders.services import process_payment_paid

logger = logging.getLogger(__name__)


def invoice_for_order(order: Order) -> Dict[str, Any]:
    if order.status == 'paid':
        return {'ok': False, 'error': 'already_paid'}
    if order.status != 'waiting_payment':
        return {'ok': False, 'error': 'not_waiting_payment'}
    if order.total_amount <= 0:
        return {'ok': False, 'error': 'bad_amount'}
    link = bc.create_invoice_link(
        title=f'سفارش {order.id}'[:32],
        description=f'پرداخت تبلیغ — سفارش {order.id}',
        payload=f'order-{order.id}',
        amount_toman=order.total_amount,
    )
    if not link.get('ok'):
        return link
    return {
        'ok': True,
        'invoice_params': link['invoice_params'],
        'amount_toman': order.total_amount,
        'amount_rial': link.get('amount_rial'),
        'order_id': order.id,
    }


def handle_pre_checkout(query: Dict[str, Any]) -> None:
    qid = str(query.get('id') or '')
    payload = str(query.get('invoice_payload') or '')
    try:
        amount = int(query.get('total_amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if not payload.startswith('order-'):
        bc.answer_pre_checkout_query(qid, False, 'سفارش نامعتبر است')
        return
    try:
        order_id = int(payload.split('-', 1)[1])
        order = Order.objects.get(id=order_id)
    except (ValueError, Order.DoesNotExist):
        bc.answer_pre_checkout_query(qid, False, 'سفارش پیدا نشد')
        return
    if order.status == 'paid':
        bc.answer_pre_checkout_query(qid, False, 'این سفارش قبلاً پرداخت شده است')
        return
    if order.status != 'waiting_payment':
        bc.answer_pre_checkout_query(qid, False, 'سفارش آماده پرداخت نیست')
        return
    expected = bc.toman_to_rial(order.total_amount)
    if amount != expected:
        bc.answer_pre_checkout_query(qid, False, 'مبلغ با فاکتور یکی نیست')
        return
    bc.answer_pre_checkout_query(qid, True)


def handle_successful_payment(message: Dict[str, Any]) -> None:
    pay = message.get('successful_payment') or {}
    payload = str(pay.get('invoice_payload') or '')
    if not payload.startswith('order-'):
        logger.warning('successful_payment ignored payload=%s', payload)
        return
    try:
        order_id = int(payload.split('-', 1)[1])
    except ValueError:
        return
    result = process_payment_paid(order_id)
    if result.get('ok'):
        return
    chat_id = str((message.get('chat') or {}).get('id') or '')
    if chat_id:
        bc.send_message(chat_id, f'پرداخت رسید ولی ثبت سفارش نشد: {result.get("error")}')
