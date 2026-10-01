"""پنل مشتری — خانه، بنرها (نام/ویرایش/حذف)، فهرست، سبد، سفارش‌ها، کیف پول."""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from bot_flow.banned_words import is_allowed
from bot_flow.handlers import ensure_user, get_session, save_session
from bot_flow.messages import fa_money, fa_num, user_error
from channels_app.models import Tariff
from integrations import bale_client as bc
from orders.availability import free_days_for_tariff
from orders.cart import add_to_cart, cart_summary, checkout, get_or_create_draft, set_banner
from orders.models import CustomerBanner, Order, OrderItem

logger = logging.getLogger(__name__)

STATE_CUST_HOME = 'cust_home'
STATE_CUST_BANNER_HUB = 'cust_banner_hub'
STATE_CUST_BANNER = 'cust_await_banner'
STATE_CUST_BANNER_NAME = 'cust_banner_name'
STATE_CUST_RENAME = 'cust_rename'
STATE_CUST_BROWSE = 'cust_browse'
STATE_CUST_PICK_DAY = 'cust_pick_day'
STATE_CUST_EDIT_CAPTION = 'cust_edit_caption'


def linkbank_username() -> str:
    raw = (
        os.environ.get('LINKBANK_CHANNEL')
        or os.environ.get('BANNER_REFERENCE_CHANNEL')
        or '@linktest'
    ).strip()
    if raw and not raw.startswith('@') and not raw.lstrip('-').isdigit():
        raw = '@' + raw
    return raw


def _nav_row() -> List[Dict[str, str]]:
    return [
        {'text': '🏠 خانه', 'callback_data': 'cu:home'},
        {'text': '🖼 بنرها', 'callback_data': 'cu:banners'},
        {'text': '🛒 انتخاب‌ها', 'callback_data': 'cu:cart'},
    ]


def customer_home_keyboard() -> Dict:
    return bc.inline_keyboard([
        [
            {'text': '🖼 بنرهای من', 'callback_data': 'cu:banners'},
            {'text': '➕ بنر جدید', 'callback_data': 'cu:new'},
        ],
        [
            {'text': '📋 فهرست تعرفه‌ها', 'callback_data': 'cu:catalog'},
            {'text': '🛒 انتخاب‌ها', 'callback_data': 'cu:cart'},
        ],
        [
            {'text': '📦 سفارش‌های من', 'callback_data': 'cu:orders'},
            {'text': '💰 کیف پول', 'callback_data': 'cu:wallet'},
        ],
        [{'text': '🔄 تعویض نقش', 'callback_data': 'nav:start'}],
    ])


def open_customer_home(chat_id: str, bale_user_id: str, username: str = '') -> None:
    user = ensure_user(bale_user_id, username)
    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_HOME, role='customer')
    from orders.banner_publish import banner_stage

    owned = list(CustomerBanner.objects.filter(customer=user, is_active=True))
    n_b = sum(1 for b in owned if banner_stage(b) == 'ready')
    n_pending = sum(1 for b in owned if banner_stage(b) == 'pending')
    draft = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
    n_cart = draft.items.count() if draft else 0
    n_open = Order.objects.filter(
        customer=user,
        status__in=(
            'waiting_banner',
            'waiting_managers',
            'waiting_customer_confirm',
            'waiting_payment',
            'paid',
        ),
    ).count()
    from wallet import services as ws

    bal = ws.balance_breakdown(user)
    text = (
        'بخش مشتری\n\n'
        f'نام شما در بله: {user.bale_handle or user.bale_user_id}\n'
        f'بنر آماده: {fa_num(n_b)}\n'
        f'در انتظار بررسی: {fa_num(n_pending)}\n'
        f'روز انتخاب‌شده: {fa_num(n_cart)}\n'
        f'سفارش باز: {fa_num(n_open)}\n'
        f'اعتبار: {fa_money(bal["credit"])}\n'
        f'در امانت: {fa_money(bal["escrow"])}\n\n'
        'اول بنر را بفرستید، بعد یک روز خالی بردارید.'
    )
    bc.send_message(str(chat_id), text, reply_markup=customer_home_keyboard())


def start_customer(chat_id: str, bale_user_id: str, username: str = '') -> None:
    open_customer_home(chat_id, bale_user_id, username)


