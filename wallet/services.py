"""Wallet balance, credits, payouts for managers and customers."""
from __future__ import annotations

import logging
import os
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from integrations import bale_client as bc
from users.models import User
from wallet.models import BankAccount, PayoutBatch, PayoutRequest, WalletLedger

logger = logging.getLogger(__name__)

PLATFORM_FEE_PERCENT = int(os.environ.get('PLATFORM_FEE_PERCENT', '14'))
MIN_PAYOUT_TOMAN = int(os.environ.get('MIN_PAYOUT_TOMAN', '100000'))
PAYOUT_COOLDOWN_DAYS = int(os.environ.get('PAYOUT_COOLDOWN_DAYS', '7'))
OPERATOR_BALE_ID = os.environ.get('OPERATOR_BALE_ID', '').strip()

IBAN_RE = re.compile(r'^IR\d{24}$', re.I)


def fee_amount(price_toman: int) -> int:
    return int(round(price_toman * PLATFORM_FEE_PERCENT / 100))


def net_manager_earn(price_toman: int) -> int:
    return price_toman - fee_amount(price_toman)


def balance_breakdown(user: User) -> Dict[str, int]:
    qs = WalletLedger.objects.filter(user=user)
    total = qs.aggregate(s=Sum('amount'))['s'] or 0
    locked = (
        PayoutRequest.objects.filter(user=user, status='pending').aggregate(s=Sum('amount_toman'))[
            's'
        ]
        or 0
    )
    paid = (
        PayoutRequest.objects.filter(user=user, status='paid').aggregate(s=Sum('amount_toman'))['s']
        or 0
    )
    return {
        'available': total,
        'locked_pending': locked,
        'paid_out': paid,
        'ledger_sum': total,
    }


def available_balance(user: User) -> int:
    return max(0, balance_breakdown(user)['available'])


@transaction.atomic
def credit(
    user: User,
    amount: int,
    entry_type: str,
    ref: str = '',
    note: str = '',
) -> WalletLedger:
    if amount == 0:
        raise ValueError('amount must be non-zero')
    return WalletLedger.objects.create(
        user=user,
        amount=amount,
        entry_type=entry_type,
        ref=ref[:64],
        note=note[:255],
    )


def credit_manager_for_execution(manager: User, price_toman: int, order_item_id: int) -> WalletLedger:
    net = net_manager_earn(price_toman)
    return credit(
        manager,
        net,
        'earn',
        ref=f'item:{order_item_id}',
        note=f'اجرا آیتم #{order_item_id} خالص پس از {PLATFORM_FEE_PERCENT}%',
    )


def credit_customer_refund(
    customer: User, amount: int, order_item_id: int, reason: str
) -> WalletLedger:
    return credit(
        customer,
        amount,
        'refund',
        ref=f'item:{order_item_id}',
        note=reason[:255],
    )


def apply_manager_penalty(manager: User, price_toman: int, order_item_id: int) -> WalletLedger:
    pen = fee_amount(price_toman)
    if pen <= 0:
        pen = 1
    return credit(
        manager,
        -pen,
        'penalty',
        ref=f'item:{order_item_id}',
        note=f'جریمه عدم انتشار آیتم #{order_item_id}',
    )


def validate_iban(iban: str) -> bool:
    return bool(IBAN_RE.match((iban or '').replace(' ', '').upper()))


def save_bank_account(
    user: User, iban: str, holder_name: str, make_default: bool = True
) -> BankAccount:
    iban = iban.replace(' ', '').upper()
    if not validate_iban(iban):
        raise ValueError('invalid_iban')
    holder_name = (holder_name or '').strip()
    if not holder_name:
        raise ValueError('need_holder_name')
    acc, _ = BankAccount.objects.update_or_create(
        user=user,
        iban=iban,
        defaults={'holder_name': holder_name},
    )
    if make_default:
        BankAccount.objects.filter(user=user).exclude(id=acc.id).update(is_default=False)
        acc.is_default = True
        acc.save(update_fields=['is_default'])
    return acc


def can_request_payout(user: User) -> Tuple[bool, str]:
    if PayoutRequest.objects.filter(user=user, status='pending').exists():
        return False, 'already_pending'
    last_paid = (
        PayoutRequest.objects.filter(user=user, status='paid').order_by('-paid_at', '-id').first()
    )
    if last_paid and last_paid.paid_at:
        if timezone.now() - last_paid.paid_at < timedelta(days=PAYOUT_COOLDOWN_DAYS):
            return False, 'weekly_limit'
    avail = available_balance(user)
    if avail < MIN_PAYOUT_TOMAN:
        return False, 'below_minimum'
    if not BankAccount.objects.filter(user=user).exists():
        return False, 'no_bank'
    return True, 'ok'


@transaction.atomic
def request_payout(
    user: User, bank: BankAccount, amount: Optional[int] = None
) -> Dict[str, Any]:
    ok, reason = can_request_payout(user)
    if not ok:
        return {'ok': False, 'error': reason}

    avail = available_balance(user)
    if amount is None:
        amount = avail
    if amount < MIN_PAYOUT_TOMAN:
        return {'ok': False, 'error': 'below_minimum'}
    if amount > avail:
        return {'ok': False, 'error': 'insufficient'}

    credit(user, -amount, 'payout_lock', ref='payout:new', note='قفل درخواست تسویه')
    pr = PayoutRequest.objects.create(
        user=user,
        amount_toman=amount,
        amount_rial=amount * 10,
        iban=bank.iban,
        holder_name=bank.holder_name,
        status='pending',
    )
    WalletLedger.objects.filter(user=user, ref='payout:new').order_by('-id').update(
        ref=f'payout:{pr.id}'
    )
    return {'ok': True, 'payout': pr}


@transaction.atomic
def build_payout_batch(operator: User) -> Dict[str, Any]:
    pending = list(
        PayoutRequest.objects.filter(status='pending', batch__isnull=True).select_related('user')
    )
    if not pending:
        return {'ok': False, 'error': 'no_pending'}

    lines: List[str] = []
    for pr in pending:
        lines.append(f'{pr.amount_rial},{pr.iban},,{pr.holder_name}')

    text = '\n'.join(lines)
    batch = PayoutBatch.objects.create(created_by=operator, file_text=text)
    for pr in pending:
        pr.batch = batch
        pr.save(update_fields=['batch'])

    return {'ok': True, 'batch': batch, 'count': len(pending), 'file_text': text}


@transaction.atomic
def mark_batch_paid(batch_id: int) -> Dict[str, Any]:
    try:
        batch = PayoutBatch.objects.get(id=batch_id)
    except PayoutBatch.DoesNotExist:
        return {'ok': False, 'error': 'batch_not_found'}

    if batch.paid_at:
        return {'ok': False, 'error': 'already_paid'}

    now = timezone.now()
    batch.paid_at = now
    batch.save(update_fields=['paid_at'])

    notified = []
    for pr in batch.requests.filter(status='pending'):
        pr.status = 'paid'
        pr.paid_at = now
        pr.save(update_fields=['status', 'paid_at'])
        # موجودی قبلاً با payout_lock کم شده
        if pr.user.bale_user_id:
            bc.send_message(
                pr.user.bale_user_id,
                f'✅ مبلغ {pr.amount_toman:,} تومان به‌صورت پایا به حساب شما واریز شد.',
            )
            notified.append(pr.user.bale_user_id)

    return {'ok': True, 'batch_id': batch.id, 'notified': notified}


def is_operator(bale_user_id: str) -> bool:
    return bool(OPERATOR_BALE_ID) and str(bale_user_id) == str(OPERATOR_BALE_ID)
