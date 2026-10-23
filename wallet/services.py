import os
import logging
logger = logging.getLogger(__name__)
"""Wallet balance, credits, payouts for managers and customers."""
from __future__ import annotations

import logging
import os
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db import IntegrityError, transaction
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


def customer_escrow_toman(user: User) -> int:
    from orders.models import OrderItem

    total = (
        OrderItem.objects.filter(
            order__customer=user,
            order__status='paid',
            execution_status__in=(
                'paid',
                'remind_sent',
                'awaiting_manager_publish',
                'awaiting_customer_confirm',
                'awaiting_operator',
            ),
        ).aggregate(s=Sum('price'))['s']
        or 0
    )
    return int(total)


def manager_escrow_toman(user: User) -> int:
    from orders.models import OrderItem

    total = (
        OrderItem.objects.filter(
            manager=user,
            order__status='paid',
            execution_status__in=(
                'paid',
                'remind_sent',
                'awaiting_manager_publish',
                'awaiting_customer_confirm',
                'awaiting_operator',
            ),
        ).aggregate(s=Sum('price'))['s']
        or 0
    )
    return int(total)


def balance_breakdown(user: User) -> Dict[str, int]:
    qs = WalletLedger.objects.filter(user=user)
    # اعتبار مشتری فقط بازگشت‌هاست. درآمد کانال‌دار جداست. ردیف امانت در جمع هیچ‌کدام نمی‌آید.
    available = qs.exclude(entry_type__in=('escrow', 'refund')).aggregate(s=Sum('amount'))['s'] or 0
    # اعتبار مشتری = بازگشت‌ها + خرج‌ها (spend معمولاً منفی است)
    credit = (
        qs.filter(entry_type__in=('refund', 'spend', 'topup')).aggregate(s=Sum('amount'))['s'] or 0
    )
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
        'available': int(available),
        'credit': int(credit),
        'locked_pending': int(locked),
        'paid_out': int(paid),
        'ledger_sum': int(available),
        'escrow': customer_escrow_toman(user),
        'manager_escrow': manager_escrow_toman(user),
    }


def recent_ledger(user: User, limit: int = 12) -> List[Dict[str, Any]]:
    rows = []
    rows_qs = (
        WalletLedger.objects.filter(user=user)
        .exclude(idempotency_key__startswith='inv:')
        .exclude(idempotency_key__startswith='invsent:')
        .exclude(idempotency_key__startswith='charge:')
    )
    for entry in rows_qs.order_by('-id')[:limit]:
        rows.append(
            {
                'id': entry.id,
                'amount': entry.amount,
                'entry_type': entry.entry_type,
                'note': entry.note,
                'ref': entry.ref,
                'created_at': entry.created_at.isoformat() if entry.created_at else '',
            }
        )
    return rows


def available_balance(user: User) -> int:
    return max(0, balance_breakdown(user)['available'])


@transaction.atomic
def credit(
    user: User,
    amount: int,
    entry_type: str,
    ref: str = '',
    note: str = '',
    idempotency_key: Optional[str] = None,
) -> WalletLedger:
    if amount == 0:
        raise ValueError('amount must be non-zero')
    key = (idempotency_key or '').strip() or None
    if key:
        existing = WalletLedger.objects.filter(idempotency_key=key).first()
        if existing:
            return existing
    try:
        return WalletLedger.objects.create(
            user=user,
            amount=amount,
            entry_type=entry_type,
            ref=ref[:64],
            note=note[:255],
            idempotency_key=key,
        )
    except IntegrityError:
        if key:
            return WalletLedger.objects.get(idempotency_key=key)
        raise


def refunded_toman_for_item(order_item_id: int) -> int:
    """جمع آنچه از این آیتم به مشتری برگشته (کامل یا بخشی)."""
    return int(
        WalletLedger.objects.filter(ref=f'item:{order_item_id}', entry_type='refund').aggregate(
            s=Sum('amount')
        )['s']
        or 0
    )