def show_banner_list(chat_id: str, bale_user_id: str) -> None:
    user = ensure_user(bale_user_id)
    from orders.banner_publish import banner_stage

    banners = list(
        CustomerBanner.objects.filter(customer=user, is_active=True).order_by('-id')[:20]
    )
    stage_label = {
        'ready': 'آماده برای سفارش',
        'pending': 'در انتظار بررسی',
        'rejected': 'رد شده',
    }
    lb = linkbank_username()
    lines = [
        '🖼 بنرهای من',
        f'کانال بنرها: {lb}',
        'روی یک بنر بزنید.',
    ]
    rows: List[List[Dict[str, str]]] = [
        [{'text': '➕ افزودن بنر', 'callback_data': 'cu:new'}],
    ]
    if not banners:
        lines.append('')
        lines.append('هنوز بنری ندارید. دکمهٔ «افزودن بنر» را بزنید.')
    else:
        for b in banners:
            label = stage_label.get(banner_stage(b), '')
            rows.append([{
                'text': f'📌 {b.display_title()} · {label}'[:60],
                'callback_data': f'cu:banner:{b.id}',
            }])
    rows.append(_nav_row())
    bc.send_message(str(chat_id), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows))


def show_banner_detail(chat_id: str, bale_user_id: str, banner_id: int) -> None:
    user = ensure_user(bale_user_id)
    b = CustomerBanner.objects.filter(
        id=banner_id, customer=user, is_active=True
    ).first()
    if not b:
        bc.send_message(str(chat_id), 'این بنر را پیدا نکردم.')
        show_banner_list(chat_id, bale_user_id)
        return
    cap = (b.caption or '').strip()
    if len(cap) > 120:
        cap = cap[:120] + '…'
    kind = {
        'photo': 'عکس',
        'video': 'ویدیو',
        'animation': 'ویدیو',
        'document': 'فایل',
        'text': 'متن',
    }.get(b.media_kind or '', 'متن' if not b.media_kind else b.media_kind)
    lines = [
        f'📌 {b.display_title()}',
        f'نوع: {kind}',
        f'روی کانال بنرها: {"هست" if b.from_linkbank else "نیست. بگذارید پشتیبانی ببیند"}',
        f'متن: {cap or "بدون متن"}',
        '',
        'یکی از دکمه‌ها را بزنید:',
    ]
    rows = [
        [{'text': '✅ استفاده در سفارش', 'callback_data': f'cu:use:{b.id}'}],
        [
            {'text': '✏️ تغییر نام', 'callback_data': f'cu:rename:{b.id}'},
            {'text': '📝 ویرایش متن', 'callback_data': f'cu:editcap:{b.id}'},
        ],
        [{'text': '🗑 حذف', 'callback_data': f'cu:del:{b.id}'}],
        [
            {'text': '🔙 لیست بنرها', 'callback_data': 'cu:banners'},
            {'text': '🏠 خانه', 'callback_data': 'cu:home'},
        ],
    ]
    bc.send_message(str(chat_id), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows))


def _has_banner_media(message: dict) -> bool:
    return bool(
        message.get('photo')
        or message.get('video')
        or message.get('animation')
        or message.get('document')
    )


def _media_kind(message: dict) -> str:
    if message.get('photo'):
        return 'photo'
    if message.get('video') or message.get('animation'):
        return 'video'
    if message.get('document'):
        return 'document'
    if message.get('text'):
        return 'text'
    return 'unknown'


def _folded(value: str) -> str:
    return (
        (value or '')
        .replace('\u200c', '')
        .replace('\u200d', '')
        .replace(' ', '')
        .replace('_', '')
        .replace('-', '')
        .lower()
    )


def _is_linkbank_chat(uname: str, title: str) -> bool:
    lb = _folded(linkbank_username().lstrip('@'))
    folded_name = _folded(uname)
    folded_title = _folded(title)
    if folded_name and (folded_name == lb or folded_name in ('linkbank', 'linktest')):
        return True
    if lb and lb in folded_title:
        return True
    return 'لینکبانک' in folded_title or 'linkbank' in folded_title or 'linktest' in folded_title


def _forward_meta(message: dict) -> Tuple[bool, str, str]:
    fwd_chat = message.get('forward_from_chat') or {}
    if isinstance(fwd_chat, dict) and fwd_chat:
        uname = fwd_chat.get('username') or ''
        title = fwd_chat.get('title') or ''
        cid = str(fwd_chat.get('id') or '')
        mid = str(message.get('forward_from_message_id') or message.get('forward_message_id') or '')
        if _is_linkbank_chat(uname, title):
            return True, cid or linkbank_username(), mid
    origin = message.get('forward_origin') or {}
    if isinstance(origin, dict) and origin:
        chat = origin.get('chat') or {}
        if _is_linkbank_chat(chat.get('username') or '', chat.get('title') or origin.get('sender_user_name') or ''):
            return True, str(chat.get('id') or linkbank_username()), str(origin.get('message_id') or '')
    return False, '', ''


