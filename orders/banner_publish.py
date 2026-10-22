"""ثبت و انتشار بنر در کانال مرجع (@linkbank2)."""
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
    """کانال مرجع بنر. پیش‌فرض: @linkbank2 (قابل‌override با LINKBANK_CHANNEL)."""
    raw = (
        os.environ.get('LINKBANK_CHANNEL')
        or os.environ.get('BANNER_REFERENCE_CHANNEL')
        or '@linkbank2'
    ).strip()
    if raw and not raw.startswith('@') and not raw.lstrip('-').isdigit():
        raw = '@' + raw
    return raw


def banner_fee_toman() -> int:
    # ساخت بنر رایگان است
    return 0


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
    return 0


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
    """ثبت بنر دیگر نیاز به تأیید ندارد — ready به‌محض انتشار در کانال مرجع."""
    if banner.from_linkbank and banner.linkbank_message_id:
        return 'ready'
    if banner.from_linkbank:
        return 'ready'
    req = banner.publish_requests.order_by('-id').first()
    if req and req.status == 'rejected':
        return 'rejected'
    # سازگاری با بنرهای قدیمی بدون linkbank
    if banner.is_active:
        return 'pending'
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
    ch = linkbank_channel()
    kb = bc.inline_keyboard([
        [
            {'text': '✅ تأیید و ارسال', 'callback_data': f'bappr:{req.id}'},
            {'text': '❌ رد', 'callback_data': f'brej:{req.id}'},
        ]
    ])
    title = ''
    if req.customer_banner_id:
        try:
            title = req.customer_banner.display_title()
        except Exception:
            title = ''
    caption = (req.caption or '').strip()
    preview = caption[:400] + ('…' if len(caption) > 400 else '')
    text = (
        f'🆕 درخواست بنر\n'
        f'#{req.id} | مشتری {req.customer.bale_user_id}\n'
        f'عنوان: {title or "—"}\n'
        f'رایگان — پس از تأیید در {ch} منتشر می‌شود.\n'
        f'{preview}'
    )
    sent_media = False
    if req.customer_banner_id:
        try:
            from orders.banner_media import stored_banner_file
            path = stored_banner_file(int(req.customer_banner_id))
            if path is not None and path.is_file():
                kind = (req.media_kind or '').lower()
                if kind in ('video', 'animation'):
                    r = bc.send_video(op, str(path), caption=text[:900])
                elif kind == 'document':
                    r = bc.send_document(op, str(path), caption=text[:900])
                else:
                    r = bc.send_photo(op, str(path), caption=text[:900])
                sent_media = bool(r.get('ok'))
        except Exception:
            logger.exception('send banner media to operator failed')
    if not sent_media:
        try:
            sid = str(req.storage_chat_id or '')
            mid = str(req.storage_message_id or '')
            if mid.isdigit() and (sid.lstrip('-').isdigit() or sid.startswith('@')):
                bc.forward_message(op, sid, int(mid))
        except Exception:
            logger.exception('forward to operator failed')
        bc.send_message(op, text, reply_markup=kb)
    else:
        bc.send_message(op, f'دکمه‌های بررسی بنر #{req.id}:', reply_markup=kb)


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

        bn0 = req.customer_banner
        path = None
        kind = (req.media_kind or 'photo').lower() or 'photo'
        if bn0 is not None:
            try:
                path = materialize_banner_file(bn0)
            except Exception:
                logger.exception('materialize banner')
        if path is None:
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

    # fallback: فوروارد بات یا ارسال فایل محلی (بنر مینی‌اپ)
    if not linkyar_rid:
        fwd = {'ok': False}
        sid = str(req.storage_chat_id or '')
        mid = str(req.storage_message_id or '')
        if mid.isdigit() and (sid.lstrip('-').isdigit() or sid.startswith('@')):
            fwd = bc.forward_message(lb, sid, int(mid))
            if not fwd.get('ok'):
                fwd = bc.copy_message(lb, sid, int(mid))
        if not fwd.get('ok'):
            try:
                from orders.banner_media import stored_banner_file, materialize_banner_file
                path = None
                if req.customer_banner_id:
                    path = stored_banner_file(int(req.customer_banner_id))
                    if path is None:
                        path = materialize_banner_file(req.customer_banner)
                if path is not None and path.is_file():
                    kind = (req.media_kind or 'photo').lower()
                    cap = req.caption or ''
                    if kind in ('video', 'animation'):
                        fwd = bc.send_video(lb, str(path), caption=cap[:900])
                    elif kind == 'document':
                        fwd = bc.send_document(lb, str(path), caption=cap[:900])
                    else:
                        fwd = bc.send_photo(lb, str(path), caption=cap[:900])
            except Exception:
                logger.exception('publish local banner file to linkbank')
                fwd = {'ok': False}
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