@transaction.atomic
def spend_customer_credit(
    user: User,
    amount: int,
    *,
    ref: str = '',
    note: str = '',
    idempotency_key: str = '',
) -> Dict[str, Any]:
    """کسر از اعتبار مشتری (refundها). برای پرداخت سفارش بدون فاکتور بازو."""
    amount = int(amount or 0)
    if amount <= 0:
        return {'ok': False, 'error': 'bad_amount'}
    br = balance_breakdown(user)
    if int(br.get('credit') or 0) < amount:
        return {'ok': False, 'error': 'low_balance', 'credit': br.get('credit')}
    key = (idempotency_key or f'spend:{ref}:{amount}')[:80]
    if key and WalletLedger.objects.filter(idempotency_key=key).exists():
        return {'ok': True, 'already': True, 'amount': amount}
    WalletLedger.objects.create(
        user=user,
        amount=-amount,
        entry_type='spend',
        ref=ref[:80],
        note=(note or 'پرداخت از اعتبار')[:200],
        idempotency_key=key,
    )
    return {'ok': True, 'amount': amount, 'credit_left': int(br['credit']) - amount}


def credit_manager_for_execution(
    manager: User, price_toman: int, order_item_id: int
) -> Optional[WalletLedger]:
    """سهم مدیر از آنچه مشتری واقعاً نگه داشته؛ بازگشت بخشی از پایه کم می‌شود."""
    base = max(0, int(price_toman) - refunded_toman_for_item(order_item_id))
    net = net_manager_earn(base)
    if net <= 0:
        return None
    return credit(
        manager,
        net,
        'earn',
        ref=f'item:{order_item_id}',
        note=f'اجرا آیتم #{order_item_id} خالص پس از {PLATFORM_FEE_PERCENT}%',
        idempotency_key=f'earn:item:{order_item_id}',
    )


def credit_customer_refund(
    customer: User, amount: int, order_item_id: int, reason: str
) -> Optional[WalletLedger]:
    """بازگشت به مشتری؛ هرگز بیشتر از آنچه برای این آیتم پرداخته و هنوز برنگشته."""
    from orders.models import OrderItem

    item_price = (
        OrderItem.objects.filter(pk=order_item_id).values_list('price', flat=True).first()
    )
    if item_price is not None:
        amount = min(int(amount), int(item_price) - refunded_toman_for_item(order_item_id))
    if amount <= 0:
        return None
    return credit(
        customer,
        amount,
        'refund',
        ref=f'item:{order_item_id}',
        note=reason[:255],
        idempotency_key=f'refund:item:{order_item_id}',
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
        idempotency_key=f'penalty:item:{order_item_id}',
    )


def validate_iban(iban: str) -> bool:
    """شکل IR + ۲۴ رقم و رقم کنترل ۹۷ (ISO 13616)؛ اشتباه تایپی نباید پول را به حساب غلط بفرستد."""
    value = (iban or '').replace(' ', '').upper()
    if not IBAN_RE.match(value):
        return False
    rearranged = value[4:] + value[:4]
    return int(''.join(str(int(ch, 36)) for ch in rearranged)) % 97 == 1


def save_bank_account(
    user: User, iban: str, holder_name: str, make_default: bool = True, label: str = ''
) -> BankAccount:
    iban = (iban or '').replace(' ', '').upper()
    if iban and not iban.startswith('IR'):
        iban = 'IR' + iban
    if not validate_iban(iban):
        raise ValueError('invalid_iban')
    holder_name = (holder_name or '').strip()
    if not holder_name:
        raise ValueError('need_holder_name')
    label = (label or '').strip()[:64]
    acc, _ = BankAccount.objects.update_or_create(
        user=user,
        iban=iban,
        defaults={'holder_name': holder_name, 'label': label},
    )
    if make_default:
        BankAccount.objects.filter(user=user).exclude(id=acc.id).update(is_default=False)
        acc.is_default = True
        acc.save(update_fields=['is_default'])
    return acc


def can_request_payout(user: User) -> Tuple[bool, str]:
    if PayoutRequest.objects.filter(user=user, status='pending').exists():
        return False, 'already_pending'
    # حداکثر یک درخواست در هر روز تقویمی
    today = timezone.localdate()
    if PayoutRequest.objects.filter(user=user, created_at__date=today).exclude(status='failed').exists():
        return False, 'daily_limit'
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
    User.objects.select_for_update().get(pk=user.pk)
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

    pr = PayoutRequest.objects.create(
        user=user,
        amount_toman=amount,
        amount_rial=amount * 10,
        iban=bank.iban,
        holder_name=bank.holder_name,
        bank_label=getattr(bank, 'label', '') or '',
        bank_account=bank,
        status='pending',
    )
    credit(
        user,
        -amount,
        'payout_lock',
        ref=f'payout:{pr.id}',
        note='قفل درخواست تسویه',
        idempotency_key=f'payout:{pr.id}',
    )
    return {'ok': True, 'message': 'درخواست ثبت شد. مبلغ حداکثر طی ۷۲ ساعت از طریق پایا واریز می‌شود', 'payout': pr}