def _apply_banner_to_draft(
    user,
    *,
    storage_chat_id: str,
    storage_message_id: str,
    caption: str,
    from_linkbank: bool = False,
    linkbank_chat_id: str = '',
    linkbank_message_id: str = '',
    media_kind: str = '',
    banner: Optional[CustomerBanner] = None,
    title: str = '',
) -> CustomerBanner:
    if banner is None and from_linkbank and linkbank_message_id:
        banner = CustomerBanner.objects.filter(
            customer=user,
            is_active=True,
            from_linkbank=True,
            linkbank_message_id=str(linkbank_message_id),
        ).first()
    if banner is None:
        banner = CustomerBanner.objects.create(
            customer=user,
            title=(title or '')[:120],
            caption=caption or '',
            storage_chat_id=str(storage_chat_id),
            storage_message_id=str(storage_message_id),
            from_linkbank=from_linkbank,
            linkbank_chat_id=linkbank_chat_id or '',
            linkbank_message_id=linkbank_message_id or '',
            media_kind=media_kind or '',
        )
    Order.objects.filter(customer=user, status='draft').delete()
    order = get_or_create_draft(user)
    set_banner(order, str(storage_chat_id), str(storage_message_id), caption or '')
    order.customer_banner = banner
    order.save(update_fields=['customer_banner'])
    return banner


def _banner_rules() -> str:
    lb = linkbank_username()
    return (
        f'یک بنر بفرستید: عکس یا ویدیو با متن زیرش، '
        f'یا یک جملهٔ تبلیغ، یا بازارسال از کانال بنرها ({lb}).'
    )


def _confirm_banner(chat_id: str, bale_user_id: str, banner: CustomerBanner, *, from_reference: bool) -> None:
    sess = get_session(bale_user_id)
    preview = (banner.caption or '').strip().replace('\n', ' ')
    if len(preview) > 140:
        preview = preview[:140] + '…'
    if not preview:
        preview = 'بدون متن'
    if from_reference:
        note = 'بنر از کانال بنرها رسید. حالا کانال و روز را انتخاب کنید.'
    else:
        note = (
            'بنر برای بررسی رفت.\n'
            'حالا کانال و روز را انتخاب کنید.'
        )
    rows = [
        [{'text': 'تأیید و انتخاب کانال', 'callback_data': 'cu:catalog'}],
        [{'text': 'ویرایش', 'callback_data': f'cu:editcap:{banner.id}'}],
    ]
    slot = (sess.data or {}).get('pending_slot') or {}
    if slot.get('tariff_id') and slot.get('date'):
        rows.insert(0, [{
            'text': 'ادامه همان روز',
            'callback_data': f"cu:day:{slot['tariff_id']}:{slot['date']}",
        }])
    bc.send_message(
        str(chat_id),
        f'بنر رسید. پیش‌نمایشش را ببینید:\n{banner.display_title()}\n{preview}\n\n{note}',
        reply_markup=bc.inline_keyboard(rows),
    )


def handle_banner_message(chat_id: str, bale_user_id: str, message: dict) -> bool:
    sess = get_session(bale_user_id)
    caption = (message.get('caption') or message.get('text') or '')[:800]
    has_media = _has_banner_media(message)
    is_fwd = bool(
        message.get('forward_date')
        or message.get('forward_from_chat')
        or message.get('forward_origin')
        or message.get('forward_from')
    )
    waiting = sess.state in (STATE_CUST_BANNER, STATE_CUST_BANNER_HUB)
    if waiting and not has_media and not is_fwd and caption.strip().startswith('/'):
        return False
    if not is_fwd and not waiting:
        if has_media:
            bc.send_message(
                str(chat_id),
                'اگر این فایل بنر است، دکمهٔ «بنر جدید» را بزنید و دوباره بفرستید.\n\n'
                + _banner_rules(),
            )
            return True
        return False

    if not has_media and not is_fwd and len(caption.strip()) < 8:
        bc.send_message(str(chat_id), 'این متن برای بنر کوتاه است. یک جملهٔ کامل بفرستید.\n\n' + _banner_rules())
        return True

    ok, hits = is_allowed(caption)
    if not ok:
        bc.send_message(str(chat_id), 'این بنر را نمی‌توانم ثبت کنم. این عبارت مجاز نیست: ' + ', '.join(hits))
        return True

    user = ensure_user(bale_user_id)
    from_lb, lb_chat, lb_mid = _forward_meta(message)
    msg_id = message.get('message_id')
    if not msg_id:
        bc.send_message(str(chat_id), 'این پیام را نگرفتم. یک بار دیگر بفرستید.')
        return True

    banner = _apply_banner_to_draft(
        user,
        storage_chat_id=str(chat_id),
        storage_message_id=str(msg_id),
        caption=caption,
        from_linkbank=from_lb,
        linkbank_chat_id=str(lb_chat or linkbank_username()) if from_lb else '',
        linkbank_message_id=str(lb_mid or '') if from_lb else '',
        media_kind=_media_kind(message),
        title=(caption or '').strip().split('\n')[0][:120],
    )
    try:
        from orders.banner_media import save_banner_from_message

        save_banner_from_message(banner.id, message)
    except Exception:
        logger.exception('banner file')
    d = dict(sess.data or {})
    d['pending_banner'] = {'banner_id': banner.id}
    sess.data = d
    sess.save(update_fields=['data'])
    save_session(sess, STATE_CUST_HOME, role='customer')
    if not from_lb:
        from orders.banner_publish import create_publish_request

        try:
            create_publish_request(
                user,
                storage_chat_id=str(chat_id),
                storage_message_id=str(msg_id),
                caption=caption,
                media_kind=_media_kind(message),
                banner=banner,
            )
        except Exception:
            logger.exception('banner request')
    _confirm_banner(chat_id, bale_user_id, banner, from_reference=from_lb)
    return True


