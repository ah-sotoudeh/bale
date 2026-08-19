"""Customer-side conversation: بنرها → فهرست → سبد → نهایی‌سازی.

نام‌گذاری کانال‌ها:
  لینک‌بانک (@linkbank) = کانال مرجع عمومی بنرهای تبلیغاتی
  لینک‌بان (@linkban) = فهرست تعرفه‌ها (معرفی)
  لینک‌ساز = بازوی سفارش
  لینک‌یار = حساب شخصی برای تاریخچه/ارسال
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from bot_flow.banned_words import is_allowed
from bot_flow.handlers import ensure_user, get_session, save_session
from channels_app.models import Tariff
from integrations import bale_client as bc
from orders.availability import free_days_for_tariff
from orders.cart import (
    add_to_cart,
    cart_summary,
    checkout,
    get_or_create_draft,
    set_banner,
)
from orders.models import CustomerBanner, Order

logger = logging.getLogger(__name__)

STATE_CUST_BANNER_HUB = 'cust_banner_hub'
STATE_CUST_BANNER = 'cust_await_banner'
STATE_CUST_BROWSE = 'cust_browse'
STATE_CUST_PICK_DAY = 'cust_pick_day'


def linkbank_username() -> str:
    raw = (
        os.environ.get('LINKBANK_CHANNEL')
        or os.environ.get('BANNER_REFERENCE_CHANNEL')
        or '@linkbank'
    ).strip()
    if raw and not raw.startswith('@') and not raw.lstrip('-').isdigit():
        raw = '@' + raw
    return raw


def _media_kind(message: dict) -> str:
    if message.get('photo'):
        return 'photo'
    if message.get('video'):
        return 'video'
    if message.get('document'):
        return 'document'
    if message.get('text'):
        return 'text'
    return 'unknown'


def _forward_meta(message: dict) -> Tuple[bool, str, str]:
    """آیا از لینک‌بانک آمده؟ (chat_id, message_id) مبدأ در صورت وجود."""
    lb = linkbank_username().lstrip('@').lower()

    # Telegram/Bale-style forward fields
    fwd_chat = message.get('forward_from_chat') or {}
    if isinstance(fwd_chat, dict) and fwd_chat:
        uname = (fwd_chat.get('username') or '').lower()
        title = (fwd_chat.get('title') or '').lower()
        cid = str(fwd_chat.get('id') or '')
        mid = str(message.get('forward_from_message_id') or message.get('forward_message_id') or '')
        if uname == lb or 'linkbank' in uname or 'لینک بانک' in title or 'link bank' in title:
            return True, cid or linkbank_username(), mid

    origin = message.get('forward_origin') or {}
    if isinstance(origin, dict):
        chat = origin.get('chat') or {}
        uname = (chat.get('username') or '').lower()
        if uname == lb or 'linkbank' in uname:
            return True, str(chat.get('id') or linkbank_username()), str(origin.get('message_id') or '')

    # caption/text hint (weak)
    text = (message.get('caption') or message.get('text') or '')
    if 'ble.ir/linkbank' in text.lower() or 'ble.ir/linkbank' in text:
        return True, linkbank_username(), ''

    # any forward without resolvable chat — still mark if user was asked to forward from linkbank
    if message.get('forward_date') or message.get('forward_from') or message.get('forward_sender_name'):
        # not necessarily linkbank
        return False, '', ''

    return False, '', ''


def start_customer(chat_id: str, bale_user_id: str, username: str = '') -> None:
    ensure_user(bale_user_id, username)
    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_BANNER_HUB, role='customer', cart_tariff_id=None)
    show_banner_hub(chat_id, bale_user_id)


def show_banner_hub(chat_id: str, bale_user_id: str) -> None:
    user = ensure_user(bale_user_id)
    banners = list(
        CustomerBanner.objects.filter(customer=user, is_active=True).order_by('-id')[:12]
    )
    lb = linkbank_username()

    lines = [
        '🎨 *مرکز بنر*',
        '',
        'برای سفارش تبلیغ یک بنر انتخاب کنید یا بسازید.',
        '',
        f'اگر بنر را قبلاً در کانال مرجع {lb} گذاشته‌اید،',
        'همان مطلب را *بازارسال* کنید به همین بازو (لینک‌ساز).',
        '',
        'در غیر این صورت بنر جدید (عکس/ویدیو + متن) بفرستید.',
    ]
    rows: List[List[Dict[str, str]]] = [
        [{'text': '➕ بنر جدید / بازارسال از لینک‌بانک', 'callback_data': 'cbnew'}],
    ]
    if banners:
        lines.append('')
        lines.append('بنرهای قبلی شما:')
        for b in banners:
            tag = '🏷 لینک‌بانک' if b.from_linkbank else '📎'
            lines.append(f'• {tag} {b.display_title()}')
            rows.append([{
                'text': f'✅ استفاده: {b.display_title()}'[:64],
                'callback_data': f'cbuse:{b.id}',
            }])
    else:
        lines.append('')
        lines.append('هنوز بنر ذخیره‌شده‌ای ندارید.')

    rows.append([{'text': '🛒 سبد فعلی', 'callback_data': 'ccart'}])
    bc.send_message(
        str(chat_id),
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(rows),
    )


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
) -> CustomerBanner:
    if banner is None:
        banner = CustomerBanner.objects.create(
            customer=user,
            caption=caption or '',
            storage_chat_id=str(storage_chat_id),
            storage_message_id=str(storage_message_id),
            from_linkbank=from_linkbank,
            linkbank_chat_id=linkbank_chat_id or '',
            linkbank_message_id=linkbank_message_id or '',
            media_kind=media_kind or '',
            title='',
        )
    Order.objects.filter(customer=user, status='draft').delete()
    order = get_or_create_draft(user)
    set_banner(order, str(storage_chat_id), str(storage_message_id), caption or '')
    order.customer_banner = banner
    order.save(update_fields=['customer_banner'])
    return banner


def handle_banner_message(
    chat_id: str,
    bale_user_id: str,
    message: dict,
) -> bool:
    sess = get_session(bale_user_id)
    if sess.state not in (STATE_CUST_BANNER, STATE_CUST_BANNER_HUB):
        return False

    caption = message.get('caption') or message.get('text') or ''
    has_media = bool(message.get('photo') or message.get('video') or message.get('document'))
    is_fwd = bool(
        message.get('forward_date')
        or message.get('forward_from_chat')
        or message.get('forward_origin')
        or message.get('forward_from')
    )
    if not has_media and not caption and not is_fwd:
        bc.send_message(str(chat_id), 'بنر باید شامل تصویر یا ویدیو باشد (یا بازارسال از لینک‌بانک).')
        return True

    ok, hits = is_allowed(caption)
    if not ok:
        bc.send_message(
            str(chat_id),
            'متأسفانه امکان ثبت این تبلیغ وجود ندارد.\n'
            f'عبارت‌های غیرمجاز: {", ".join(hits)}',
        )
        return True

    user = ensure_user(bale_user_id)
    from_lb, lb_chat, lb_mid = _forward_meta(message)
    # اگر کاربر در حالت انتظار بنر است و بازارسال کرده، احتمالاً از لینک‌بانک است
    if is_fwd and not from_lb and sess.state == STATE_CUST_BANNER:
        from_lb = True
        lb_chat = lb_chat or linkbank_username()

    msg_id = message.get('message_id')
    banner = _apply_banner_to_draft(
        user,
        storage_chat_id=str(chat_id),
        storage_message_id=str(msg_id),
        caption=caption,
        from_linkbank=from_lb,
        linkbank_chat_id=str(lb_chat or ''),
        linkbank_message_id=str(lb_mid or ''),
        media_kind=_media_kind(message),
    )

    save_session(sess, STATE_CUST_BROWSE, role='customer')
    note = ' (از لینک‌بانک)' if banner.from_linkbank else ''
    bc.send_message(
        str(chat_id),
        f'بنر ذخیره شد ✅{note}\n«{banner.display_title()}»\n\nحالا تعرفه را از فهرست انتخاب کنید.',
    )
    show_catalog(chat_id, bale_user_id)
    return True


def use_saved_banner(chat_id: str, bale_user_id: str, banner_id: int) -> None:
    user = ensure_user(bale_user_id)
    banner = CustomerBanner.objects.filter(
        id=banner_id, customer=user, is_active=True
    ).first()
    if not banner:
        bc.send_message(str(chat_id), 'بنر پیدا نشد.')
        show_banner_hub(chat_id, bale_user_id)
        return

    Order.objects.filter(customer=user, status='draft').delete()
    order = get_or_create_draft(user)
    set_banner(
        order,
        banner.storage_chat_id,
        banner.storage_message_id,
        banner.caption,
    )
    order.customer_banner = banner
    order.save(update_fields=['customer_banner'])

    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_BROWSE, role='customer')
    bc.send_message(
        str(chat_id),
        f'بنر «{banner.display_title()}» انتخاب شد ✅\nفهرست تعرفه‌ها:',
    )
    show_catalog(chat_id, bale_user_id)


def models_q():
    from django.db.models import Q

    return Q(is_active=True) & (Q(channel__isnull=False) | Q(group__isnull=False))


def show_catalog(chat_id: str, bale_user_id: str, page: int = 0) -> None:
    page_size = 8
    tariffs: List[Tariff] = list(
        Tariff.objects.select_related('channel', 'group').filter(models_q()).order_by('id')
    )
    if not tariffs:
        bc.send_message(
            str(chat_id),
            'فعلاً تعرفه‌ای در فهرست نیست.\n'
            'مدیران هنوز کانال ثبت نکرده‌اند یا تعرفه فعال نیست.\n'
            'فهرست عمومی: ble.ir/linkban',
        )
        return

    start = page * page_size
    chunk = tariffs[start : start + page_size]
    rows = []
    for t in chunk:
        if t.group_id:
            label = f'📦 {t.group.name} | {t.name} | {t.price:,}ت'
        else:
            ch = t.channel.name if t.channel else '?'
            label = f'📢 {ch} | {t.name} | {t.price:,}ت'
        rows.append([{'text': label[:64], 'callback_data': f'ctar:{t.id}'}])

    nav = []
    if page > 0:
        nav.append({'text': '◀️ قبل', 'callback_data': f'cpage:{page - 1}'})
    if start + page_size < len(tariffs):
        nav.append({'text': 'بعد ▶️', 'callback_data': f'cpage:{page + 1}'})
    if nav:
        rows.append(nav)
    rows.append([
        {'text': '🛒 سبد', 'callback_data': 'ccart'},
        {'text': '🎨 بنرها', 'callback_data': 'cbhub'},
        {'text': '✅ نهایی‌سازی', 'callback_data': 'ccheck'},
    ])

    bc.send_message(
        str(chat_id),
        f'📋 فهرست تعرفه‌ها (صفحه {page + 1})\n'
        'یک تعرفه را انتخاب کنید تا روزهای خالی را ببینید:\n'
        '(مرجع عمومی: ble.ir/linkban)',
        reply_markup=bc.inline_keyboard(rows),
    )


def show_days_for_tariff(chat_id: str, bale_user_id: str, tariff_id: int) -> None:
    t = Tariff.objects.select_related('channel', 'group').filter(id=tariff_id, is_active=True).first()
    if not t:
        bc.send_message(str(chat_id), 'تعرفه پیدا نشد یا غیرفعال است.')
        return

    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_PICK_DAY, cart_tariff_id=tariff_id)

    today = timezone.localdate()
    until = today + timedelta(days=13)
    free = list(free_days_for_tariff(t, today, until))

    owner = t.group.name if t.group_id else (t.channel.name if t.channel else '?')
    if not free:
        bc.send_message(
            str(chat_id),
            f'برای «{owner} — {t.name}» در ۱۴ روز آینده نوبت خالی نیست.',
            reply_markup=bc.inline_keyboard([
                [{'text': '⬅️ فهرست', 'callback_data': 'cpage:0'}]
            ]),
        )
        return

    rows = []
    row: List[Dict[str, str]] = []
    for d in free[:14]:
        short = f'{d.month}/{d.day}'
        try:
            from bot_flow.jalali import to_jalali

            jy, jm, jd = to_jalali(d)
            short = f'{jm}/{jd}'
        except Exception:
            pass
        row.append({'text': short, 'callback_data': f'cday:{t.id}:{d.isoformat()}'})
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        {'text': '⬅️ فهرست', 'callback_data': 'cpage:0'},
        {'text': '🛒 سبد', 'callback_data': 'ccart'},
    ])

    bc.send_message(
        str(chat_id),
        f'📅 روز خالی برای\n{owner} — {t.name} — {t.price:,} ت\n'
        f'یک روز را انتخاب کنید:',
        reply_markup=bc.inline_keyboard(rows),
    )


def handle_customer_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
) -> bool:
    if not data.startswith((
        'ctar:', 'cday:', 'cpage:', 'ccart', 'ccheck',
        'custok:', 'custno:', 'cbnew', 'cbuse:', 'cbhub',
    )):
        return False

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='…')

    user = ensure_user(bale_user_id)

    if data == 'cbhub':
        sess = get_session(bale_user_id)
        save_session(sess, STATE_CUST_BANNER_HUB, role='customer')
        show_banner_hub(chat_id, bale_user_id)
        return True

    if data == 'cbnew':
        sess = get_session(bale_user_id)
        save_session(sess, STATE_CUST_BANNER, role='customer')
        lb = linkbank_username()
        bc.send_message(
            str(chat_id),
            'بنر را بفرستید:\n'
            f'• اگر در {lb} دارید → همان مطلب را *بازارسال* کنید به اینجا\n'
            '• یا عکس/ویدیو + متن جدید بفرستید\n\n'
            'دقیقاً همان چیزی که باید تبلیغ شود را بفرستید.',
        )
        return True

    if data.startswith('cbuse:'):
        use_saved_banner(chat_id, bale_user_id, int(data.split(':')[1]))
        return True

    if data.startswith('custok:') or data.startswith('custno:'):
        from orders.cart import customer_confirm_edit

        item_id = int(data.split(':')[1])
        accept = data.startswith('custok:')
        result = customer_confirm_edit(item_id, bale_user_id, accept)
        bc.send_message(
            str(chat_id),
            'ثبت شد.' if result.get('ok') else f'خطا: {result.get("error")}',
        )
        return True

    if data.startswith('cpage:'):
        show_catalog(chat_id, bale_user_id, page=int(data.split(':')[1]))
        return True

    if data == 'ccart':
        order = get_or_create_draft(user)
        text = cart_summary(order)
        kb = bc.inline_keyboard([
            [
                {'text': '➕ ادامه خرید', 'callback_data': 'cpage:0'},
                {'text': '✅ نهایی‌سازی', 'callback_data': 'ccheck'},
            ],
            [{'text': '🎨 تعویض بنر', 'callback_data': 'cbhub'}],
        ])
        bc.send_message(str(chat_id), text, reply_markup=kb)
        return True

    if data == 'ccheck':
        order = (
            Order.objects.filter(customer=user, status='draft').order_by('-id').first()
        )
        if not order:
            bc.send_message(str(chat_id), 'سبد خالی است.')
            return True
        result = checkout(order)
        if not result.get('ok'):
            err = result.get('error')
            msg = {
                'empty_cart': 'سبد خالی است.',
                'no_banner': 'اول بنر را انتخاب یا ارسال کنید. /start',
                'slot_conflict': 'یکی از نوبت‌ها دیگر خالی نیست.',
            }.get(err, str(err))
            bc.send_message(str(chat_id), msg)
            return True
        bc.send_message(
            str(chat_id),
            f'سفارش #{order.id} برای {result["count"]} آیتم ثبت شد.\n'
            f'در انتظار تأیید مدیران (حداکثر ۱۲ ساعت).\n'
            f'نتیجه همه آیتم‌ها یک‌جا اعلام می‌شود.',
        )
        sess = get_session(bale_user_id)
        save_session(sess, 'idle', role='customer')
        return True

    if data.startswith('ctar:'):
        show_days_for_tariff(chat_id, bale_user_id, int(data.split(':')[1]))
        return True

    if data.startswith('cday:'):
        parts = data.split(':', 2)
        tariff_id = int(parts[1])
        from datetime import date

        day = date.fromisoformat(parts[2])
        t = Tariff.objects.filter(id=tariff_id, is_active=True).first()
        if not t:
            bc.send_message(str(chat_id), 'تعرفه نامعتبر یا غیرفعال.')
            return True
        # بنر الزامی قبل از افزودن به سبد
        order = get_or_create_draft(user)
        if not order.banner_message_id:
            bc.send_message(str(chat_id), 'اول بنر را از مرکز بنر انتخاب کنید.')
            show_banner_hub(chat_id, bale_user_id)
            return True
        result = add_to_cart(user, t, day)
        if not result.get('ok'):
            bc.send_message(str(chat_id), 'این نوبت در دسترس نیست.')
            show_days_for_tariff(chat_id, bale_user_id, tariff_id)
            return True
        order = result['order']
        kb = bc.inline_keyboard([
            [
                {'text': '➕ تعرفه دیگر', 'callback_data': 'cpage:0'},
                {'text': '🛒 سبد', 'callback_data': 'ccart'},
            ],
            [{'text': '✅ نهایی‌سازی سبد', 'callback_data': 'ccheck'}],
        ])
        bc.send_message(
            str(chat_id),
            f'به سبد اضافه شد ✅\n\n{cart_summary(order)}',
            reply_markup=kb,
        )
        return True

    return False


def try_handle_customer_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    norm = (text or '').strip()
    if norm in ('/banners', 'بنر', 'بنرها'):
        save_session(sess, STATE_CUST_BANNER_HUB, role='customer')
        show_banner_hub(chat_id, bale_user_id)
        return True
    if sess.state == STATE_CUST_BANNER:
        bc.send_message(
            str(chat_id),
            'لطفاً بنر را به‌صورت عکس/ویدیو بفرستید یا از لینک‌بانک بازارسال کنید.',
        )
        return True
    if sess.state == STATE_CUST_BANNER_HUB:
        bc.send_message(str(chat_id), 'از دکمه‌ها استفاده کنید یا /banners')
        return True
    if sess.state in (STATE_CUST_BROWSE, STATE_CUST_PICK_DAY):
        if norm in ('/cart', 'سبد'):
            handle_customer_callback(chat_id, bale_user_id, 'ccart')
            return True
        if norm in ('/catalog', 'فهرست'):
            show_catalog(chat_id, bale_user_id)
            return True
    return False
