"""متن‌های نمایش‌داده‌شده به کاربر — فقط این فایل را ویرایش کنید.

هیچ کلمهٔ انگلیسی برای کاربر ننویسید. اعداد با fa_num / fa_money.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_EN = '0123456789'
_FA = '۰۱۲۳۴۵۶۷۸۹'
_TRANS = str.maketrans(_EN, _FA)


def parse_user_int(value: Any) -> Optional[int]:
    """عدد انگلیسی یا فارسی، با جداکنندهٔ هزارگان. قیمت ۲۰۰٬۰۰۰ همان ۲۰۰۰۰۰ می‌ماند."""
    raw = str(value or '').translate(str.maketrans(_FA, _EN))
    raw = raw.replace('٬', '').replace(',', '').replace(' ', '')
    match = re.search(r'(\d{1,12})', raw)
    if not match:
        return None
    return int(match.group(1))


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
    'waiting_managers': 'در انتظار پاسخ کانال‌دار',
    'waiting_customer_confirm': 'در انتظار تأیید شما',
    'waiting_payment': 'در انتظار پرداخت',
    'paid': 'پرداخت‌شده',
    'completed': 'تکمیل‌شده',
    'rejected': 'رد شده',
    'cancelled': 'لغو شده',
}

MANAGER_STATUS_FA = {
    'cart': 'انتخاب شده',
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
    'executed': 'منتشر شد',
    'failed_publish': 'منتشر نشد',
    'cancelled': 'لغو شده',
}

PUBLISH_MODE_FA = {
    'bot': 'انتشار خودکار با بازوی لینک‌بان',
    'linkyar': 'انتشار خودکار با حساب دستیار',
    'manual': 'انتشار دستی توسط شما',
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
        'not_found': 'این مورد را پیدا نکردم. یک بار دیگر از فهرست انتخاب کنید.',
        'item_not_found': 'این نوبت را پیدا نکردم.',
        'order_not_found': 'این سفارش را پیدا نکردم.',
        'forbidden': 'این کار برای شما نیست.',
        'bad_status': 'این کار الان ممکن نیست. وضعیت را در سفارش‌ها ببینید.',
        'not_customer': 'این سفارش برای شما نیست.',
        'not_manager': 'شما کانال‌دار این کانال نیستید.',
        'not_item_manager': 'فقط کانال‌دار همین کانال می‌تواند جواب بدهد.',
        'manager_not_found': 'اول از بخش کانال‌دار وارد شوید.',
        'already_handled': 'به این نوبت قبلاً جواب داده‌اید.',
        'slot_conflict': 'این روز پر است. روز دیگری را انتخاب کنید.',
        'need_new_start': 'تاریخ تازه را بفرستید.',
        'invalid_action': 'این دکمه را نمی‌شناسم.',
        'not_awaiting': 'زمانی برای تأیید شما باقی نمانده.',
        'not_operator': 'فقط پشتیبانی می‌تواند این کار را انجام دهد.',
        'bad_fields': 'نام، مدت و قیمت را درست بنویسید.',
        'bad_date': 'این تاریخ درست نیست. یک بار دیگر بفرستید.',
        'bad_mode': 'این روش انتشار را نمی‌شناسم.',
        'need_date': 'تاریخ را انتخاب کنید.',
        'target_required': 'کانال یا مجموعه را انتخاب کنید.',
        'channel_not_found': 'کانال را پیدا نکردم.',
        'bank_not_found': 'این حساب را پیدا نکردم.',
        'invalid_iban': 'شماره شبا درست نیست. یک بار دیگر بفرستید.',
        'need_holder_name': 'نام صاحب حساب را بفرستید.',
        'inactive_tariff': 'این تعرفه خاموش است و روزش فروخته نمی‌شود.',
        'empty_cart': 'هنوز روزی انتخاب نکرده‌اید.',
        'no_banner': 'اول یک بنر بیاورید. تا وقتی بنری نداشته باشید، نمی‌توانید روزی را انتخاب کنید.',
        'not_cancellable': 'این سفارش الان بسته نمی‌شود. اگر منتشر شده، اعتراض ثبت کنید.',
        'too_late': 'از ۲ ساعت پیش از انتشار دیگر لغو نمی‌شود. اگر مشکلی هست، اعتراض ثبت کنید.',
        'past': 'این ساعت گذشته است. روز دیگری را انتخاب کنید.',
        'not_pending': 'این سفارش دیگر در انتظار شما نیست.',
        'already_pending': 'یک درخواست تسویه باز دارید. بعد از واریز همان، دوباره درخواست بدهید.',
        'weekly_limit': 'از تسویهٔ قبلی هنوز یک هفته نگذشته. بعد از آن دوباره درخواست بدهید.',
        'below_minimum': 'مبلغ از حداقل تسویه کمتر است. وقتی اعتبارتان رسید، دوباره درخواست بدهید.',
        'no_bank': 'اول شماره شبا را ثبت کنید.',
        'insufficient': 'موجودی برای این تسویه کافی نیست.',
        'already_paid': 'این سفارش قبلاً پرداخت شده. نیازی به پرداخت دوباره نیست.',
        'not_waiting_payment': 'این سفارش الان قابل پرداخت نیست. وضعیت را در سفارش‌ها ببینید.',
        'bad_amount': 'مبلغ درست نیست. یک بار دیگر بررسی کنید.',
        'part_paid': 'این بخش قبلاً پرداخت شده. بخش بعدی را بپردازید.',
        'amount_mismatch': 'مبلغ این فاکتور با سفارش یکی نیست.',
        'not_found_in_history': 'بنر را در تاریخچه کانال پیدا نکردم. اول پست را در کانال بفرستید.',
        'no_channel': 'کانال این نوبت مشخص نیست.',
        'unauthorized': 'نشست بله تأیید نشد. لینک‌بان را از داخل گفتگوی بله باز کنید.',
        'empty_init_data': 'لینک‌بان را از داخل گفتگوی بله باز کنید.',
        'bad_hash': 'نشست بله معتبر نیست. دوباره از گفتگو باز کنید.',
        'expired': 'نشست بله منقضی شده. دوباره از گفتگو باز کنید.',
        'no_user': 'حساب بله‌تان را نشناختم. لینک‌بان را از داخل گفتگو دوباره باز کنید.',
        'empty': 'چیزی نفرستادید.',
        'invalid': 'این مقدار را نشناختم. یک بار دیگر بفرستید.',
        'no_tariffs': 'هنوز تعرفه‌ای ثبت نکرده‌اید.',
        'no_slots': 'در این بازه روز خالی نیست.',
        'timeout': 'مهلت پاسخ تمام شده.',
        'publish_failed': 'انتشار انجام نشد. پشتیبانی در جریان است.',
        'payment_failed': 'پرداخت ثبت نشد. دوباره تلاش کنید.',
        'ERR': 'یک اشکال پیش آمد. یک بار دیگر تلاش کنید.',
        'NO': 'انجام نشد. یک بار دیگر تلاش کنید.',
        'OK': 'انجام شد.',
        'bad_theme': 'این ظاهر را نمی‌شناسم. روشن یا تیره را انتخاب کنید.',
        'use_bot': 'درخواست تسویه را در گفتگو با لینک‌بان بسازید. اینجا فقط بعد از واریز بانک تأیید می‌شود.',
        'invalid_new_start': 'تاریخ تازه درست نیست. روز دیگری را انتخاب کنید.',
        'not_paid': 'این سفارش هنوز پرداخت نشده. فقط سفارش پرداخت‌شده به اعتبار برمی‌گردد.',
        'already_refunded': 'مبلغ این سفارش قبلاً به اعتبار برگشته.',
        'inactive': 'این تعرفه خاموش است. یک تعرفهٔ روشن را انتخاب کنید.',
        'no_pending': 'درخواست تسویه‌ای برای واریز نیست. وقتی درخواستی باز شد، دوباره بزنید.',
        'batch_not_found': 'این فهرست تسویه را پیدا نکردم. یک بار دیگر از اول بسازید.',
        'banned': 'این متن مجاز نیست. عبارت را عوض کنید و دوباره بفرستید.',
        'bot_token_missing': 'لینک‌بان الان در دسترس نیست. کمی بعد از گفتگوی بله دوباره باز کنید.',
        'missing_hash': 'نشست بله کامل نیست. لینک‌بان را از داخل گفتگو باز کنید.',
        'bad_auth_date': 'زمان نشست بله درست نیست. دوباره از گفتگو باز کنید.',
        'bad_user_json': 'حساب بله خوانده نشد. لینک‌بان را از داخل گفتگو باز کنید.',
        'bad_banner_id': 'این بنر را پیدا نکردم. یک بنر دیگر انتخاب کنید.',
        'ref_publish_failed': 'ثبت بنر در کانال بنرها انجام نشد. به پشتیبانی بگویید.',
        'ref_no_message_id': 'بنر در کانال بنرها ثبت نشد. کمی بعد دوباره تلاش کنید.',
    }
    if not code:
        return 'یک اشکال پیش آمد. یک بار دیگر تلاش کنید.'
    return mapping.get(str(code), 'یک اشکال پیش آمد. اگر تکرار شد به پشتیبانی بگویید.')


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
BTN_MANAGER_PANEL = '📢 بخش کانال‌دار'
BTN_OPERATOR_PANEL = '🛠️ بخش پشتیبانی'
BTN_SWITCH_ROLE = '🔄 تغییر نقش'

BTN_MY_BANNERS = '🖼 بنرهای من'
BTN_NEW_BANNER = '➕ بنر جدید'
BTN_TARIFF_LIST = '📋 فهرست تعرفه‌ها'
BTN_CART = '🛒 انتخاب‌ها'
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
BTN_ADMIN_CHECK = '🔎 بررسی کانال‌ها'
BTN_MARK_PAID = '✅ پرداخت انجام شد'
BTN_EXEC_OK = '✅ منتشر شد'
BTN_EXEC_NO = '❌ اجرا نشده'

BTN_MODE_BOT = 'انتشار خودکار با بازوی لینک‌بان'
BTN_MODE_LINKYAR = 'انتشار خودکار با حساب دستیار'
BTN_MODE_MANUAL = 'انتشار دستی توسط شما'

# ── پیام‌ها ──────────────────────────────────────────────
MSG_START_WELCOME = (
    'سلام، به لینک‌بان خوش آمدید.\n'
    'تبلیغ کانال‌های بله را از اینجا سفارش می‌دهید، یا برای کانالتان تبلیغ می‌گیرید. '
    'پول هر سفارش تا پایان کار در امانت می‌ماند.\n\n'
    'یکی از دکمه‌ها را بزنید.\n'
    'نام شما در بله: {handle}'
)

MSG_HELP = (
    'راهنمای لینک‌بان\n'
    'مشتری هستید؟ اول بنر را همین‌جا بفرستید؛ عکس یا ویدیو با متنش.\n'
    'کانال‌دار هستید؟ از منوی پایین، بخش کانال‌دار را باز کنید.\n'
    'پرداخت بعد از قبول کانال، با کیف پول بله است. تا آن موقع پولی کم نمی‌شود.\n'
    'اگر تبلیغ انجام نشود، پول به اعتبارتان برمی‌گردد.'
)

MSG_CB_OK = 'انجام شد'
MSG_CB_SAVED = 'ثبت شد'
MSG_CB_DONE = 'انجام شد'
MSG_CB_FAILED = 'انجام نشد'
MSG_USE_BUTTONS = 'از دکمه‌های منو یکی را بزنید.'
MSG_INVALID = 'این مقدار را نشناختم. یک بار دیگر بفرستید.'
MSG_NOT_FOUND = 'این مورد را پیدا نکردم.'
MSG_FORBIDDEN = 'این بخش برای شما نیست.'

MSG_TARIFF_HELP = (
    'یک خط بفرستید، با همین ترتیب:\n\n'
    'نام | ساعت ارسال | مدت ماندگاری به ساعت | قیمت به تومان\n\n'
    'مثال:\n'
    'طرح عادی | ۱۰ | ۲۴ | ۲۰۰۰۰۰'
)

MSG_TARIFF_SAVED = '✅ تعرفه ذخیره شد: {name} — ساعت {hour} | {duration} ساعت | {price}'
MSG_TARIFF_DELETED = '🗑 تعرفه «{name}» حذف شد.'
MSG_TARIFF_UPDATED = '✅ تعرفه «{name}» به‌روز شد.'
MSG_TARIFF_INVALID = 'این خط را به‌صورت تعرفه نفهمیدم.\n\n{help}'
MSG_BUSY_MARKED = '🔒 روز {date} برای «{target}» پر شد.'
MSG_BUSY_CLEARED = '✅ نوبت دستی روز {date} برای «{target}» برداشته شد.'
MSG_NO_ORDERS = 'هنوز سفارشی نرسیده. وقتی کسی روزی را بردارد، همین‌جا جواب می‌دهید.'
MSG_ORDERS_HEADER = '📋 سفارش‌های اخیر:'

MSG_CUSTOMER_HOME = (
    'بخش مشتری\n\n'
    'نام شما در بله: {handle}\n'
    'بنر آماده: {banners}\n'
    'روز انتخاب‌شده: {cart}\n'
    'سفارش باز: {open_orders}\n'
    'اعتبار: {balance}\n\n'
    'اول بنر را بفرستید، بعد یک روز خالی بردارید.'
)

MSG_BANNERS_HEADER = (
    '🖼 بنرهای من\n'
    'کانال بنرها: {ref}\n\n'
    'روی یک بنر بزنید.'
)
MSG_BANNERS_EMPTY = (
    'هنوز بنری ندارید.\n'
    'دکمهٔ «افزودن بنر» را بزنید.'
)
MSG_BANNER_PROMPT = (
    'بنر را بفرستید: عکس یا ویدیو، و متن را زیر همان عکس بنویسید.\n'
    'اگر بنر از قبل در کانال بنرها ({ref}) هست، همان پست را بازارسال کنید.'
)
MSG_BANNER_SAVED = '✅ بنر «{title}» ذخیره شد و برای سفارش انتخاب شد.'
MSG_BANNER_SELECTED = '✅ بنر «{title}» انتخاب شد.\nحالا فهرست تعرفه‌ها را ببینید.'
MSG_BANNER_DELETED = '🗑 «{title}» حذف شد.'
MSG_BANNER_RENAMED = '✅ نام بنر «{title}» شد.'
MSG_BANNER_NAME_PROMPT = 'یک نام کوتاه برای این بنر بفرستید.'
MSG_BANNER_CAPTION_PROMPT = 'متن تازهٔ بنر را بفرستید. عکس و ویدیو همان می‌ماند.'
MSG_BANNER_NOT_FROM_REF = (
    'این بنر از کانال بنرها ({ref}) نیست.\n'
    'اگر می‌خواهید بررسی شود، درخواست را ثبت کنید.'
)
MSG_BANNER_REVIEW_SENT = (
    '📨 درخواست بررسی بنر ثبت شد.\n'
    'هزینهٔ اعلام‌شده برای انتشار در کانال بنرها: {fee}'
)
MSG_BANNER_FEE_NOTE = 'هزینهٔ بنر بعدی در کانال بنرها: {fee}'

MSG_CATALOG_HEADER = '📋 فهرست تعرفه‌ها — صفحه {page}'
MSG_NO_FREE_DAYS = 'برای «{owner} — {tariff}» در این بازه نوبت خالی نیست.'
MSG_PICK_DAY_HEADER = '📅 روزهای خالی\n{owner} — {tariff} — {price}'
MSG_CART_ADDED = 'این روز انتخاب شد.\n\n{summary}'
MSG_CHECKOUT_OK = 'سفارش {order_id} با {count} کانال ثبت شد و برای کانال‌دارها فرستاده شد.'
MSG_ORDER_LINE = 'سفارش {id} | {status} | {count} کانال | {amount}'

MSG_MANAGER_HOME = (
    'بخش کانال‌دار\n\n'
    'نام شما در بله: {handle}\n'
    'کانال‌ها: {channels}\n'
    'منتظر پاسخ شما: {pending}\n'
    'قابل برداشت: {balance}\n\n'
    'اگر سفارشی منتظر شماست، اول همان را جواب دهید.'
)

# —— نحوهٔ ارسال (نسخه نهایی برای مدیر) ——
MSG_PUBLISH_MODE_TITLE = 'نحوهٔ ارسال تبلیغ در «{channel}»'
MSG_PUBLISH_MODE_CURRENT = 'روش فعلی: {label}'

MSG_PUBLISH_MODE_HELP = (
    'چطور می‌خواهید تبلیغ در این کانال منتشر شود؟ یکی را انتخاب کنید.\n\n'
    '۱) انتشار خودکار با بازوی لینک‌بان (پیشنهادی)\n'
    'بازوی لینک‌بان را مدیر این کانال کنید. سر وقت، بنر خودش منتشر می‌شود و در پایان مدت حذف می‌شود.\n\n'
    '۲) انتشار خودکار با حساب دستیار\n'
    'اگر جای مدیر بازو پر است، حساب دستیار لینک‌بان را مدیر کنید. این حساب بازو نیست.\n\n'
    '۳) انتشار دستی توسط شما\n'
    'بنر را خودتان در کانال می‌فرستید. پیش از موعد به شما یادآوری می‌شود.'
)

MSG_PUBLISH_MODE_SET = '✅ نحوهٔ انتشار روی «{label}» ذخیره شد.'
MSG_PUBLISH_MODE_HINT_BOT = '\nبازوی لینک‌بان را در کانال مدیر کنید. سر وقت، خودش پست را می‌فرستد.'
MSG_PUBLISH_MODE_HINT_LINKYAR = '\nحساب دستیار لینک‌بان را در کانال مدیر کنید. این حساب بازو نیست.'
MSG_REMIND_HOURS_ASK = 'چند ساعت قبل از موعد تبلیغ به شما یادآوری شود؟'

MSG_CHANNEL_LINKS_PROMPT = (
    'ثبت کانال\n\n'
    'پیوند کانال را بفرستید. اگر چند کانال یک مجموعه هستند، هر پیوند را در یک خط بنویسید.\n\n'
    'نام کاربری شما باید در بخش «درباره» کانال باشد: {proof}'
)
MSG_GROUP_NAME_PROMPT = 'نام مجموعه را بفرستید:'
MSG_CALENDAR_PICK_TARIFF = 'تعرفه را انتخاب کنید تا تقویم را ببینید.'
MSG_REMIND_PUBLISH = (
    '⏰ یادآوری ارسال تبلیغ\n'
    'سفارش شماره {item_id} — {owner}\n'
    'زمان: {when}\n\n'
    'بنر را در کانال بفرستید، بعد دکمهٔ «منتشر شد» را بزنید.'
)

MSG_PAYOUT_BATCH_HEADER = '📁 فایل تسویه شماره {id} — {count} درخواست\nمبالغ به ریال:'
MSG_PAYOUT_AFTER_BANK = 'پس از واریز بانک، دکمهٔ «پرداخت انجام شد» را بزنید.'
MSG_PAYOUT_MARKED = '✅ پرداخت این دسته ثبت شد و به کانال‌دارها خبر داده شد.'
MSG_PAYOUT_PAID_USER = '✅ مبلغ {amount} به‌صورت پایا به حساب شما واریز شد.'
MSG_WALLET_CREDITED = 'مبلغ {amount} بابت سفارش شماره {item_id} به اعتبار شما برگشت.'
MSG_EXEC_DONE_CUSTOMER = '✅ تبلیغ شما منتشر شد.\n{link}'
MSG_EXEC_DONE_MANAGER = 'سفارش {item_id} منتشر شد. مبلغ خالص، پس از کارمزد: {net}.'
MSG_EXEC_FAILED_MANAGER = 'سفارش شماره {item_id} منتشر نشد. جریمه این نوبت: {penalty}'
MSG_OPERATOR_REVIEW = (
    '🔎 بررسی انتشار\n'
    'نوبت {item_id} از سفارش {order_id}\n'
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
MSG_ORDER_REJECTED = (
    'سفارش {order_id} بسته شد، چون هیچ کانالی آن را نپذیرفت. '
    'اگر فقط یک کانال رد کند، بقیهٔ سفارش سر جایش می‌ماند.'
)
MSG_PUBLISH_OK_CUSTOMER = '✅ بنر شما در «{channel}» منتشر شد.\n🔗 {link}'
MSG_PUBLISH_FAIL_CHANNEL = '❌ سفارش شماره {item_id} در «{channel}» منتشر نشد. پشتیبانی در جریان است.'
MSG_TARIFF_DEACTIVATED = (
    '⚠️ تعرفه‌های «{channel}» موقتاً از فهرست خارج شد.\n'
    'بازوی لینک‌بان یا حساب دستیار دیگر مدیر این کانال نیست. وقتی درست شد، به پشتیبانی بگویید.'
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
        f'  پاسخ شما: {label_manager_status(manager_status)} | '
        f'انتشار: {label_exec_status(exec_status)}\n'
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