def _finish_named_banner(chat_id: str, bale_user_id: str, title: str) -> None:
    sess = get_session(bale_user_id)
    pending = (sess.data or {}).get('pending_banner') or {}
    if not pending:
        bc.send_message(str(chat_id), 'بنری برای نام‌گذاری نمانده. اول بنر را بفرستید.')
        open_customer_home(chat_id, bale_user_id)
        return
    user = ensure_user(bale_user_id)
    name = (title or '').strip()
    if name in ('.', '-', 'بدون نام', 'skip'):
        name = ''
    banner_id = pending.get('banner_id')
    if banner_id:
        banner = CustomerBanner.objects.filter(id=banner_id, customer=user, is_active=True).first()
        if not banner:
            bc.send_message(str(chat_id), 'این بنر را پیدا نکردم.')
            open_customer_home(chat_id, bale_user_id)
            return
        if name:
            banner.title = name[:120]
            banner.save(update_fields=['title'])
    else:
        banner = _apply_banner_to_draft(
            user,
            storage_chat_id=pending['chat_id'],
            storage_message_id=pending['message_id'],
            caption=pending.get('caption') or '',
            from_linkbank=bool(pending.get('from_linkbank')),
            linkbank_chat_id=pending.get('linkbank_chat_id') or '',
            linkbank_message_id=pending.get('linkbank_message_id') or '',
            media_kind=pending.get('media_kind') or '',
            title=name[:120],
        )
    d = dict(sess.data or {})
    d.pop('pending_banner', None)
    sess.data = d
    sess.save(update_fields=['data'])
    save_session(sess, STATE_CUST_BROWSE, role='customer')
    bc.send_message(
        str(chat_id),
        f'✅ بنر «{banner.display_title()}» ذخیره شد و برای سفارش انتخاب شد.\n'
        'حالا تعرفه را انتخاب کنید:',
    )
    show_catalog(chat_id, bale_user_id)


def use_saved_banner(chat_id: str, bale_user_id: str, banner_id: int) -> None:
    user = ensure_user(bale_user_id)
    from orders.banner_publish import banner_stage

    banner = CustomerBanner.objects.filter(
        id=banner_id, customer=user, is_active=True
    ).first()
    if not banner or banner_stage(banner) == 'rejected':
        bc.send_message(str(chat_id), 'این بنر هنوز روی کانال بنرها نیست. اول بگذارید پشتیبانی ببیند.')
        show_banner_list(chat_id, bale_user_id)
        return
    Order.objects.filter(customer=user, status='draft').delete()
    order = get_or_create_draft(user)
    set_banner(order, banner.storage_chat_id, banner.storage_message_id, banner.caption)
    order.customer_banner = banner
    order.save(update_fields=['customer_banner'])
    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_BROWSE, role='customer')
    bc.send_message(str(chat_id), f'✅ بنر «{banner.display_title()}» انتخاب شد.\nحالا فهرست تعرفه‌ها را ببینید.')
    show_catalog(chat_id, bale_user_id)


