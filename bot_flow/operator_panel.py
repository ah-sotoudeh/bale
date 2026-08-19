"""پنل اپراتور سامانه (لینک‌پخش)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from integrations import bale_client as bc
from orders.models import BannerPublishRequest, Order, OrderItem
from orders.publish import daily_admin_audit
from users.models import User
from wallet import services as ws


def _ensure(bale_user_id: str, username: str = '') -> User:
    from bot_flow.handlers import ensure_user

    return ensure_user(bale_user_id, username)


def main_keyboard() -> Dict[str, Any]:
    return bc.inline_keyboard([
        [
            {'text': '📁 فایل تسویه', 'callback_data': 'op:payout'},
            {'text': '🆕 درخواست بنر', 'callback_data': 'op:banners'},
        ],
        [
            {'text': '📋 سفارش‌های باز', 'callback_data': 'op:orders'},
            {'text': '🔎 چک ادمین کانال', 'callback_data': 'op:audit'},
        ],
        [
            {'text': '🛒 پنل مشتری', 'callback_data': 'cu:home'},
            {'text': '📢 پنل مدیر', 'callback_data': 'mgr:home'},
        ],
        [{'text': '🏠 منوی اصلی', 'callback_data': 'nav:start'}],
    ])


def open_panel(chat_id: str, bale_user_id: str, username: str = '') -> None:
    if not ws.is_operator(bale_user_id):
        bc.send_message(str(chat_id), 'این بخش فقط برای اپراتور سامانه است.')
        return
    user = _ensure(bale_user_id, username)
    pending_pay = ws.PayoutRequest.objects.filter(status='pending').count() if hasattr(ws, 'PayoutRequest') else 0
    from wallet.models import PayoutRequest

    pending_pay = PayoutRequest.objects.filter(status='pending').count()
    pending_banner = BannerPublishRequest.objects.filter(status='pending').count()
    open_orders = Order.objects.filter(
        status__in=('waiting_managers', 'waiting_payment', 'paid')
    ).count()
    text = (
        '🛠️ پنل اپراتور\n\n'
        f'آیدی: {user.bale_handle or user.bale_user_id}\n'
        f'درخواست تسویه باز: {pending_pay}\n'
        f'درخواست بنر باز: {pending_banner}\n'
        f'سفارش‌های فعال: {open_orders}\n\n'
        'یک بخش را انتخاب کنید:'
    )
    bc.send_message(str(chat_id), text, reply_markup=main_keyboard())


def show_pending_banners(chat_id: str) -> None:
    qs = list(
        BannerPublishRequest.objects.filter(status='pending')
        .select_related('customer')
        .order_by('id')[:20]
    )
    if not qs:
        bc.send_message(str(chat_id), 'درخواست بنر بازی نیست.', reply_markup=main_keyboard())
        return
    lines = ['🆕 درخواست‌های بنر در انتظار:']
    rows = []
    for r in qs:
        lines.append(
            f'#{r.id} مشتری {r.customer.bale_user_id} | '
            f'{"رایگان" if r.fee_toman == 0 else f"{r.fee_toman:,} ت"}'
        )
        rows.append([
            {'text': f'✅ تأیید #{r.id}', 'callback_data': f'bappr:{r.id}'},
            {'text': f'❌ رد #{r.id}', 'callback_data': f'brej:{r.id}'},
        ])
    rows.append([{'text': '🏠 پنل اپراتور', 'callback_data': 'op:home'}])
    bc.send_message(str(chat_id), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows))


def show_open_orders(chat_id: str) -> None:
    items = list(
        OrderItem.objects.filter(
            order__status__in=('waiting_managers', 'waiting_payment', 'paid')
        )
        .select_related('order', 'channel', 'tariff')
        .order_by('-id')[:25]
    )
    if not items:
        bc.send_message(str(chat_id), 'سفارش بازی نیست.', reply_markup=main_keyboard())
        return
    lines = ['📋 آیتم‌های فعال:']
    for it in items:
        lines.append(
            f'#{it.id} سفارش {it.order_id} | {it.manager_status}/{it.execution_status} | '
            f'{it.price:,} ت'
        )
    bc.send_message(str(chat_id), '\n'.join(lines)[:3900], reply_markup=main_keyboard())


def try_handle_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
    username: str = '',
) -> bool:
    if not data.startswith('op:') and data != 'nav:start':
        return False
    if cq_id:
        bc.answer_callback_query(str(cq_id))

    if data == 'nav:start':
        from bot_flow.handlers import handle_start

        handle_start(chat_id, bale_user_id, username)
        return True

    if not ws.is_operator(bale_user_id):
        bc.send_message(str(chat_id), 'دسترسی اپراتور ندارید.')
        return True

    user = _ensure(bale_user_id, username)

    if data in ('op:home', 'op:panel'):
        open_panel(chat_id, bale_user_id, username)
        return True
    if data == 'op:payout':
        from bot_flow.manager_panel import operator_payout_file

        operator_payout_file(chat_id, user)
        return True
    if data == 'op:banners':
        show_pending_banners(chat_id)
        return True
    if data == 'op:orders':
        show_open_orders(chat_id)
        return True
    if data == 'op:audit':
        r = daily_admin_audit()
        bc.send_message(str(chat_id), f'نتیجه چک ادمین:\n{r}', reply_markup=main_keyboard())
        return True
    return False