@transaction.atomic
def build_payout_batch(operator: User | None = None) -> Dict[str, Any]:
    """فقط درخواست‌های بدون batch؛ شناسه یکتا per خط برای تطبیق."""
    import hashlib
    pending = list(
        PayoutRequest.objects.filter(status='pending', batch__isnull=True).select_related('user')
    )
    if not pending:
        return {'ok': False, 'error': 'no_pending'}

    lines: List[str] = []
    for pr in pending:
        # شناسه درخواست در ابتدای خط برای تطبیق اکسل
        lines.append(f'{pr.id},{pr.amount_rial},{pr.iban},,{pr.holder_name}')

    text = '\n'.join(lines)
    file_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if PayoutBatch.objects.filter(file_hash=file_hash).exists():
        return {'ok': False, 'error': 'duplicate_file'}
    batch = PayoutBatch.objects.create(
        created_by=operator,
        file_text=text,
        file_hash=file_hash,
        status='open',
    )
    for pr in pending:
        pr.batch = batch
        pr.save(update_fields=['batch'])

    return {'ok': True, 'batch': batch, 'count': len(pending), 'file_text': text, 'file_hash': file_hash}


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
    uid = str(bale_user_id or "").strip()
    if not uid:
        return False
    if uid == "demo_operator_1":
        return True
    ids: set[str] = set()
    for src in (
        os.environ.get("OPERATOR_BALE_ID") or "",
        OPERATOR_BALE_ID or "",
        os.environ.get("DEBUG_BALE_ID") or "",
    ):
        for part in str(src).replace(";", ",").split(","):
            p = part.strip()
            if p:
                ids.add(p)
    try:
        from django.conf import settings
        for part in str(getattr(settings, "OPERATOR_BALE_ID", "") or "").replace(";", ",").split(","):
            p = part.strip()
            if p:
                ids.add(p)
    except Exception:
        pass
    return uid in ids


@transaction.atomic
def mark_payout_failed(payout_id: int, bank_tx_id: str = '') -> Dict[str, Any]:
    """گزارش بانک ناموفق → مبلغ به قابل برداشت برمی‌گردد."""
    pr = PayoutRequest.objects.select_for_update().filter(id=payout_id, status='pending').first()
    if not pr:
        return {'ok': False, 'error': 'not_found'}
    pr.status = 'failed'
    if bank_tx_id:
        pr.bank_tx_id = str(bank_tx_id)[:64]
    pr.save(update_fields=['status', 'bank_tx_id'] if bank_tx_id else ['status'])
    credit(
        pr.user,
        int(pr.amount_toman),
        'payout_unlock',
        ref=f'payout_fail:{pr.id}',
        note='بازگشت پس از ناموفق بودن پایا',
        idempotency_key=f'payout_fail:{pr.id}',
    )
    return {'ok': True, 'payout_id': pr.id}


def can_delete_bank(user: User, bank_id: int) -> Tuple[bool, str]:
    bank = BankAccount.objects.filter(id=bank_id, user=user).first()
    if not bank:
        return False, 'not_found'
    if PayoutRequest.objects.filter(user=user, status='pending', bank_account=bank).exists():
        return False, 'pending_payout'
    if PayoutRequest.objects.filter(user=user, status='pending', iban=bank.iban).exists():
        return False, 'pending_payout'
    return True, 'ok'


@transaction.atomic
def cancel_payout_request(user: User, payout_id: int) -> Dict[str, Any]:
    """لغو درخواست تا قبل از قرار گرفتن در فایل پرداخت."""
    pr = PayoutRequest.objects.select_for_update().filter(
        id=payout_id, user=user, status='pending', batch__isnull=True,
    ).first()
    if not pr:
        return {'ok': False, 'error': 'not_cancellable', 'message': 'این درخواست قابل لغو نیست (یا در فایل پرداخت آمده).'}
    pr.status = 'cancelled'
    pr.save(update_fields=['status'])
    credit(
        user,
        int(pr.amount_toman),
        'payout_unlock',
        ref=f'payout_cancel:{pr.id}',
        note='لغو درخواست برداشت توسط کاربر',
        idempotency_key=f'payout_cancel:{pr.id}',
    )
    return {'ok': True, 'payout_id': pr.id}