def soft_delete_banner(chat_id: str, bale_user_id: str, banner_id: int) -> None:
    user = ensure_user(bale_user_id)
    b = CustomerBanner.objects.filter(id=banner_id, customer=user, is_active=True).first()
    if not b:
        bc.send_message(str(chat_id), 'این بنر را پیدا نکردم.')
        return
    b.is_active = False
    b.save(update_fields=['is_active'])
    bc.send_message(str(chat_id), f'🗑 «{b.display_title()}» حذف شد.')
    show_banner_list(chat_id, bale_user_id)


def models_q():
    from django.db.models import Q

    return Q(is_active=True) & (Q(channel__isnull=False) | Q(group__isnull=False))


def show_catalog(chat_id: str, bale_user_id: str, page: int = 0) -> None:
    page_size = 8
    tariffs = list(
        Tariff.objects.select_related('channel', 'group').filter(models_q()).order_by('id')
    )
    if not tariffs:
        bc.send_message(
            str(chat_id),
            'الان تعرفه‌ای برای انتخاب نیست. کمی بعد دوباره سر بزنید.',
            reply_markup=bc.inline_keyboard([_nav_row()]),
        )
        return
    start = page * page_size
    chunk = tariffs[start : start + page_size]
    rows = []
    for t in chunk:
        if t.group_id:
            label = f'📦 {t.group.name} | {t.name} | {fa_money(t.price, "ت")}'
        else:
            ch = t.channel.name if t.channel else '?'
            label = f'📢 {ch} | {t.name} | {fa_money(t.price, "ت")}'
        rows.append([{'text': label[:64], 'callback_data': f'cu:tar:{t.id}'}])
    nav = []
    if page > 0:
        nav.append({'text': '◀️ قبل', 'callback_data': f'cu:page:{page - 1}'})
    if start + page_size < len(tariffs):
        nav.append({'text': 'بعد ▶️', 'callback_data': f'cu:page:{page + 1}'})
    if nav:
        rows.append(nav)
    rows.append([
        {'text': '🛒 انتخاب‌ها', 'callback_data': 'cu:cart'},
        {'text': '✅ ثبت سفارش', 'callback_data': 'cu:check'},
    ])
    rows.append(_nav_row())
    bc.send_message(
        str(chat_id),
        f'📋 فهرست تعرفه‌ها — صفحه {fa_num(page + 1)}',
        reply_markup=bc.inline_keyboard(rows),
    )


def show_days_for_tariff(chat_id: str, bale_user_id: str, tariff_id: int) -> None:
    t = Tariff.objects.select_related('channel', 'group').filter(id=tariff_id, is_active=True).first()
    if not t:
        bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
        return
    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_PICK_DAY, cart_tariff_id=tariff_id)
    today = timezone.localdate()
    free = list(free_days_for_tariff(t, today, today + timedelta(days=13)))
    owner = t.group.name if t.group_id else (t.channel.name if t.channel else '?')
    if not free:
        bc.send_message(
            str(chat_id),
            f'برای «{owner} — {t.name}» در این روزها نوبت خالی نیست.',
            reply_markup=bc.inline_keyboard([
                [{'text': 'فهرست', 'callback_data': 'cu:catalog'}],
                _nav_row(),
            ]),
        )
        return
    rows = []
    row: List[Dict[str, str]] = []
    for d in free[:14]:
        short = f'{d.month}/{d.day}'
        try:
            from bot_flow.jalali import to_jalali

            _jy, jm, jd = to_jalali(d)
            short = f'{jm}/{jd}'
        except Exception:
            pass
        row.append({'text': short, 'callback_data': f'cu:day:{t.id}:{d.isoformat()}'})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        {'text': 'فهرست', 'callback_data': 'cu:catalog'},
        {'text': 'انتخاب‌ها', 'callback_data': 'cu:cart'},
    ])
    bc.send_message(
        str(chat_id),
        f'📅 روز خالی\n{owner} — {t.name} — {fa_money(t.price)}',
        reply_markup=bc.inline_keyboard(rows),
    )


def show_my_orders(chat_id: str, bale_user_id: str) -> None:
    user = ensure_user(bale_user_id)
    orders = list(
        Order.objects.filter(customer=user)
        .exclude(status='draft')
        .order_by('-id')[:15]
    )
    if not orders:
        bc.send_message(
            str(chat_id),
            'هنوز سفارشی ندارید. از فهرست یک روز خالی بردارید.',
            reply_markup=customer_home_keyboard(),
        )
        return
    from bot_flow.messages import fa_num, format_order_line_customer

    lines = ['سفارش‌های اخیر:']
    pay_rows = []
    for o in orders:
        n = o.items.exclude(manager_status='cart').count() or o.items.count()
        lines.append(format_order_line_customer(o.id, o.status, n, o.total_amount))
        if o.status == 'waiting_payment' and (o.total_amount or 0) > 0:
            pay_rows.append([
                {'text': f'پرداخت سفارش {fa_num(o.id)}', 'callback_data': f'cu:pay:{o.id}'},
            ])
    home = customer_home_keyboard()['inline_keyboard']
    bc.send_message(
        str(chat_id),
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(pay_rows + home),
    )


