"""متن‌های نمایش‌داده‌شده به کاربر — فقط این فایل را ویرایش کنید.

هیچ کلمهٔ انگلیسی برای کاربر ننویسید. اعداد با fa_num / fa_money.
"""
from __future__ import annotations

from typing import Any, Optional

_EN = '0123456789'
_FA = '۰۱۲۳۴۵۶۷۸۹'
_TRANS = str.maketrans(_EN, _FA)


def fa_num(value: Any) -> str:
    if value is None:
        return ''
    return str(value).translate(_TRANS)


def fa_money(amount: int | float, suffix: str = ' تومان') -> str:
    try:
        n = int(amount)
    except (TypeError, ValueError):
        return fa_num(amount) + suffix
    s = f'{n:,}'.replace(',', '٬')
    return fa_num(s) + suffix


ORDER_STATUS_FA = {
    'draft': 'پیش‌نویس',
    'waiting_managers': 'در انتظار تأیید مدیران',
    'waiting_customer_confirm': 'در انتظار تأیید شما',
    'waiting_payment': 'در انتظار پرداخت',
    'paid': 'پرداخت‌شده',
    'completed': 'تکمیل‌شده',
    'rejected': 'رد شده',
    'cancelled': 'لغو شده',
}

MANAGER_STATUS_FA = {
    'cart': 'در سبد',
    'pending': 'در انتظار تأیید',
    'approved': 'تأیید شده',
    'rejected': 'رد شده',
    'edited': 'زمان پیشنهادی جدید',
    'expired': 'منقضی‌شده',
    'customer_declined': 'رد زمان توسط مشتری',
}

EXEC_STATUS_FA = {
    'none': 'هنوز شروع نشده',
    'paid': 'آماده انتشار',
    'remind_sent': 'یادآوری ارسال شد',
    'awaiting_manager_publish': 'در انتظار انتشار',
    'awaiting_customer_confirm': 'در انتظار تأیید مشتری',
    'awaiting_operator': 'در بررسی پشتیبانی',
    'executed': 'اجرا شده',
    'failed_publish': 'انتشار ناموفق',
    'cancelled': 'لغو شده',
}

PUBLISH_MODE_FA = {
    'bot': 'ارسال خودکار با لینک‌ساز',
    'linkyar': 'ارسال خودکار با لینک‌یار',
    'manual': 'ارسال توسط خودتان',
}


def label_order_status(code: str) -> str:
    return ORDER_STATUS_FA.get(code or '', 'نامشخص')


def label_manager_status(code: str) -> str:
    return MANAGER_STATUS_FA.get(code or '', 'نامشخص')


def label_exec_status(code: str) -> str:
    return EXEC_STATUS_FA.get(code or '', 'نامشخص')


def label_publish_mode(code: str) -> str:
    return PUBLISH_MODE_FA.get(code or '', 'نامشخص')


def user_error(code: Optional[str]) -> str:
    mapping = {
        'not_found': 'مورد پیدا نشد.',
        'forbidden': 'دسترسی مجاز نیست.',
        'bad_status': 'این کار الان ممکن نیست.',
        'not_customer': 'این سفارش برای شما نیست.',
        'not_manager': 'شما مدیر این مورد نیستید.',
        'not_operator': 'فقط پشتیبانی می‌تواند این کار را انجام دهد.',
        'empty': 'اطلاعاتی وارد نشده است.',
        'invalid': 'مقدار نامعتبر است.',
        'no_tariffs': 'هنوز تعرفه‌ای ثبت نشده است.',
        'no_slots': 'در این بازه نوبت خالی نیست.',
        'timeout': 'مهلت پاسخ تمام شده است.',
        'publish_failed': 'انتشار انجام نشد. پشتیبانی در جریان است.',
        'payment_failed': 'پرداخت ثبت نشد. دوباره تلاش کنید.',
        'ERR': 'خطایی رخ داد.',
        'NO': 'انجام نشد.',
        'OK': 'انجام شد.',
    }
    if not code:
        return 'خطایی رخ داد.'
    return mapping.get(str(code), 'خطایی رخ داد. در صورت تکرار با پشتیبانی تماس بگیرید.')


