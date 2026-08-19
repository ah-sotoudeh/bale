"""درخواست انتشار بنر در کانال مرجع لینک‌بانک (@linkbank)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from integrations import bale_client as bc
from orders.models import BannerPublishRequest, CustomerBanner
from users.models import User

logger = logging.getLogger(__name__)


def linkbank_channel() -> str:
    raw = (os.environ.get('LINKBANK_CHANNEL') or '@linkbank').strip()
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
    """اولین بنر رایگان؛ بعدی‌ها تعرفه."""
    if count_linkbank_banners(user) == 0:
        # درخواست‌های تأییدشده در صف هم حساب شوند
        approved_pending = BannerPublishRequest.objects.filter(
            customer=user, status='approved'
        ).count()
        if approved_pending == 0 and count_linkbank_banners(user) == 0:
            return 0
    return banner_fee_toman()


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
    kb = bc.inline_keyboard([
        [
            {'text': '✅ تأیید و ارسال به لینک‌بانک', 'callback_data': f'bappr:{req.id}'},
            {'text': '❌ رد', 'callback_data': f'brej:{req.id}'},
        ]
    ])
    bc.send_message(
        op,
        f'🆕 درخواست بنر لینک‌بانک\n'
        f'#{req.id} | مشتری `{req.customer.bale_user_id}`\n'
        f'هزینه ثبت: {fee_txt}\n'
        f'پس از تأیید در {linkbank_channel()} منتشر می‌شود و حذف نمی‌شود.',
        reply_markup=kb,
    )


@transaction.atomic
def operator_decide(req_id: int, operator_bale_id: str, approve: bool) -> Dict[str, Any]:
    try:
        req = BannerPublishRequest.objects.select_related('customer').get(id=req_id)
    except BannerPublishRequest.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}
    if req.status != 'pending':
        return {'ok': False, 'error': 'already_handled'}

    op = operator_chat_id()
    if op and str(operator_bale_id) != str(op):
        return {'ok': False, 'error': 'not_operator'}

    cust = req.customer.bale_user_id
    if not approve:
        req.status = 'rejected'
        req.reviewed_at = timezone.now()
        req.save(update_fields=['status', 'reviewed_at'])
        if cust:
            bc.send_message(cust, f'❌ درخواست بنر #{req.id} رد شد.')
        return {'ok': True, 'status': 'rejected'}

    # انتشار در لینک‌بانک با فوروارد (نقل‌قول از چت مشتری/بازو)
    lb = linkbank_channel()
    fwd = bc.forward_message(lb, req.storage_chat_id, int(req.storage_message_id))
    if not fwd.get('ok'):
        # fallback copy
        fwd = bc.copy_message(lb, req.storage_chat_id, int(req.storage_message_id))
    if not fwd.get('ok'):
        logger.error('publish to linkbank failed: %s', fwd)
        return {'ok': False, 'error': 'publish_failed', 'detail': fwd}

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
        fee_note = '' if req.fee_toman == 0 else f'\n(تعرفه ثبت: {req.fee_toman:,} ت — پرداخت جداگانه در نسخه بعدی کیف پول)'
        bc.send_message(
            cust,
            f'✅ بنر شما در {lb} ثبت شد و دائمی است.{fee_note}\n'
            f'بنر «{banner.display_title()}» آماده سفارش تبلیغ است.\n'
            f'/banners',
        )
    return {'ok': True, 'status': 'approved', 'banner_id': banner.id}


def edit_banner_caption(
    banner_id: int,
    customer_bale_id: str,
    new_caption: str,
) -> Dict[str, Any]:
    """فقط متن؛ رسانه قابل ویرایش نیست. رایگان."""
    from bot_flow.banned_words import is_allowed

    try:
        banner = CustomerBanner.objects.select_related('customer').get(id=banner_id)
    except CustomerBanner.DoesNotExist:
        return {'ok': False, 'error': 'not_found'}
    if str(banner.customer.bale_user_id) != str(customer_bale_id):
        return {'ok': False, 'error': 'forbidden'}

    ok, hits = is_allowed(new_caption or '')
    if not ok:
        return {'ok': False, 'error': 'banned', 'hits': hits}

    banner.caption = new_caption or ''
    banner.save(update_fields=['caption'])

    # تلاش برای edit روی پیام ذخیره‌شده نزد بازو
    try:
        bc.edit_message_caption(
            banner.storage_chat_id,
            int(banner.storage_message_id),
            new_caption or ' ',
        )
    except Exception:
        logger.exception('edit storage caption failed')

    # روی لینک‌بانک اگر message_id عددی Bot API باشد (ممکن است داخلی بزرگ باشد و fail شود)
    if banner.linkbank_message_id and banner.linkbank_message_id.isdigit():
        try:
            bc.edit_message_caption(
                banner.linkbank_chat_id or linkbank_channel(),
                int(banner.linkbank_message_id),
                new_caption or ' ',
            )
        except Exception:
            logger.exception('edit linkbank caption failed')

    return {'ok': True, 'banner_id': banner.id}
