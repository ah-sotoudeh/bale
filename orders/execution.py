"""Ad execution lifecycle: remind (manual) → published verify → wallet."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict

from django.db import transaction
from django.utils import timezone

from channels_app.models import Channel
from integrations import bale_client as bc
from orders.models import OrderItem
from orders.publish import targets_for_item
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
    """Remind managers before slot for paid items on *manual* channels only.

    هر کانال می‌تواند manual_remind_hours جدا داشته باشد (پیش‌فرض ۲).
    """
    now = timezone.now()
    items = _item_qs().filter(
        execution_status='paid',
        requested_start__gte=now - timedelta(minutes=30),
        requested_start__lte=now + timedelta(hours=48),
    )
    n = 0
    for it in items:
        if not it.manager or not it.manager.bale_user_id:
            continue
        channels = targets_for_item(it)
        manual_chs = [
            c for c in channels
            if (c.publish_mode or Channel.PUBLISH_BOT) == Channel.PUBLISH_MANUAL
        ]
        if not manual_chs:
            continue
        start = it.effective_start
        if not start:
            continue
        start_cmp = start if timezone.is_aware(start) else timezone.make_aware(start)
        max_h = max(
            (getattr(c, 'manual_remind_hours', None) or REMIND_HOURS_BEFORE)
            for c in manual_chs
        )
        if start_cmp > now + timedelta(hours=max_h):
            continue
        owner = (
            it.tariff.group.name
            if it.tariff.group_id
            else (it.channel.name if it.channel else '?')
        )
        rows = []
        for ch in manual_chs:
            rows.append([{
                'text': f'✅ منتشر شد — {ch.name[:20]}',
                'callback_data': f'published:{it.id}:{ch.id}',
            }])
        kb = bc.inline_keyboard(rows)
        bc.send_message(
            it.manager.bale_user_id,
            f'⏰ یادآوری انتشار (ارسال دستی)\n'
            f'آیتم #{it.id} — {owner}\n'
            f'زمان: {timezone.localtime(it.effective_start)}\n'
            f'پس از ارسال بنر در کانال، دکمه زیر را بزنید.',
            reply_markup=kb,
        )
        it.execution_status = 'remind_sent'
        it.save(update_fields=['execution_status'])
        n += 1
    return n
