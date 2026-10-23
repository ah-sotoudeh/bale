"""قوانین کسب‌وکار سفارش، لغو، تغییر زمان و مهلت مدیر."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

# مهلت پاسخ مدیر به سفارش (ساعت)
MANAGER_RESPONSE_HOURS = 12
# یادآوری قبل از پایان مهلت (ساعت مانده)
MANAGER_REMIND_BEFORE_HOURS = 2

# لغو پس از پرداخت
CANCEL_FEE_PERCENT = 14
CANCEL_MIN_HOURS_BEFORE_PUBLISH = 48  # کمتر از این: لغو عادی ممنوع

# تغییر زمان
TIME_CHANGE_MAX = 2
TIME_CHANGE_MIN_HOURS_BEFORE = 12

CANCEL_POLICY_TEXT = (
    'قوانین لغو و بازپرداخت:\n'
    '• پیش از پرداخت: لغو رایگان.\n'
    '• پس از پرداخت و بیش از ۴۸ ساعت تا انتشار: لغو با کسر ۱۴٪ جریمه؛ باقی به کیف پول.\n'
    '• کمتر از ۴۸ ساعت تا انتشار: لغو عادی ممکن نیست؛ می‌توانید درخواست تغییر زمان بدهید.\n'
    '• پس از انتشار: لغو و بازپرداخت عادی نیست.\n'
    '• اگر اجرا به‌خاطر سامانه یا مدیر ناموفق باشد، جریمه از شما کسر نمی‌شود.\n'
    'با پرداخت نهایی این شرایط را می‌پذیرید.'
)


def hours_until_publish(start) -> float | None:
    if not start:
        return None
    now = timezone.now()
    if timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    return (start - now).total_seconds() / 3600.0


def can_cancel_paid(start) -> tuple[bool, str, int]:
    """(allowed, reason_code, fee_percent)."""
    h = hours_until_publish(start)
    if h is None:
        return False, 'no_schedule', 0
    if h < 0:
        return False, 'already_past', 0
    if h < CANCEL_MIN_HOURS_BEFORE_PUBLISH:
        return False, 'within_48h', 0
    return True, 'with_fee', CANCEL_FEE_PERCENT


def can_change_time(start, changes_used: int) -> tuple[bool, str]:
    if changes_used >= TIME_CHANGE_MAX:
        return False, 'max_changes'
    h = hours_until_publish(start)
    if h is None:
        return False, 'no_schedule'
    # زمان جدید هم باید حداقل ۱۲ ساعت فاصله داشته باشد — در caller چک می‌شود
    return True, 'ok'


def new_time_allowed(new_start) -> tuple[bool, str]:
    h = hours_until_publish(new_start)
    if h is None:
        return False, 'no_schedule'
    if h < TIME_CHANGE_MIN_HOURS_BEFORE:
        return False, 'too_soon'
    return True, 'ok'