# ── دکمه‌ها ──────────────────────────────────────────────
BTN_HOME = '🏠 خانه'
BTN_MAIN_MENU = '🔄 منوی اصلی'
BTN_BACK = '⬅️ بازگشت'
BTN_HELP = 'ℹ️ راهنما'
BTN_CANCEL = 'انصراف'
BTN_CONFIRM = '✅ تأیید'
BTN_REJECT = '❌ رد'
BTN_REFRESH = '🔄 به‌روزرسانی'
BTN_CUSTOMER_PANEL = '🛒 بخش مشتری'
BTN_MANAGER_PANEL = '📢 بخش مدیر کانال'
BTN_OPERATOR_PANEL = '🛠️ بخش پشتیبانی'
BTN_SWITCH_ROLE = '🔄 تغییر نقش'

BTN_MY_BANNERS = '🖼 بنرهای من'
BTN_NEW_BANNER = '➕ بنر جدید'
BTN_TARIFF_LIST = '📋 فهرست تعرفه‌ها'
BTN_CART = '🛒 سبد خرید'
BTN_MY_ORDERS = '📦 سفارش‌های من'
BTN_WALLET = '💰 کیف پول'
BTN_ADD_BANNER = '➕ افزودن بنر'
BTN_USE_BANNER = '✅ انتخاب برای سفارش'
BTN_RENAME_BANNER = '✏️ تغییر نام'
BTN_EDIT_CAPTION = '📝 ویرایش متن'
BTN_DELETE_BANNER = '🗑 حذف بنر'
BTN_CHECKOUT = '✅ ثبت نهایی سفارش'
BTN_MORE_TARIFFS = 'تعرفهٔ دیگر'
BTN_PICK_DAY = '📅 انتخاب روز'

BTN_CHANNELS = '📢 کانال‌ها'
BTN_TARIFFS = '💳 تعرفه‌ها'
BTN_ORDERS = '📋 سفارش‌ها'
BTN_CALENDAR = '📅 تقویم و نوبت'
BTN_FINANCE = '💰 مالی'
BTN_PUBLISH_MODE = '⚙️ نحوهٔ ارسال'
BTN_ADD_CHANNEL = '➕ ثبت کانال'
BTN_EDIT_TARIFF = '✏️ ویرایش تعرفه'
BTN_DEACTIVATE = '⏸ غیرفعال'
BTN_ACTIVATE = '✅ فعال‌سازی'
BTN_DELETE = '🗑 حذف'
BTN_TARIFF_LIST_BACK = '⬅️ فهرست تعرفه‌ها'
BTN_ADD_IBAN = '➕ افزودن شبا'
BTN_REQUEST_PAYOUT = '💸 درخواست تسویه'
BTN_MARK_BUSY = '🔒 ثبت روز پر'
BTN_CLEAR_BUSY = '🗑 حذف نوبت دستی'
BTN_BACK_CALENDAR = '⬅️ بازگشت به تقویم'
BTN_PUBLISHED = '✅ منتشر شد'

BTN_PAYOUT_FILE = '📁 فایل تسویه'
BTN_BANNER_REQUESTS = '🆕 درخواست بنر'
BTN_OPEN_ORDERS = '📋 سفارش‌های باز'
BTN_ADMIN_CHECK = '🔎 بررسی ادمین کانال‌ها'
BTN_MARK_PAID = '✅ پرداخت انجام شد'
BTN_EXEC_OK = '✅ اجرا شده'
BTN_EXEC_NO = '❌ اجرا نشده'

BTN_MODE_BOT = 'ارسال خودکار با لینک‌ساز'
BTN_MODE_LINKYAR = 'ارسال خودکار با لینک‌یار'
BTN_MODE_MANUAL = 'ارسال توسط خودم'

# ── پیام‌ها ──────────────────────────────────────────────
MSG_START_WELCOME = (
    'سلام 👋\n'
    'به سامانهٔ تبلیغات لینک‌بانک خوش آمدید.\n\n'
    'شناسه شما: {handle}\n\n'
    'لطفاً نقش خود را انتخاب کنید:'
)

