"""Ad execution lifecycle: remind → published → customer/operator confirm → wallet."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from integrations import bale_client as bc
from orders.models import OrderItem
from users.models import User
from wallet.services import (
    OPERATOR_BALE_ID,
    apply_manager_penalty,
    credit_customer_refund,
    credit_manager_for_execution,
    fee_amount,
)

logger = logging.getLogger(__name__)

REMIND_HOURS_BEFORE = int(os.environ.get('REMIND_HOURS_BEFORE', '2'))
CUSTOMER_CONFIRM_HOURS = int(os.environ.get('CUSTOMER_EXEC_CONFIRM_HOURS', '12'))


def _item_qs():
    return OrderItem.objects.select_related(
        'order', 'order__customer', 'channel', 'tariff', 'tariff__group', 'manager'
    )


def send_publish_reminders() -> int:
    """Remind managers 2h before slot start for paid items not yet reminded."""
    now = timezone.now()
    window_end = now + timedelta(hours=REMIND_HOURS_BEFORE)
    # paid items whose start is within next REMIND_HOURS and not yet reminded
    items = _item_qs().filter(
        execution_status='paid',
        requested_start__lte=window_end,
        requested_start__gte=now - timedelta(minutes=30),
    )
    n = 0
    for it in items:
        if not it.manager or not it.manager.bale_user_id:
            continue
        owner = (
            it.tariff.group.name
            if it.tariff.group_id
            else (it.channel.name if it.channel else '?')
        )
        kb = bc.inline_keyboard([
            [{'text': '✅ منتشر شد', 'callback_data': f'published:{it.id}'}]
        ])
        bc.send_message(
            it.manager.bale_user_id,
            f'⏰ یادآوری انتشار\n'
            f'آیتم #{it.id} — {owner}\n'
            f'زمان: {timezone.localtime(it.effective_start)}\n'
            f'پس از ارسال بنر در کانال، دکمه زیر را بزنید.',
            reply_markup=kb,
        )
        it.execution_status = 'remind_sent'
        it.save(update_fields=['execution_status'])
        n += 1
    return n


@transaction.atomic
def mark_published(item_id: int, manager_bale_id: str, channel_link: str = '') -> Dict[str, Any]:
    try:
        it = _item_qs().get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}

    if it.manager and str(it.manager.bale_user_id) != str(manager_bale_id):
        return {'ok': False, 'error': 'not_manager'}
    if it.execution_status not in ('paid', 'remind_sent'):
        return {'ok': False, 'error': 'bad_status', 'status': it.execution_status}

    it.execution_status = 'awaiting_customer_confirm'
    it.published_at = timezone.now()
    it.customer_confirm_deadline = timezone.now() + timedelta(hours=CUSTOMER_CONFIRM_HOURS)
    if channel_link:
        it.published_link = channel_link[:500]
    elif it.channel and it.channel.link:
        it.published_link = it.channel.link[:500]
    it.save()

    cust = it.order.customer.bale_user_id
    owner = (
        it.tariff.group.name if it.tariff.group_id else (it.channel.name if it.channel else '?')
    )
    link = it.published_link or ''
    kb = bc.inline_keyboard([
        [
            {'text': '✅ تأیید انتشار', 'callback_data': f'execok:{it.id}'},
            {'text': '❌ منتشر نشده', 'callback_data': f'execno:{it.id}'},
        ]
    ])
    if cust:
        bc.send_message(
            cust,
            f'📢 بنر شما در «{owner}» ارسال شد.\n'
            f'{("لینک: " + link) if link else ""}\n'
            f'لطفاً تأیید کنید (مهلت {CUSTOMER_CONFIRM_HOURS} ساعت).',
            reply_markup=kb,
        )
    return {'ok': True, 'item_id': it.id}


@transaction.atomic
def customer_confirm_execution(item_id: int, customer_bale_id: str, ok: bool) -> Dict[str, Any]:
    try:
        it = _item_qs().get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}

    if str(it.order.customer.bale_user_id) != str(customer_bale_id):
        return {'ok': False, 'error': 'not_customer'}
    if it.execution_status != 'awaiting_customer_confirm':
        return {'ok': False, 'error': 'bad_status'}

    if ok:
        return _finalize_executed(it)
    # customer says not published → operator review
    it.execution_status = 'awaiting_operator'
    it.save(update_fields=['execution_status'])
    _notify_operator_review(it)
    return {'ok': True, 'status': 'awaiting_operator'}


def _finalize_executed(it: OrderItem) -> Dict[str, Any]:
    it.execution_status = 'executed'
    it.executed_at = timezone.now()
    it.save(update_fields=['execution_status', 'executed_at'])
    if it.manager:
        credit_manager_for_execution(it.manager, it.price, it.id)
    cust = it.order.customer.bale_user_id
    if cust:
        bc.send_message(cust, f'✅ آیتم #{it.id} به‌عنوان اجراشده ثبت شد.')
    if it.manager and it.manager.bale_user_id:
        net = it.price - fee_amount(it.price)
        bc.send_message(
            it.manager.bale_user_id,
            f'✅ آیتم #{it.id} اجرا شد. {net:,} تومان به کیف پول شما اضافه شد.',
        )
    return {'ok': True, 'status': 'executed'}


def _notify_operator_review(it: OrderItem) -> None:
    if not OPERATOR_BALE_ID:
        logger.warning('OPERATOR_BALE_ID not set')
        return
    owner = (
        it.tariff.group.name if it.tariff.group_id else (it.channel.name if it.channel else '?')
    )
    kb = bc.inline_keyboard([
        [
            {'text': '✅ اجرا شده', 'callback_data': f'opok:{it.id}'},
            {'text': '❌ اجرا نشده', 'callback_data': f'opno:{it.id}'},
        ]
    ])
    text = (
        f'🔎 بررسی انتشار\n'
        f'آیتم #{it.id} | سفارش #{it.order_id}\n'
        f'هدف: {owner}\n'
        f'لینک: {it.published_link or "—"}\n'
        f'مبلغ: {it.price:,} ت'
    )
    bc.send_message(OPERATOR_BALE_ID, text, reply_markup=kb)
    # forward banner if possible
    order = it.order
    if order.banner_message_id and order.banner_from_chat_id:
        try:
            bc.forward_message(
                OPERATOR_BALE_ID, order.banner_from_chat_id, int(order.banner_message_id)
            )
        except Exception:
            logger.exception('forward to operator')


@transaction.atomic
def operator_resolve(item_id: int, operator_bale_id: str, executed: bool) -> Dict[str, Any]:
    from wallet.services import is_operator

    if not is_operator(operator_bale_id):
        return {'ok': False, 'error': 'not_operator'}
    try:
        it = _item_qs().get(id=item_id)
    except OrderItem.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}
    if it.execution_status not in ('awaiting_operator', 'awaiting_customer_confirm'):
        return {'ok': False, 'error': 'bad_status'}

    if executed:
        return _finalize_executed(it)

    # not executed: refund customer full price, penalize manager 14%
    it.execution_status = 'failed_publish'
    it.save(update_fields=['execution_status'])
    credit_customer_refund(
        it.order.customer, it.price, it.id, 'عدم انتشار — بازگشت به کیف مشتری'
    )
    if it.manager:
        apply_manager_penalty(it.manager, it.price, it.id)

    if it.order.customer.bale_user_id:
        bc.send_message(
            it.order.customer.bale_user_id,
            f'مبلغ {it.price:,} تومان بابت آیتم #{it.id} به کیف پول شما برگشت.',
        )
    if it.manager and it.manager.bale_user_id:
        pen = fee_amount(it.price)
        bc.send_message(
            it.manager.bale_user_id,
            f'آیتم #{it.id} منتشر نشده ثبت شد. جریمه {pen:,} تومان.',
        )
    return {'ok': True, 'status': 'failed_publish'}


def escalate_unconfirmed() -> int:
    """After 12h without customer confirm → operator."""
    now = timezone.now()
    items = _item_qs().filter(
        execution_status='awaiting_customer_confirm',
        customer_confirm_deadline__lt=now,
    )
    n = 0
    for it in items:
        it.execution_status = 'awaiting_operator'
        it.save(update_fields=['execution_status'])
        _notify_operator_review(it)
        n += 1
    return n
