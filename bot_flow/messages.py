"""متن‌های نمایش‌داده‌شده به کاربر — ویرایش فقط از این فایل.

قانون: هیچ رشتهٔ انگلیسی وضعیت/خطا مستقیماً به کاربر نرود؛ از برچسب‌های این فایل استفاده شود.
اعداد با fa_num / fa_money فارسی شوند.
"""
from __future__ import annotations

from typing import Any, Optional

# ── ارقام فارسی ──────────────────────────────────────────
_EN = '0123456789'
_FA = '۰۱۲۳۴۵۶۷۸۹'
_TRANS = str.maketrans(_EN, _FA)


def fa_num(value: Any) -> str:
    """هر عدد یا رشتهٔ شامل رقم را با ارقام فارسی برمی‌گرداند."""
    if value is None:
        return ''
    return str(value).translate(_TRANS)


def fa_money(amount: int | float, suffix: str = ' تومان') -> str:
    try:
        n = int(amount)
    except (TypeError, ValueError):
        return fa_num(amount) + suffix
    # جداکننده هزارگان با ویرگول فارسی‌نما
    s = f'{n:,}'.replace(',', '٬')
    return fa_num(s) + suffix


# ── وضعیت سفارش (Order.status) ───────────────────────────
ORDER_STATUS_FA = {
    'draft': 'پیش‌نویس',
    'waiting_managers': 'در انتظار مدیران',
    'waiting_customer_confirm': 'در انتظار تأیید مشتری',
    'waiting_payment': 'در انتظار پرداخت',
    'paid': 'پرداخت‌شده',
    'completed': 'تکمیل‌شده',
    'rejected': 'رد شده',
    'cancelled': 'لغو شده',
}

# ── وضعیت پاسخ مدیر (OrderItem.manager_status) ───────────
MANAGER_STATUS_FA = {
    'cart': 'سبد',
    'pending': 'در انتظار',
    'approved': 'تأیید شده',
    'rejected': 'رد شده',
    'edited': 'زمان پیشنهادی',
    'expired': 'منقضی',
    'customer_declined': 'رد زمان توسط مشتری',
}

# ── وضعیت اجرا (OrderItem.execution_status) ──────────────
EXEC_STATUS_FA = {
    'none': 'هنوز شروع نشده',
    'paid': 'آماده انتشار',
    'remind_sent': 'یادآوری ارسال شد',
    'awaiting_manager_publish': 'در انتظار انتشار مدیر',
    'awaiting_customer_confirm': 'در انتظار تأیید مشتری',
    'awaiting_operator': 'در انتظار اپراتور',
    'executed': 'اجرا شده',
    'failed_publish': 'انتشار ناموفق',
    'cancelled': 'لغو شده',
}


def label_order_status(code: str) -> str:
    return ORDER_STATUS_FA.get(code or '', code or '—')


def label_manager_status(code: str) -> str:
    return MANAGER_STATUS_FA.get(code or '', code or '—')


def label_exec_status(code: str) -> str:
    return EXEC_STATUS_FA.get(code or '', code or '—')


# ── پیام‌های عمومی ───────────────────────────────────────
MSG_START_WELCOME = (
    'سلام 👋\n'
    'به سامانه تبلیغات لینک‌بانک خوش آمدید.\n\n'
    'آیدی شما: {handle}\n\n'
    'یک پنل را باز کنید:'
)

MSG_HELP = (
    'راهنما:\n'
    '• مشتری: بنر ← فهرست ← سبد ← پرداخت\n'
    '• مدیر: کانال / تعرفه / تقویم / مالی\n'
    '• اپراتور: تسویه و تأیید بنر\n\n'
    '/start منوی اصلی\n'
    '/customer پنل مشتری\n'
    '/panel پنل مدیر'
)

MSG_TARIFF_HELP = (
    'نام | ساعت_ارسال | مدت_ساعت | قیمت_تومان\n'
    'مثال: طرح عادی | ۱۰ | ۲۴ | ۲۰۰\n'
    'یا: طرح عادی | ساعت ۱۰ | ۲۴ ساعت | ۲۰۰ تومن'
)

MSG_TARIFF_SAVED = '✅ تعرفه ذخیره شد: {name} — ارسال {hour} | {duration} ساعت | {price}'
MSG_TARIFF_DELETED = '🗑 تعرفه «{name}» حذف شد.'
MSG_TARIFF_UPDATED = '✅ تعرفه «{name}» به‌روز شد.'
MSG_BUSY_MARKED = '🔒 روز {date} برای «{target}» پر ثبت شد.'
MSG_NO_ORDERS = 'سفارشی نیست.'
MSG_ORDERS_HEADER = '📋 سفارش‌های اخیر:'

# قالب یک خط سفارش برای مدیر
def format_manager_order_line(
    item_id: int,
    order_id: int,
    owner: str,
    manager_status: str,
    exec_status: str,
    date_fa: str,
    price: int,
) -> str:
    return (
        f'#{fa_num(item_id)} | سفارش {fa_num(order_id)} | {owner}\n'
        f'  مدیر: {label_manager_status(manager_status)} | '
        f'اجرا: {label_exec_status(exec_status)}\n'
        f'  {date_fa} | {fa_money(price)}'
    )