MSG_HELP = (
    'راهنما\n\n'
    '• مشتری: بنر را ثبت کنید، تعرفه و روز را انتخاب کنید و سفارش را نهایی کنید.\n'
    '• مدیر کانال: کانال و تعرفه را ثبت کنید، سفارش‌ها را بررسی کنید و تقویم را مدیریت کنید.\n'
    '• پشتیبانی: تسویه حساب و بررسی موارد ویژه.\n\n'
    'از دکمه‌های منو استفاده کنید.'
)

MSG_CB_OK = 'انجام شد'
MSG_CB_SAVED = 'ثبت شد'
MSG_CB_DONE = 'انجام شد'
MSG_CB_FAILED = 'انجام نشد'
MSG_USE_BUTTONS = 'لطفاً از دکمه‌های منو استفاده کنید.'
MSG_INVALID = 'مقدار نامعتبر است. دوباره تلاش کنید.'
MSG_NOT_FOUND = 'مورد پیدا نشد.'
MSG_FORBIDDEN = 'دسترسی به این بخش مجاز نیست.'

MSG_TARIFF_HELP = (
    'هر خط یک تعرفه، با این ترتیب:\n\n'
    'نام | ساعت ارسال | مدت ماندگاری (ساعت) | قیمت (تومان)\n\n'
    'مثال:\n'
    'طرح عادی | ۱۰ | ۲۴ | ۲۰۰۰۰۰'
)

MSG_TARIFF_SAVED = '✅ تعرفه ذخیره شد: {name} — ساعت {hour} | {duration} ساعت | {price}'
MSG_TARIFF_DELETED = '🗑 تعرفه «{name}» حذف شد.'
MSG_TARIFF_UPDATED = '✅ تعرفه «{name}» به‌روز شد.'
MSG_TARIFF_INVALID = 'فرمت تعرفه درست نیست.\n\n{help}'
MSG_BUSY_MARKED = '🔒 روز {date} برای «{target}» پر ثبت شد.'
MSG_BUSY_CLEARED = '✅ نوبت دستی روز {date} برای «{target}» برداشته شد.'
MSG_NO_ORDERS = 'سفارشی برای نمایش نیست.'
MSG_ORDERS_HEADER = '📋 سفارش‌های اخیر:'

MSG_CUSTOMER_HOME = (
    '🛒 بخش مشتری\n\n'
    'شناسه: {handle}\n'
    'بنرهای فعال: {banners}\n'
    'اقلام سبد: {cart}\n'
    'سفارش در جریان: {open_orders}\n'
    'موجودی کیف پول: {balance}\n\n'
    'یک گزینه را انتخاب کنید:'
)

MSG_BANNERS_HEADER = (
    '🖼 بنرهای من\n'
    'کانال مرجع بنر: {ref}\n\n'
    'برای مدیریت، روی بنر بزنید.'
)
MSG_BANNERS_EMPTY = (
    'هنوز بنری ندارید.\n'
    'بنر را از کانال مرجع بازارسال کنید یا بنر جدید بفرستید.'
)
MSG_BANNER_PROMPT = (
    'بنر تبلیغاتی را بفرستید.\n\n'
    '• اگر قبلاً در کانال مرجع ({ref}) منتشر شده، همان را به اینجا بازارسال کنید.\n'
    '• در غیر این صورت عکس یا ویدیو همراه متن بفرستید.\n\n'
    'لطفاً دقیقاً همان بنری را بفرستید که می‌خواهید منتشر شود.'
)
MSG_BANNER_SAVED = '✅ بنر «{title}» ذخیره و برای سفارش انتخاب شد.'
MSG_BANNER_SELECTED = '✅ بنر «{title}» انتخاب شد.\nاکنون فهرست تعرفه‌ها را ببینید.'
MSG_BANNER_DELETED = '🗑 «{title}» حذف شد.'
MSG_BANNER_RENAMED = '✅ نام بنر به «{title}» تغییر کرد.'
MSG_BANNER_NAME_PROMPT = 'یک نام کوتاه برای این بنر بفرستید:'
MSG_BANNER_CAPTION_PROMPT = 'متن جدید بنر را بفرستید (فقط متن؛ تصویر یا ویدیو قابل تغییر نیست):'
MSG_BANNER_NOT_FROM_REF = (
    'این بنر از کانال مرجع ({ref}) نیست.\n'
    'در صورت تمایل می‌توانید درخواست بررسی برای انتشار در کانال مرجع ثبت کنید.'
)
MSG_BANNER_REVIEW_SENT = (
    '📨 درخواست بررسی بنر ثبت شد.\n'
    'هزینه اعلامی انتشار در کانال مرجع: {fee}'
)
MSG_BANNER_FEE_NOTE = 'هزینه بنر بعدی در کانال مرجع (اعلامی): {fee}'

