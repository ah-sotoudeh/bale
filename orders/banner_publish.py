"""درخواست انتشار بنر در کانال مرجع (فعلاً @linktest برای تست؛ پروداکشن @linkbank)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from django.db import transaction
from django.utils import timezone

from integrations import bale_client as bc
from orders.models import BannerPublishRequest, CustomerBanner
from users.models import User

logger = logging.getLogger(__name__)


def linkbank_channel() -> str:
    """کانال مرجع بنر. تست: @linktest — پروداکشن: LINKBANK_CHANNEL=@linkbank"""
    raw = (
        os.environ.get('LINKBANK_CHANNEL')
        or os.environ.get('BANNER_REFERENCE_CHANNEL')
        or '@linktest'  # موقت تا بازو روی لینک‌بانک ادمین شود
    ).strip()
    if raw and not raw.startswith('@') and not raw.lstrip('-').isdigit():
        raw = '@' + raw
    return raw


def banner_fee_toman() -> int:
    return int(os.environ.get('LINKBANK_BANNER_FEE_TOMAN', '140000'))


def operator_chat_id() -> str:
    return (
        os.environ.get('OPERATOR_BALE_ID')
        or os.environ.get('LINKPAKHSH_BALE_ID')
        or ''
    ).strip()


def count_linkbank_banners(user: User) -> int:
    return CustomerBanner.objects.filter(
        customer=user, from_linkbank=True, is_active=True
    ).count()


def fee_for_user(user: User) -> int:
    if count_linkbank_banners(user) == 0:
        return 0
    return banner_fee_toman()


def user_facing_error(code: str) -> str:
    """پیام امن برای کاربر/اپراتور — بدون URL و توکن."""
    mapping = {
        'not_found': 'درخواست پیدا نشد.',
        'already_handled': 'این درخواست قبلاً رسیدگی شده.',
        'not_operator': 'فقط اپراتور می‌تواند این کار را انجام دهد.',
        'publish_failed': (
            f'ارسال به کانال مرجع ({linkbank_channel()}) ناموفق بود. '
            'بازو باید در آن کانال ادمین باشد و حق ارسال داشته باشد.'
        ),
        'banned': 'متن شامل عبارت غیرمجاز است.',
        'forbidden': 'اجازه این کار را ندارید.',
    }
    return mapping.get(code, 'خطایی رخ داد. جزئیات در لاگ سرور است.')


def create_publish_request(
    user: User,
    *,
    storage_chat_id: str,
    storage_message_id: str,
    caption: str = '',
    media_kind: str = '',
) -> Dict[str, Any]:
    fee = fee_for_user(user)
    req = BannerPublishRequest.objects.create(
        customer=user,
        storage_chat_id=str(storage_chat_id),
        storage_message_id=str(storage_message_id),
        caption=caption or '',
        media_kind=media_kind or '',
        fee_toman=fee,
        status='pending',
    )
    _notify_operator(req)
    return {'ok': True, 'request': req, 'fee': fee}


def _notify_operator(req: BannerPublishRequest) -> None:
    op = operator_chat_id()
    if not op:
        logger.warning('OPERATOR_BALE_ID not set; cannot notify for banner request #%s', req.id)
        return
    try:
        bc.forward_message(op, req.storage_chat_id, int(req.storage_message_id))
    except Exception:
        logger.exception('forward to operator failed')
    fee_txt = 'رایگان (بنر اول)' if req.fee_toman == 0 else f'{req.fee_toman:,} تومان'
    ch = linkbank_channel()
    kb = bc.inline_keyboard([
        [
            {'text': '✅ تأیید و ارسال', 'callback_data': f'bappr:{req.id}'},
            {'text': '❌ رد', 'callback_data': f'brej:{req.id}'},
        ]
    ])
    bc.send_message(
        op,
        f'🆕 درخواست بنر\n'
        f'#{req.id} | مشتری {req.customer.bale_user_id}\n'
        f'هزینه ثبت: {fee_txt}\n'
        f'پس از تأیید در {ch} منتشر می‌شود (دائمی).',
        reply_markup=kb,
    )


@transaction.atomic
def operator_decide(req_id: int, operator_bale_id: str, approve: bool) -> Dict[str, Any]:
    try:
        req = BannerPublishRequest.objects.select_related('customer').get(id=req_id)
    except BannerPublishRequest.DoesNotExist:
        return {'ok': False, 'error': 'not_found', 'message': user_facing_error('not_found')}
    if req.status != 'pending':
        return {
            'ok': False,
            'error': 'already_handled',
            'message': user_facing_error('already_handled'),
        }

    op = operator_chat_id()
    if op and str(operator_bale_id) != str(op):
        return {
            'ok': False,
            'error': 'not_operator',
            'message': user_facing_error('not_operator'),
        }

    cust = req.customer.bale_user_id
    if not approve:
        req.status = 'rejected'
        req.reviewed_at = timezone.now()
        req.save(update_fields=['status', 'reviewed_at'])
        if cust:
            bc.send_message(cust, f'❌ درخواست بنر #{req.id} رد شد.')
        return {'ok': True, 'status': 'rejected', 'message': f'درخواست #{req.id} رد شد.'}

    lb = linkbank_channel()
    fwd = bc.forward_message(lb, req.storage_chat_id, int(req.storage_message_id))
    if not fwd.get('ok'):
        fwd = bc.copy_message(lb, req.storage_chat_id, int(req.storage_message_id))
    if not fwd.get('ok'):
        # فقط در لاگ سرور — هرگز detail خام به کاربر نرود
        logger.error('publish to %s failed (sanitized log): ok=False error_code-ish', lb)
        logger.debug('publish detail keys=%s', list(fwd.keys()) if isinstance(fwd, dict) else type(fwd))
        return {
            'ok': False,
            'error': 'publish_failed',
            'message': user_facing_error('publish_failed'),
        }

    result = fwd.get('result') or {}
    lb_mid = str(result.get('message_id') or '')

    banner = CustomerBanner.objects.create(
        customer=req.customer,
        caption=req.caption,
        storage_chat_id=req.storage_chat_id,
        storage_message_id=req.storage_message_id,
        from_linkbank=True,
        linkbank_chat_id=lb,
        linkbank_message_id=lb_mid,
        media_kind=req.media_kind,
        is_active=True,
    )
    req.status = 'approved'
    req.reviewed_at = timezone.now()
    req.customer_banner = banner
    req.linkbank_message_id = lb_mid
    req.save()

    if cust:
        fee_note = ''
        if req.fee_toman:
            fee_note = f'\n(تعرفه ثبت: {req.fee_toman:,} ت — پرداخت کیف پول در نسخه بعد)'
        bc.send_message(
            cust,
            f'✅ بنر شما در {lb} ثبت شد و دائمی است.{fee_note}\n'
            f'«{banner.display_title()}» آماده سفارش است.\n'
            f'/banners',
        )
    return {
        'ok': True,
        'status': 'approved',
        'banner_id': banner.id,
        'message': f'تأیید شد و در {lb} منتشر شد (بنر #{banner.id}).',
    }


def edit_banner_caption(
    banner_id: int,
    customer_bale_id: str,
    new_caption: str,
) -> Dict[str, Any]:
    from bot_flow.banned_words import is_allowed

    try:
        banner = CustomerBanner.objects.select_related('customer').get(id=banner_id)
    except CustomerBanner.DoesNotExist:
        return {'ok': False, 'error': 'not_found', 'message': user_facing_error('not_found')}
    if str(banner.customer.bale_user_id) != str(customer_bale_id):
        return {'ok': False, 'error': 'forbidden', 'message': user_facing_error('forbidden')}

    ok, hits = is_allowed(new_caption or '')
    if not ok:
        return {'ok': False, 'error': 'banned', 'message': user_facing_error('banned')}

    banner.caption = new_caption or ''
    banner.save(update_fields=['caption'])

    try:
        bc.edit_message_caption(
            banner.storage_chat_id,
            int(banner.storage_message_id),
            new_caption or ' ',
        )
    except Exception:
        logger.exception('edit storage caption failed')

    if banner.linkbank_message_id and str(banner.linkbank_message_id).isdigit():
        try:
            bc.edit_message_caption(
                banner.linkbank_chat_id or linkbank_channel(),
                int(banner.linkbank_message_id),
                new_caption or ' ',
            )
        except Exception:
            logger.exception('edit channel caption failed')

    return {'ok': True, 'banner_id': banner.id, 'message': 'متن به‌روز شد.'}
