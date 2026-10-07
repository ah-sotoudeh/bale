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
    """پیام امن برای کاربر — بدون URL و توکن."""
    mapping = {
        'not_found': 'این درخواست را پیدا نکردم. فهرست را یک بار تازه کنید.',
        'already_handled': 'به این درخواست قبلاً جواب داده‌اید.',
        'not_operator': 'فقط پشتیبانی می‌تواند این کار را انجام دهد.',
        'publish_failed': 'بنر در کانال بنرها منتشر نشد. به پشتیبانی بگویید تا ارسال را بررسی کند.',
        'banned': 'این متن مجاز نیست. عبارت را عوض کنید و دوباره بفرستید.',
        'forbidden': 'این کار برای شما نیست.',
    }
    return mapping.get(code, 'یک اشکال پیش آمد. یک بار دیگر تلاش کنید.')


def banner_stage(banner: CustomerBanner) -> str:
    """ready بعد از تأیید، rejected اگر آخرین درخواست رد شده، وگرنه در انتظار بررسی."""
    if banner.from_linkbank:
        return 'ready'
    req = banner.publish_requests.order_by('-id').first()
    if req and req.status == 'rejected':
        return 'rejected'
    return 'pending'


def create_publish_request(
    user: User,
    *,
    storage_chat_id: str,
    storage_message_id: str,
    caption: str = '',
    media_kind: str = '',
    banner: CustomerBanner | None = None,
) -> Dict[str, Any]:
    fee = fee_for_user(user)
    if banner is None:
        banner = CustomerBanner.objects.filter(
            customer=user,
            is_active=True,
            storage_chat_id=str(storage_chat_id),
            storage_message_id=str(storage_message_id),
        ).order_by('-id').first()
    req = BannerPublishRequest.objects.create(
        customer=user,
        storage_chat_id=str(storage_chat_id),
        storage_message_id=str(storage_message_id),
        caption=caption or '',
        media_kind=media_kind or '',
        fee_toman=fee,
        status='pending',
        customer_banner=banner,
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

    from wallet.services import is_operator

    if not is_operator(operator_bale_id):
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
            title = req.customer_banner.display_title() if req.customer_banner_id else 'بنر'
            bc.send_message(
                cust,
                f'بنر «{title}» تأیید نشد. سفارش پرداخت‌نشده‌ای که با این بنر مانده بود لغو شد.',
            )
        if req.customer_banner_id:
            try:
                from orders.cart import cancel_orders_waiting_on_banner

                cancel_orders_waiting_on_banner(req.customer_banner)
            except Exception:
                logger.exception('cancel orders after banner reject')
        return {'ok': True, 'status': 'rejected', 'message': 'درخواست رد شد. مشتری خبردار می‌شود.'}

    lb = linkbank_channel()
    lb_mid = ''
    linkyar_rid = ''
    linkyar_date = ''
    linkyar_seq = ''

    # اولویت: آپلود توسط لینک‌یار + ذخیره rid/date برای فوروارد بعدی
    try:
        from orders.banner_media import materialize_banner_file
        from integrations import linkyar_client as ly
        from orders.models import CustomerBanner as CB

        bn0 = req.customer_banner
        path = None
        kind = (req.media_kind or 'photo').lower() or 'photo'
        if bn0 is not None:
            try:
                path = materialize_banner_file(bn0)
            except Exception:
                logger.exception('materialize banner')
        if path is None:
            # از storage بات دانلود
            try:
                from orders.banner_media import _pull_stored_message
                if bn0 is not None:
                    path = _pull_stored_message(bn0)
            except Exception:
                pass

        if path is not None:
            up = ly.publish_to_linkbank_and_capture(
                lb, str(path), caption=req.caption or (bn0.caption if bn0 else '') or '', kind=kind,
            )
            if up.get('ok'):
                linkyar_rid = str(up.get('linkyar_rid') or '')
                linkyar_date = str(up.get('linkyar_date') or '')
                linkyar_seq = str(up.get('linkyar_seq') or '')
                lb_mid = str(up.get('message_id') or up.get('linkyar_rid') or '')
                logger.info(
                    'linkyar uploaded to linkbank rid=%s date=%s',
                    linkyar_rid, linkyar_date,
                )
            else:
                logger.warning('linkyar upload failed: %s — fallback bot', up.get('error'))
    except Exception:
        logger.exception('linkyar publish_to_linkbank')

    # fallback: فوروارد بات (برای linkbank_message_id بات)
    if not linkyar_rid:
        fwd = bc.forward_message(lb, req.storage_chat_id, int(req.storage_message_id))
        if not fwd.get('ok'):
            fwd = bc.copy_message(lb, req.storage_chat_id, int(req.storage_message_id))
        if not fwd.get('ok'):
            logger.error('publish to %s failed', lb)
            return {
                'ok': False,
                'error': 'publish_failed',
                'message': user_facing_error('publish_failed'),
            }
        result = fwd.get('result') or {}
        lb_mid = str(result.get('message_id') or '')

    banner = req.customer_banner
    if banner is None:
        banner = CustomerBanner.objects.filter(
            customer=req.customer,
            is_active=True,
            storage_chat_id=req.storage_chat_id,
            storage_message_id=req.storage_message_id,
        ).order_by('-id').first()
    if banner is None:
        banner = CustomerBanner.objects.create(
            customer=req.customer,
            caption=req.caption,
            storage_chat_id=req.storage_chat_id,
            storage_message_id=req.storage_message_id,
            from_linkbank=True,
            linkbank_chat_id=lb,
            linkbank_message_id=lb_mid,
            linkyar_rid=linkyar_rid,
            linkyar_date=linkyar_date,
            linkyar_seq=linkyar_seq,
            media_kind=req.media_kind,
            is_active=True,
        )
    else:
        banner.from_linkbank = True
        banner.linkbank_chat_id = lb
        banner.linkbank_message_id = lb_mid
        if linkyar_rid:
            banner.linkyar_rid = linkyar_rid
            banner.linkyar_date = linkyar_date
            banner.linkyar_seq = linkyar_seq
        if req.caption and not banner.caption:
            banner.caption = req.caption
        banner.is_active = True
        banner.save()
    req.status = 'approved'
    req.reviewed_at = timezone.now()
    req.customer_banner = banner
    req.linkbank_message_id = lb_mid
    req.save()

    if cust:
        kb = bc.inline_keyboard([
            [{'text': 'انتخاب کانال', 'callback_data': 'cu:catalog'}],
        ])
        bc.send_message(
            cust,
            f'بنر «{banner.display_title()}» تأیید شد و آماده است. حالا روز کانال را بردارید.',
            reply_markup=kb,
        )
    try:
        from orders.cart import release_orders_waiting_on_banner

        release_orders_waiting_on_banner(banner)
    except Exception:
        logger.exception('release orders waiting on banner')
    return {
        'ok': True,
        'status': 'approved',
        'banner_id': banner.id,
        'message': 'تأیید شد و بنر در کانال بنرها منتشر شد.',
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