def handle_customer_callback(
    chat_id: str, bale_user_id: str, data: str, cq_id: Optional[str] = None
) -> bool:
    # سازگاری قدیمی + پیشوند جدید
    aliases = {
        'cbhub': 'cu:banners',
        'cbnew': 'cu:new',
        'ccart': 'cu:cart',
        'ccheck': 'cu:check',
        'cwallet': 'cu:wallet',
        'cbreq': 'cu:req',
    }
    if data in aliases:
        data = aliases[data]
    if data.startswith('cbuse:'):
        data = 'cu:use:' + data.split(':', 1)[1]
    if data.startswith('cbedit:'):
        data = 'cu:editcap:' + data.split(':', 1)[1]
    if data.startswith('ctar:'):
        data = 'cu:tar:' + data.split(':', 1)[1]
    if data.startswith('cday:'):
        data = 'cu:day:' + data.split(':', 1)[1]
    if data.startswith('cpage:'):
        data = 'cu:page:' + data.split(':', 1)[1]

    if not (
        data.startswith('cu:')
        or data.startswith('custok:')
        or data.startswith('custno:')
    ):
        return False
    if cq_id:
        bc.answer_callback_query(str(cq_id), text='✓')

    user = ensure_user(bale_user_id)

    if data == 'cu:home':
        open_customer_home(chat_id, bale_user_id)
        return True
    if data == 'cu:banners':
        show_banner_list(chat_id, bale_user_id)
        return True
    if data == 'cu:new':
        sess = get_session(bale_user_id)
        save_session(sess, STATE_CUST_BANNER, role='customer')
        lb = linkbank_username()
        bc.send_message(
            str(chat_id),
            f'بنر را بفرستید: عکس یا ویدیو، و متن را زیر همان عکس بنویسید.\n'
            f'اگر بنر از قبل در کانال بنرها ({lb}) هست، همان پست را بازارسال کنید.',
            reply_markup=bc.inline_keyboard([[{'text': 'انصراف', 'callback_data': 'cu:banners'}]]),
        )
        return True
    if data == 'cu:catalog':
        show_catalog(chat_id, bale_user_id)
        return True
    if data == 'cu:orders':
        show_my_orders(chat_id, bale_user_id)
        return True
    if data.startswith('cu:pay:'):
        try:
            order_id = int(data.split(':')[2])
        except (IndexError, ValueError):
            return True
        order = Order.objects.filter(id=order_id, customer=user, status='waiting_payment').first()
        if not order:
            bc.send_message(str(chat_id), 'این سفارش الان برای پرداخت نیست. وضعیت را در سفارش‌ها ببینید.')
            return True
        from orders.bale_pay import announce_invoices, order_is_fully_paid, send_order_invoices
        from orders.services import process_payment_paid

        if order_is_fully_paid(order):
            process_payment_paid(order.id)
            return True
        result = send_order_invoices(order, str(chat_id))
        if result['sent'] == 0 and result['failed'] == 0:
            bc.send_message(str(chat_id), 'فاکتور تازه‌ای نمانده. اگر همه را پرداخت کرده‌اید، کمی بعد دوباره نگاه کنید.')
            return True
        announce_invoices(str(chat_id), result)
        return True
    if data == 'cu:wallet':
        from bot_flow.manager_panel import show_wallet

        show_wallet(chat_id, user)
        return True

    if data.startswith('cu:banner:'):
        show_banner_detail(chat_id, bale_user_id, int(data.split(':')[2]))
        return True
    if data.startswith('cu:use:'):
        use_saved_banner(chat_id, bale_user_id, int(data.split(':')[2]))
        return True
    if data.startswith('cu:rename:'):
        bid = int(data.split(':')[2])
        sess = get_session(bale_user_id)
        d = dict(sess.data or {})
        d['rename_banner_id'] = bid
        save_session(sess, STATE_CUST_RENAME, role='customer')
        sess.data = d
        sess.save(update_fields=['data'])
        bc.send_message(str(chat_id), 'یک نام کوتاه برای این بنر بفرستید.')
        return True
    if data.startswith('cu:editcap:'):
        bid = int(data.split(':')[2])
        sess = get_session(bale_user_id)
        d = dict(sess.data or {})
        d['edit_banner_id'] = bid
        save_session(sess, STATE_CUST_EDIT_CAPTION, role='customer')
        sess.data = d
        sess.save(update_fields=['data'])
        bc.send_message(str(chat_id), 'متن تازهٔ بنر را بفرستید. عکس و ویدیو همان می‌ماند.')
        return True
    if data.startswith('cu:del:'):
        bid = int(data.split(':')[2])
        kb = bc.inline_keyboard([
            [
                {'text': 'بله، حذف شود', 'callback_data': f'cu:delok:{bid}'},
                {'text': 'خیر', 'callback_data': f'cu:banner:{bid}'},
            ]
        ])
        bc.send_message(str(chat_id), 'این بنر حذف شود؟', reply_markup=kb)
        return True
    if data.startswith('cu:delok:'):
        soft_delete_banner(chat_id, bale_user_id, int(data.split(':')[2]))
        return True

    if data == 'cu:req':
        sess = get_session(bale_user_id)
        pending = (sess.data or {}).get('pending_banner')
        if not pending:
            bc.send_message(str(chat_id), 'بنری برای ثبت درخواست نمانده. اول بنر را بفرستید.')
            return True
        from orders.banner_publish import create_publish_request

        r = create_publish_request(
            user,
            storage_chat_id=pending['chat_id'],
            storage_message_id=pending['message_id'],
            caption=pending.get('caption') or '',
            media_kind=pending.get('media_kind') or '',
        )
        fee = r.get('fee') or 0
        d = dict(sess.data or {})
        d.pop('pending_banner', None)
        sess.data = d
        sess.save(update_fields=['data'])
        fee_txt = 'رایگان' if fee == 0 else fa_money(fee)
        bc.send_message(
            str(chat_id),
            f'📨 درخواست برای پشتیبانی ثبت شد.\nهزینهٔ اعلام‌شده: {fee_txt}',
            reply_markup=customer_home_keyboard(),
        )
        return True

    if data.startswith('custok:') or data.startswith('custno:'):
        from orders.cart import customer_confirm_edit

        item_id = int(data.split(':')[1])
        result = customer_confirm_edit(item_id, bale_user_id, data.startswith('custok:'))
        bc.send_message(
            str(chat_id),
            'ثبت شد.' if result.get('ok') else user_error(result.get('error')),
        )
        return True

    if data.startswith('cu:page:'):
        show_catalog(chat_id, bale_user_id, page=int(data.split(':')[2]))
        return True

    if data == 'cu:cart':
        order = get_or_create_draft(user)
        kb = bc.inline_keyboard([
            [
                {'text': 'ادامه خرید', 'callback_data': 'cu:catalog'},
                {'text': '✅ ثبت سفارش', 'callback_data': 'cu:check'},
            ],
            _nav_row(),
        ])
        bc.send_message(str(chat_id), cart_summary(order), reply_markup=kb)
        return True

    if data == 'cu:check':
        order = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
        if not order:
            bc.send_message(str(chat_id), 'هنوز روزی انتخاب نکرده‌اید.', reply_markup=customer_home_keyboard())
            return True
        result = checkout(order)
        if not result.get('ok'):
            err = result.get('error')
            msg = {
                'empty_cart': 'هنوز روزی انتخاب نکرده‌اید.',
                'no_banner': 'اول یک بنر بیاورید. تا وقتی بنری نداشته باشید، نمی‌توانید روزی را انتخاب کنید.',
                'slot_conflict': 'یکی از روزها پر شد. انتخاب‌ها را دوباره ببینید.',
            }.get(err) or user_error(err)
            bc.send_message(str(chat_id), msg)
            return True
        bc.send_message(
            str(chat_id),
            f'سفارش ثبت شد. منتظر جواب {fa_num(result["count"])} کانال‌دار بمانید.',
            reply_markup=customer_home_keyboard(),
        )
        sess = get_session(bale_user_id)
        save_session(sess, STATE_CUST_HOME, role='customer')
        return True

    if data.startswith('cu:tar:'):
        show_days_for_tariff(chat_id, bale_user_id, int(data.split(':')[2]))
        return True

    if data.startswith('cu:day:'):
        parts = data.split(':', 3)
        tariff_id = int(parts[2])
        from datetime import date

        day = date.fromisoformat(parts[3])
        t = Tariff.objects.filter(id=tariff_id, is_active=True).first()
        if not t:
            bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
            return True
        order = get_or_create_draft(user)
        if not order.banner_message_id:
            sess = get_session(bale_user_id)
            d = dict(sess.data or {})
            d['pending_slot'] = {'tariff_id': tariff_id, 'date': parts[3]}
            sess.data = d
            sess.save(update_fields=['data'])
            bc.send_message(
                str(chat_id),
                'این روز را نگه داشتم.\n'
                'حالا بنر را بفرستید: عکس، ویدیو یا متن تبلیغ.',
                reply_markup=bc.inline_keyboard([
                    [{'text': 'ساخت بنر', 'callback_data': 'cu:new'}],
                    [{'text': 'بنرهای من', 'callback_data': 'cu:banners'}],
                ]),
            )
            return True
        result = add_to_cart(user, t, day)
        sess = get_session(bale_user_id)
        d = dict(sess.data or {})
        if 'pending_slot' in d:
            d.pop('pending_slot', None)
            sess.data = d
            sess.save(update_fields=['data'])
        if not result.get('ok'):
            bc.send_message(str(chat_id), 'این روز دیگر خالی نیست. روز دیگری را انتخاب کنید.')
            show_days_for_tariff(chat_id, bale_user_id, tariff_id)
            return True
        kb = bc.inline_keyboard([
            [
                {'text': 'تعرفه دیگر', 'callback_data': 'cu:catalog'},
                {'text': 'انتخاب‌ها', 'callback_data': 'cu:cart'},
            ],
            [{'text': '✅ ثبت سفارش', 'callback_data': 'cu:check'}],
        ])
        bc.send_message(
            str(chat_id),
            f'این روز انتخاب شد.\n\n{cart_summary(result["order"])}',
            reply_markup=kb,
        )
        return True

    return False