MSG_CATALOG_HEADER = '📋 فهرست تعرفه‌ها — صفحه {page}'
MSG_NO_FREE_DAYS = 'برای «{owner} — {tariff}» در این بازه نوبت خالی نیست.'
MSG_PICK_DAY_HEADER = '📅 روزهای خالی\n{owner} — {tariff} — {price}'
MSG_CART_ADDED = '➕ به سبد اضافه شد.\n\n{summary}'
MSG_CHECKOUT_OK = '✅ سفارش شماره {order_id} با {count} قلم ثبت شد و برای مدیران ارسال شد.'
MSG_ORDER_LINE = 'شماره {id} | {status} | {count} قلم | {amount}'

MSG_MANAGER_HOME = (
    '🎛️ بخش مدیر کانال\n\n'
    'شناسه: {handle}\n'
    'کانال‌ها: {channels}\n'
    'سفارش در انتظار: {pending}\n'
    'موجودی قابل برداشت: {balance}\n\n'
    'یک گزینه را انتخاب کنید:'
)

# —— نحوهٔ ارسال (نسخه نهایی برای مدیر) ——
MSG_PUBLISH_MODE_TITLE = 'نحوهٔ ارسال تبلیغ در «{channel}»'
MSG_PUBLISH_MODE_CURRENT = 'روش فعلی: {label}'

MSG_PUBLISH_MODE_HELP = (
    'چطور می‌خواهید تبلیغ در این کانال ارسال شود؟\n\n'
    '۱) ارسال خودکار با لینک‌ساز (پیشنهادی)\n'
    'ربات لینک‌ساز را در کانال ادمین کنید. در زمان مقرر، بنر به‌صورت خودکار ارسال می‌شود.\n\n'
    '۲) ارسال خودکار با لینک‌یار\n'
    'اگر امکان افزودن ربات به کانال را ندارید، حساب لینک‌یار را ادمین کنید تا ارسال خودکار انجام شود.\n\n'
    '۳) ارسال توسط خودتان\n'
    'بنر را خودتان در کانال می‌فرستید. قبل از موعد، به شما یادآوری می‌کنیم.'
)

MSG_PUBLISH_MODE_SET = '✅ نحوهٔ ارسال روی «{label}» تنظیم شد.'
MSG_PUBLISH_MODE_HINT_BOT = '\nلطفاً ربات لینک‌ساز را در کانال ادمین کنید.'
MSG_PUBLISH_MODE_HINT_LINKYAR = '\nلطفاً حساب لینک‌یار را در کانال ادمین کنید.'
MSG_REMIND_HOURS_ASK = 'چند ساعت قبل از موعد تبلیغ به شما یادآوری شود؟'

MSG_CHANNEL_LINKS_PROMPT = (
    'ثبت کانال\n\n'
    'لینک کانال‌ها را بفرستید (هر خط یک کانال).\n'
    '• یک لینک = تک‌کانال\n'
    '• چند لینک = مجموعه با تعرفهٔ مشترک\n\n'
    'شناسه شما باید در بیوی کانال باشد: {proof}'
)
MSG_GROUP_NAME_PROMPT = 'نام مجموعه را بفرستید:'
MSG_CALENDAR_PICK_TARIFF = 'تعرفه را برای مشاهدهٔ تقویم انتخاب کنید:'
MSG_REMIND_PUBLISH = (
    '⏰ یادآوری ارسال تبلیغ\n'
    'سفارش شماره {item_id} — {owner}\n'
    'زمان: {when}\n\n'
    'پس از ارسال بنر در کانال، دکمهٔ «منتشر شد» را بزنید.'
)

