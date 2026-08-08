"""Show free booking days for a tariff in the Bale bot."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from channels_app.models import Channel, Tariff
from integrations import bale_client as bc
from orders.availability import free_days_for_tariff
from users.models import User

WEEKDAY_FA = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']
# Python weekday(): Mon=0 ... Sun=6 → map to FA list above


def _fa_weekday(d: date) -> str:
    return WEEKDAY_FA[d.weekday()]


def format_day(d: date) -> str:
    return f'{_fa_weekday(d)} {d.year}/{d.month:02d}/{d.day:02d}'


def free_days_text(
    channel: Channel,
    tariff: Tariff,
    days: int = 14,
) -> str:
    today = timezone.localdate()
    until = today + timedelta(days=max(1, days) - 1)
    free = list(free_days_for_tariff(channel, tariff, today, until))

    hour_label = (
        f'{tariff.start_hour:02d}:00'
        if tariff.start_hour is not None
        else 'بدون ساعت ثابت'
    )
    header = (
        f'📅 روزهای خالی\n'
        f'کانال: {channel.name}\n'
        f'تعرفه: {tariff.name}\n'
        f'نوبت: {hour_label} | {tariff.duration_hours} ساعت | {tariff.price:,} تومان\n'
        f'بازه: {days} روز آینده\n'
    )
    if not free:
        return header + '\nهیچ روز خالی‌ای در این بازه نیست.'

    lines = [header, f'✅ {len(free)} روز آزاد:']
    for d in free:
        lines.append(f'• {format_day(d)}')
    busy_count = days - len(free)
    if busy_count > 0:
        lines.append(f'\n🔒 {busy_count} روز پر یا مسدود')
    return '\n'.join(lines)


def channels_keyboard_for_manager(manager: User) -> Optional[Dict[str, Any]]:
    channels = list(
        Channel.objects.filter(manager=manager, tariffs__isnull=False).distinct().order_by('name')[:20]
    )
    if not channels:
        return None
    rows = [
        [{'text': f'📢 {ch.name}', 'callback_data': f'free:ch:{ch.id}'}]
        for ch in channels
    ]
    return bc.inline_keyboard(rows)


def tariffs_keyboard(channel: Channel) -> Optional[Dict[str, Any]]:
    tariffs = list(channel.tariffs.order_by('start_hour', 'id')[:20])
    if not tariffs:
        return None
    rows = []
    for t in tariffs:
        hour = f'{t.start_hour:02d}:00' if t.start_hour is not None else t.name
        rows.append([
            {
                'text': f'{hour} — {t.price:,} ت',
                'callback_data': f'free:t:{t.id}',
            }
        ])
    rows.append([{'text': '⬅️ بازگشت به کانال‌ها', 'callback_data': 'free:list'}])
    return bc.inline_keyboard(rows)


def send_manager_channel_picker(chat_id: str, manager: User) -> None:
    kb = channels_keyboard_for_manager(manager)
    if not kb:
        bc.send_message(
            str(chat_id),
            'هنوز کانال+تعرفه‌ای ثبت نکرده‌اید.\n'
            'با /start نقش مدیر را انتخاب کنید و کانال/تعرفه اضافه کنید.',
        )
        return
    bc.send_message(
        str(chat_id),
        '📅 کدام کانال را برای دیدن روزهای خالی می‌خواهید؟',
        reply_markup=kb,
    )


def handle_free_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
) -> bool:
    """Handle free:list | free:ch:ID | free:t:ID. Return True if matched."""
    if not data.startswith('free:'):
        return False

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='در حال بارگذاری…')

    from bot_flow.handlers import ensure_user

    user = ensure_user(bale_user_id)
    parts = data.split(':')

    if data == 'free:list' or data == 'free':
        send_manager_channel_picker(chat_id, user)
        return True

    if len(parts) == 3 and parts[1] == 'ch':
        try:
            ch_id = int(parts[2])
        except ValueError:
            bc.send_message(str(chat_id), 'شناسه کانال نامعتبر.')
            return True
        ch = Channel.objects.filter(id=ch_id, manager=user).first()
        if not ch:
            bc.send_message(str(chat_id), 'کانال پیدا نشد یا متعلق به شما نیست.')
            return True
        kb = tariffs_keyboard(ch)
        if not kb:
            bc.send_message(str(chat_id), f'برای «{ch.name}» تعرفه‌ای ثبت نشده.')
            return True
        bc.send_message(
            str(chat_id),
            f'تعرفه کانال «{ch.name}» را انتخاب کنید:',
            reply_markup=kb,
        )
        return True

    if len(parts) == 3 and parts[1] == 't':
        try:
            t_id = int(parts[2])
        except ValueError:
            bc.send_message(str(chat_id), 'شناسه تعرفه نامعتبر.')
            return True
        t = Tariff.objects.select_related('channel').filter(id=t_id).first()
        if not t or not t.channel.manager_id or t.channel.manager_id != user.id:
            bc.send_message(str(chat_id), 'تعرفه پیدا نشد یا متعلق به شما نیست.')
            return True
        text = free_days_text(t.channel, t, days=14)
        kb = bc.inline_keyboard([
            [
                {'text': '🔄 ۱۴ روز', 'callback_data': f'free:t:{t.id}'},
                {'text': '📢 کانال‌ها', 'callback_data': 'free:list'},
            ]
        ])
        bc.send_message(str(chat_id), text, reply_markup=kb)
        return True

    return False