def register_banner_immediate(
    user: User,
    *,
    storage_chat_id: str,
    storage_message_id: str,
    caption: str = '',
    media_kind: str = '',
    title: str = '',
    bot_file_id: str = '',
    message: dict | None = None,
) -> Dict[str, Any]:
    """ثبت فوری بنر مشتری بدون تأیید اپراتور.

    1) بازو پیام را با copyMessage به کانال مرجع می‌فرستد
    2) CustomerBanner با from_linkbank=True ساخته/به‌روز می‌شود
    3) لینک‌یار از تاریخچهٔ مرجع file_id/access_hash می‌گیرد و ذخیره می‌کند
    """
    from integrations import linkyar_client as ly
    from orders.banner_media import file_from_message, save_banner_from_message

    lb = linkbank_channel()
    caption = (caption or '')[:2000]
    media_kind = (media_kind or 'photo').lower() or 'photo'
    title = (title or (caption.strip().split('\n')[0] if caption.strip() else '') or '')[:120]

    if message and not bot_file_id:
        try:
            fid, kind = file_from_message(message)
            if fid:
                bot_file_id = str(fid)
            if kind and not media_kind:
                media_kind = kind
        except Exception:
            logger.exception('extract bot_file_id')

    # کپی به کانال مرجع با بازو
    lb_mid = ''
    copy_err = ''
    try:
        # ترجیح: copyMessage تا بدون هدر فوروارد باشد
        cr = bc.copy_message(lb, str(storage_chat_id), int(storage_message_id))
        if isinstance(cr, dict) and cr.get('ok'):
            res = cr.get('result') or {}
            lb_mid = str(res.get('message_id') or '')
        else:
            copy_err = str((cr or {}).get('error') or cr)[:200]
            # fallback forward
            fr = bc.forward_message(lb, str(storage_chat_id), int(storage_message_id))
            if isinstance(fr, dict) and fr.get('ok'):
                res = fr.get('result') or {}
                lb_mid = str(res.get('message_id') or '')
                copy_err = ''
            else:
                copy_err = copy_err or str((fr or {}).get('error') or fr)[:200]
    except Exception as e:
        copy_err = f'{type(e).__name__}:{e}'
        logger.exception('copy banner to linkbank')

    if not lb_mid:
        return {
            'ok': False,
            'error': 'linkbank_copy_failed',
            'message': 'نتوانستم بنر را در کانال مرجع ثبت کنم. دوباره بفرستید.',
            'detail': copy_err,
        }

    banner = CustomerBanner.objects.create(
        customer=user,
        title=title,
        caption=caption,
        storage_chat_id=str(storage_chat_id),
        storage_message_id=str(storage_message_id),
        from_linkbank=True,
        linkbank_chat_id=lb,
        linkbank_message_id=str(lb_mid),
        media_kind=media_kind,
        bot_file_id=str(bot_file_id or ''),
        is_active=True,
    )

    # فایل محلی اختیاری (پشتیبان)
    if message:
        try:
            save_banner_from_message(banner.id, message)
        except Exception:
            logger.exception('save_banner_from_message')

    # متای لینک‌یار از تاریخچهٔ کانال مرجع
    ly_meta = _capture_linkyar_file_meta(lb, caption=caption, prefer_mid=None)
    if ly_meta:
        banner.ly_file_id = str(ly_meta.get('file_id') or '')
        banner.ly_file_access_hash = str(ly_meta.get('file_access_hash') or '')
        banner.ly_file_size = int(ly_meta.get('file_size') or 0)
        banner.ly_file_name = str(ly_meta.get('file_name') or '')[:255]
        banner.ly_mime_type = str(ly_meta.get('mime') or ly_meta.get('mime_type') or '')[:80]
        if ly_meta.get('message_id'):
            banner.linkyar_rid = str(ly_meta.get('message_id'))
        if ly_meta.get('date'):
            banner.linkyar_date = str(ly_meta.get('date'))
        banner.save(update_fields=[
            'ly_file_id', 'ly_file_access_hash', 'ly_file_size', 'ly_file_name',
            'ly_mime_type', 'linkyar_rid', 'linkyar_date',
        ])

    return {
        'ok': True,
        'banner': banner,
        'banner_id': banner.id,
        'linkbank_message_id': lb_mid,
        'ly_file_id': banner.ly_file_id,
        'bot_file_id': banner.bot_file_id,
        'message': 'بنر ثبت شد و در فهرست بنرهای شما قرار گرفت.',
    }