MSG_PAYOUT_BATCH_HEADER = '📁 فایل تسویه شماره {id} — {count} درخواست\nمبالغ به ریال:'
MSG_PAYOUT_AFTER_BANK = 'پس از واریز بانک، دکمهٔ «پرداخت انجام شد» را بزنید.'
MSG_PAYOUT_MARKED = '✅ پرداخت این دسته ثبت شد و به مدیران اطلاع داده شد.'
MSG_PAYOUT_PAID_USER = '✅ مبلغ {amount} به‌صورت پایا به حساب شما واریز شد.'
MSG_WALLET_CREDITED = 'مبلغ {amount} بابت سفارش شماره {item_id} به کیف پول شما برگشت.'
MSG_EXEC_DONE_CUSTOMER = '✅ تبلیغ شما اجرا شد.\n{link}'
MSG_EXEC_DONE_MANAGER = '✅ سفارش شماره {item_id} اجرا شد. اعتبار کیف پول: {net} (پس از کارمزد).'
MSG_EXEC_FAILED_MANAGER = 'سفارش شماره {item_id} منتشر نشده ثبت شد. جریمه: {penalty}'
MSG_OPERATOR_REVIEW = (
    '🔎 بررسی انتشار\n'
    'جزء شماره {item_id} | سفارش {order_id}\n'
    'هدف: {owner}\n'
    'پیوند: {link}\n'
    'مبلغ: {price}'
)
MSG_PAYMENT_REQUEST = (
    'همه مدیران تأیید کردند.\n'
    'مبلغ قابل پرداخت: {amount}\n\n'
    'لطفاً پرداخت را تکمیل کنید.'
)
MSG_ORDER_PAID = 'سفارش شماره {order_id} پرداخت شد و در زمان مقرر منتشر می‌شود.'
MSG_ORDER_REJECTED = 'متأسفیم؛ یکی از کانال‌ها سفارش شما را نپذیرفت. سفارش شماره {order_id} رد شد.'
MSG_PUBLISH_OK_CUSTOMER = '✅ بنر شما در «{channel}» منتشر شد.\n🔗 {link}'
MSG_PUBLISH_FAIL_CHANNEL = '❌ ارسال سفارش شماره {item_id} در «{channel}» ناموفق بود. پشتیبانی مطلع شد.'
MSG_TARIFF_DEACTIVATED = (
    '⚠️ تعرفه(های) «{channel}» موقتاً از فهرست خارج شد.\n'
    'علت: لینک‌یار یا لینک‌ساز دیگر ادمین این کانال نیست. پس از رفع، به پشتیبانی اطلاع دهید.'
)


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
        f'شماره {fa_num(item_id)} | سفارش {fa_num(order_id)} | {owner}\n'
        f'  وضعیت مدیر: {label_manager_status(manager_status)} | '
        f'اجرا: {label_exec_status(exec_status)}\n'
        f'  {date_fa} | {fa_money(price)}'
    )


def format_order_line_customer(order_id: int, status: str, count: int, amount: int) -> str:
    return MSG_ORDER_LINE.format(
        id=fa_num(order_id),
        status=label_order_status(status),
        count=fa_num(count),
        amount=fa_money(amount),
    )


def format_publish_mode_screen(channel_name: str, mode_code: str) -> str:
    """متن کامل صفحهٔ انتخاب نحوهٔ ارسال برای یک کانال."""
    lines = [
        MSG_PUBLISH_MODE_TITLE.format(channel=channel_name),
        MSG_PUBLISH_MODE_CURRENT.format(label=label_publish_mode(mode_code)),
        '',
        MSG_PUBLISH_MODE_HELP,
    ]
    return '\n'.join(lines)
