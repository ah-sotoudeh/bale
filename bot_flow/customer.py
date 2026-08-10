"""Customer-side conversation: banner → فهرست → cart → checkout."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from bot_flow.banned_words import is_allowed
from bot_flow.handlers import ensure_user, get_session, save_session
from bot_flow.jalali import format_jalali
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
from orders.models import Order

logger = logging.getLogger(__name__)

STATE_CUST_BANNER = 'cust_await_banner'
STATE_CUST_BROWSE = 'cust_browse'
STATE_CUST_PICK_DAY = 'cust_pick_day'


def start_customer(chat_id: str, bale_user_id: str, username: str = '') -> None:
    ensure_user(bale_user_id, username)
    sess = get_session(bale_user_id)
    save_session(sess, STATE_CUST_BANNER, role='customer', cart_tariff_id=None)
    bc.send_message(
        str(chat_id),
        'شما مشتری هستید ✅\n\n'
        'لطفاً **بنر تبلیغ** را بفرستید:\n'
        '• عکس + توضیح، یا\n'
        '• ویدیو + توضیح\n\n'
        'یک بنر برای کل سبد استفاده می‌شود.\n'
        'دقیقاً همان بنری که باید منتشر شود را بفرستید.\n'
        'بنر جدید = سفارش جدید از اول.',
    )


def handle_banner_message(
    chat_id: str,
    bale_user_id: str,
    message: dict,
) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_CUST_BANNER:
        return False

    caption = message.get('caption') or message.get('text') or ''
    has_media = bool(message.get('photo') or message.get('video') or message.get('document'))
    if not has_media and not caption:
        bc.send_message(str(chat_id), 'بنر باید شامل تصویر یا ویدیو باشد.')
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
    Order.objects.filter(customer=user, status='draft').delete()
    order = get_or_create_draft(user)
    msg_id = message.get('message_id')
    set_banner(order, str(chat_id), str(msg_id), caption)

    save_session(sess, STATE_CUST_BROWSE, role='customer')
    bc.send_message(str(chat_id), 'بنر پذیرفته شد ✅')
    show_catalog(chat_id, bale_user_id)
    return True


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
            'ممکن است مدیران هنوز کانال ثبت نکرده باشند یا لینک‌یار ادمین نباشد.',
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
        {'text': '✅ نهایی‌سازی', 'callback_data': 'ccheck'},
    ])

    bc.send_message(
        str(chat_id),
        f'فهرست تعرفه‌ها (صفحه {page + 1})\n'
        'یک تعرفه را انتخاب کنید تا روزهای خالی را ببینید:',
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
    if not data.startswith(('ctar:', 'cday:', 'cpage:', 'ccart', 'ccheck', 'custok:', 'custno:')):
        return False

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='…')

    user = ensure_user(bale_user_id)

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
            ]
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
                'no_banner': 'اول بنر بفرستید. /start',
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
    if sess.state == STATE_CUST_BANNER:
        bc.send_message(str(chat_id), 'لطفاً بنر را به‌صورت عکس یا ویدیو بفرستید.')
        return True
    if sess.state in (STATE_CUST_BROWSE, STATE_CUST_PICK_DAY):
        if text.strip() in ('/cart', 'سبد'):
            handle_customer_callback(chat_id, bale_user_id, 'ccart')
            return True
        if text.strip() in ('/catalog', 'فهرست', 'کاتالوگ'):
            show_catalog(chat_id, bale_user_id)
            return True
    return False