def _capture_linkyar_file_meta(
    channel_ref: str,
    *,
    caption: str = '',
    prefer_mid: Any = None,
) -> Dict[str, Any] | None:
    """از تاریخچهٔ لینک‌یار آخرین/مچ‌شده‌ترین document را بردار."""
    import time as _time
    from integrations import linkyar_client as ly

    # کمی صبر تا پیام در تاریخچه دیده شود
    for delay in (0.8, 1.5, 2.5):
        try:
            _time.sleep(delay)
            hist = ly.load_channel_history(channel_ref, limit=25)
        except Exception as e:
            logger.warning('ly history for meta: %s', e)
            continue
        if not isinstance(hist, dict) or not hist.get('ok'):
            continue
        msgs = list(hist.get('messages') or [])
        # اولویت: message_id مشخص، بعد caption match، بعد آخرین photo
        if prefer_mid:
            for p in msgs:
                if str(p.get('message_id')) == str(prefer_mid) and p.get('file_id'):
                    return p
        cap_key = (caption or '').strip()[:40]
        if cap_key:
            for p in msgs:
                if p.get('file_id') and cap_key in str(p.get('preview') or ''):
                    return p
        for p in msgs:
            if p.get('kind') in ('photo', 'document', 'video') and p.get('file_id') and p.get('file_access_hash'):
                return p
    return None


def edit_banner_caption(
    banner_id: int,
    customer_bale_id: str,
    new_caption: str,
) -> Dict[str, Any]:
    """ویرایش فقط متن بنر. ترجیح: editMessageCaption روی کانال مرجع؛ وگرنه کپی جدید."""
    from bot_flow.banned_words import is_allowed

    try:
        banner = CustomerBanner.objects.select_related('customer').get(id=banner_id)
    except CustomerBanner.DoesNotExist:
        return {'ok': False, 'error': 'not_found', 'message': 'بنر پیدا نشد.'}

    if str(banner.customer.bale_user_id) != str(customer_bale_id):
        return {'ok': False, 'error': 'forbidden', 'message': 'اجازه ندارید.'}

    new_caption = (new_caption or '')[:2000]
    ok, hits = is_allowed(new_caption)
    if not ok:
        return {
            'ok': False,
            'error': 'banned_words',
            'message': 'این عبارت مجاز نیست: ' + ', '.join(hits),
        }

    lb = banner.linkbank_chat_id or linkbank_channel()
    lb_mid = str(banner.linkbank_message_id or '').strip()
    edited = False
    method = ''

    # 1) ویرایش همان پیام در کانال مرجع (پایدارتر — message_id عوض نمی‌شود)
    if lb_mid:
        try:
            er = bc.edit_message_caption(lb, int(lb_mid), new_caption)
            if isinstance(er, dict) and er.get('ok'):
                edited = True
                method = 'editMessageCaption'
            else:
                logger.info('editMessageCaption failed: %s', (er or {}).get('error'))
        except Exception:
            logger.exception('editMessageCaption')

    # 2) اگر ویرایش ممکن نبود: کپی جدید با caption تازه و جایگزینی شناسه‌ها
    if not edited and lb_mid and banner.storage_chat_id and banner.storage_message_id:
        try:
            # کپی از پیام ذخیره‌شده مشتری با caption جدید ممکن است پشتیبانی نشود؛
            # copy بدون caption سپس edit، یا forward از linkbank و edit
            fr = bc.copy_message(lb, lb, int(lb_mid))
            if isinstance(fr, dict) and fr.get('ok'):
                new_mid = str(((fr.get('result') or {}).get('message_id')) or '')
                if new_mid:
                    er = bc.edit_message_caption(lb, int(new_mid), new_caption)
                    if isinstance(er, dict) and er.get('ok'):
                        # حذف پیام قدیمی اختیاری
                        try:
                            bc.delete_message(lb, int(lb_mid))
                        except Exception:
                            pass
                        banner.linkbank_message_id = new_mid
                        edited = True
                        method = 'recopy+edit'
                        # رفرش متای لینک‌یار
                        ly_meta = _capture_linkyar_file_meta(lb, caption=new_caption)
                        if ly_meta:
                            banner.ly_file_id = str(ly_meta.get('file_id') or banner.ly_file_id)
                            banner.ly_file_access_hash = str(
                                ly_meta.get('file_access_hash') or banner.ly_file_access_hash
                            )
                            if ly_meta.get('message_id'):
                                banner.linkyar_rid = str(ly_meta.get('message_id'))
                            if ly_meta.get('date'):
                                banner.linkyar_date = str(ly_meta.get('date'))
        except Exception:
            logger.exception('recopy banner for caption edit')

    banner.caption = new_caption
    if title_from_cap := (new_caption.strip().split('\n')[0][:120] if new_caption.strip() else ''):
        banner.title = title_from_cap
    fields = ['caption', 'title', 'linkbank_message_id', 'ly_file_id', 'ly_file_access_hash', 'linkyar_rid', 'linkyar_date']
    banner.save(update_fields=[f for f in fields if hasattr(banner, f)])

    return {
        'ok': True,
        'banner_id': banner.id,
        'method': method or 'db_only',
        'edited_in_channel': edited,
        'message': 'متن بنر به‌روز شد.' if edited else 'متن در سامانه به‌روز شد (ویرایش کانال مرجع ممکن نشد).',
    }