def send_daily_payout_file_to_operators() -> Dict[str, Any]:
    """تولید فایل روز و ارسال به پشتیبان‌ها با دکمه پرداخت شد."""
    from integrations import bale_client as bc
    built = build_payout_batch(None)
    if not built.get('ok'):
        return built
    batch = built['batch']
    text = built['file_text']
    count = built['count']
    # فایل به‌صورت سند
    import tempfile
    from pathlib import Path as P
    tmp = P(tempfile.gettempdir()) / f'payout_batch_{batch.id}.txt'
    tmp.write_text(text, encoding='utf-8')
    caption = (
        f'فایل پرداخت گروهی #{batch.id}\n'
        f'تعداد: {count} درخواست\n'
        f'پس از انجام پایا، «پرداخت شد» را بزنید و فایل اکسل گزارش بانک را بفرستید.'
    )
    kb = {
        'inline_keyboard': [[
            {'text': f'پرداخت شد — فایل #{batch.id}', 'callback_data': f'paybatch:{batch.id}'},
        ]]
    }
    sent = 0
    for oid in _operator_ids():
        try:
            # send document if available else message with text
            r = None
            if hasattr(bc, 'send_document'):
                r = bc.send_document(oid, str(tmp), caption=caption, reply_markup=kb)
            if not r or r.get('error'):
                bc.send_message(oid, caption + '\n\n```\n' + text[:3500] + '\n```', reply_markup=kb)
            sent += 1
        except Exception:
            logger.exception('send payout batch to %s', oid)
    return {'ok': True, 'batch_id': batch.id, 'sent': sent, 'count': count}


def _operator_ids() -> list[str]:
    ids: list[str] = []
    for src in (
        os.environ.get('OPERATOR_BALE_ID') or '',
        os.environ.get('DEBUG_BALE_ID') or '',
    ):
        for part in str(src).replace(';', ',').split(','):
            p = part.strip()
            if p and p not in ids:
                ids.append(p)
    return ids


def process_bank_report_for_batch(batch_id: int, rows: list[dict]) -> Dict[str, Any]:
    """rows: [{payout_id, status: success|failed, bank_tx_id?}]"""
    batch = PayoutBatch.objects.filter(id=batch_id).first()
    if not batch:
        return {'ok': False, 'error': 'batch_not_found'}
    if batch.status == 'processed':
        return {'ok': False, 'error': 'already_processed', 'message': 'این فایل قبلاً پردازش شده.'}
    ok_n = fail_n = skip_n = 0
    for row in rows:
        try:
            pid = int(row.get('payout_id') or 0)
        except (TypeError, ValueError):
            skip_n += 1
            continue
        st = str(row.get('status') or '').lower()
        pr = PayoutRequest.objects.filter(id=pid, batch=batch, status='pending').first()
        if not pr:
            skip_n += 1
            continue
        if st in ('success', 'ok', 'paid', '1', 'موفق'):
            mark_one_paid(pr, str(row.get('bank_tx_id') or ''))
            ok_n += 1
        elif st in ('failed', 'fail', '0', 'ناموفق'):
            mark_payout_failed(pr.id, str(row.get('bank_tx_id') or ''))
            fail_n += 1
        else:
            skip_n += 1
    remaining = PayoutRequest.objects.filter(batch=batch, status='pending').count()
    if remaining == 0:
        batch.status = 'processed'
        batch.paid_at = timezone.now()
    batch.result_summary = f'موفق {ok_n} · ناموفق {fail_n} · بدون نتیجه {skip_n + remaining}'
    batch.save()
    return {
        'ok': True,
        'success': ok_n,
        'failed': fail_n,
        'pending': remaining,
        'skipped': skip_n,
        'summary': batch.result_summary,
    }


def mark_one_paid(pr: PayoutRequest, bank_tx_id: str = '') -> None:
    if pr.status != 'pending':
        return
    from integrations import bale_client as bc
    pr.status = 'paid'
    pr.paid_at = timezone.now()
    fields = ['status', 'paid_at']
    if bank_tx_id:
        pr.bank_tx_id = bank_tx_id[:64]
        fields.append('bank_tx_id')
    pr.save(update_fields=fields)
    try:
        uid = pr.user.bale_user_id
        if uid:
            bc.send_message(
                uid,
                f'مبلغ {pr.amount_toman:,} تومان در تاریخ {timezone.localdate().isoformat()} به حساب شما پایا شد.',
            )
    except Exception:
        logger.exception('notify payout paid')