def try_handle_customer_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    norm = (text or '').strip()

    if norm in ('/customer', '/cust', '/مشتری', 'پنل مشتری'):
        open_customer_home(chat_id, bale_user_id)
        return True
    if norm in ('/banners', 'بنر', 'بنرها'):
        show_banner_list(chat_id, bale_user_id)
        return True
    if norm in ('/wallet', '/کیف', 'کیف پول'):
        from bot_flow.manager_panel import show_wallet

        show_wallet(chat_id, ensure_user(bale_user_id))
        return True

    if sess.state == STATE_CUST_BANNER_NAME:
        _finish_named_banner(chat_id, bale_user_id, norm)
        return True

    if sess.state == STATE_CUST_RENAME:
        bid = (sess.data or {}).get('rename_banner_id')
        if not bid:
            open_customer_home(chat_id, bale_user_id)
            return True
        user = ensure_user(bale_user_id)
        b = CustomerBanner.objects.filter(id=bid, customer=user, is_active=True).first()
        if not b:
            bc.send_message(str(chat_id), 'این بنر را پیدا نکردم.')
            open_customer_home(chat_id, bale_user_id)
            return True
        b.title = (norm or '')[:40]
        b.save(update_fields=['title'])
        save_session(sess, STATE_CUST_HOME, role='customer')
        bc.send_message(str(chat_id), f'✅ نام بنر «{b.display_title()}» شد.')
        show_banner_detail(chat_id, bale_user_id, b.id)
        return True

    if sess.state == STATE_CUST_EDIT_CAPTION:
        bid = (sess.data or {}).get('edit_banner_id')
        if not bid:
            open_customer_home(chat_id, bale_user_id)
            return True
        from orders.banner_publish import edit_banner_caption

        r = edit_banner_caption(int(bid), bale_user_id, norm)
        if not r.get('ok'):
            bc.send_message(str(chat_id), r.get('message') or user_error(r.get('error')))
            return True
        save_session(sess, STATE_CUST_HOME, role='customer')
        bc.send_message(str(chat_id), '✅ متن بنر به‌روز شد.')
        show_banner_detail(chat_id, bale_user_id, int(bid))
        return True

    if sess.state == STATE_CUST_BANNER:
        return False

    if sess.state in (STATE_CUST_HOME, STATE_CUST_BANNER_HUB):
        if norm:
            bc.send_message(
                str(chat_id),
                'از دکمه‌های پایین یکی را بزنید.',
                reply_markup=customer_home_keyboard(),
            )
            return True

    if sess.state in (STATE_CUST_BROWSE, STATE_CUST_PICK_DAY):
        if norm in ('/cart', 'سبد', 'انتخاب‌ها', 'انتخاب'):
            handle_customer_callback(chat_id, bale_user_id, 'cu:cart')
            return True
        if norm in ('/catalog', 'فهرست'):
            show_catalog(chat_id, bale_user_id)
            return True
    return False
