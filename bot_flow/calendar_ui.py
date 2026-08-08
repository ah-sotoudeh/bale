"""Free booking days UI (Jalali) for channels and packages."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from django.utils import timezone

from bot_flow.jalali import format_jalali
from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from orders.availability import free_days_for_tariff
from users.models import User


def format_day(d: date) -> str:
    return format_jalali(d)


def free_days_text_for_tariff(tariff: Tariff, days: int = 14) -> str:
    today = timezone.localdate()
    until = today + timedelta(days=max(1, days) - 1)
    free = list(free_days_for_tariff(tariff, today, until))

    if tariff.group_id:
        owner = f'مجموعه «{tariff.group.name}» ({tariff.group.channel_count} کانال)'
    else:
        owner = tariff.channel.name if tariff.channel else '—'

    hour_label = (
        f'{tariff.start_hour:02d}:00'
        if tariff.start_hour is not None
        else 'بدون ساعت ثابت'
    )
    header = (
        f'📅 روزهای خالی (شمسی)\n'
        f'هدف: {owner}\n'
        f'تعرفه: {tariff.name}\n'
        f'نوبت: {hour_label} | {tariff.duration_hours}س | {tariff.price:,} تومان\n'
        f'از {format_jalali(today)} تا {format_jalali(until)}\n'
    )
    if not free:
        return header + '\nهیچ روز خالی‌ای در این بازه نیست.'

    lines = [header, f'✅ {len(free)} روز آزاد:']
    for d in free:
        lines.append(f'• {format_day(d)}')
    busy = days - len(free)
    if busy > 0:
        lines.append(f'\n🔒 {busy} روز پر یا مسدود')
    return '\n'.join(lines)


def free_days_text(channel: Channel, tariff: Tariff, days: int = 14) -> str:
    return free_days_text_for_tariff(tariff, days=days)


def channels_keyboard_for_manager(manager: User) -> Optional[Dict[str, Any]]:
    rows = []
    groups = list(
        ChannelGroup.objects.filter(manager=manager, tariffs__isnull=False)
        .distinct()
        .order_by('name')[:15]
    )
    for g in groups:
        rows.append([
            {
                'text': f'📦 {g.name} ({g.channel_count})',
                'callback_data': f'free:g:{g.id}',
            }
        ])

    channels = list(
        Channel.objects.filter(manager=manager, tariffs__isnull=False)
        .distinct()
        .order_by('name')[:15]
    )
    for ch in channels:
        rows.append([{'text': f'📢 {ch.name}', 'callback_data': f'free:ch:{ch.id}'}])

    if not rows:
        return None
    return bc.inline_keyboard(rows)


def tariffs_keyboard_channel(channel: Channel) -> Optional[Dict[str, Any]]:
    tariffs = list(channel.tariffs.order_by('id')[:20])
    if not tariffs:
        return None
    rows = [
        [{
            'text': f'{t.name} — {t.price:,} ت',
            'callback_data': f'free:t:{t.id}',
        }]
        for t in tariffs
    ]
    rows.append([{'text': '⬅️ بازگشت', 'callback_data': 'free:list'}])
    return bc.inline_keyboard(rows)


def tariffs_keyboard_group(group: ChannelGroup) -> Optional[Dict[str, Any]]:
    tariffs = list(group.tariffs.order_by('id')[:20])
    if not tariffs:
        return None
    rows = [
        [{
            'text': f'{t.name} — {t.price:,} ت',
            'callback_data': f'free:t:{t.id}',
        }]
        for t in tariffs
    ]
    rows.append([{'text': '⬅️ بازگشت', 'callback_data': 'free:list'}])
    return bc.inline_keyboard(rows)


def send_manager_channel_picker(chat_id: str, manager: User) -> None:
    kb = channels_keyboard_for_manager(manager)
    if not kb:
        bc.send_message(
            str(chat_id),
            'هنوز کانال یا مجموعه‌ای با تعرفه ندارید.\n/start',
        )
        return
    bc.send_message(
        str(chat_id),
        '📅 کانال یا مجموعه را انتخاب کنید:',
        reply_markup=kb,
    )


def handle_free_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
) -> bool:
    if not data.startswith('free:'):
        return False

    if cq_id:
        bc.answer_callback_query(str(cq_id), text='…')

    from bot_flow.handlers import ensure_user

    user = ensure_user(bale_user_id)
    parts = data.split(':')

    if data in ('free:list', 'free'):
        send_manager_channel_picker(chat_id, user)
        return True

    if len(parts) == 3 and parts[1] == 'ch':
        ch = Channel.objects.filter(id=int(parts[2]), manager=user).first()
        if not ch:
            bc.send_message(str(chat_id), 'کانال پیدا نشد.')
            return True
        kb = tariffs_keyboard_channel(ch)
        if not kb:
            bc.send_message(str(chat_id), 'تعرفه‌ای نیست.')
            return True
        bc.send_message(str(chat_id), f'تعرفه «{ch.name}»:', reply_markup=kb)
        return True

    if len(parts) == 3 and parts[1] == 'g':
        g = ChannelGroup.objects.filter(id=int(parts[2]), manager=user).first()
        if not g:
            bc.send_message(str(chat_id), 'مجموعه پیدا نشد.')
            return True
        kb = tariffs_keyboard_group(g)
        if not kb:
            bc.send_message(str(chat_id), 'تعرفه‌ای نیست.')
            return True
        bc.send_message(str(chat_id), f'تعرفه مجموعه «{g.name}»:', reply_markup=kb)
        return True

    if len(parts) == 3 and parts[1] == 't':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t:
            bc.send_message(str(chat_id), 'تعرفه پیدا نشد.')
            return True
        owner_ok = False
        if t.group_id and t.group.manager_id == user.id:
            owner_ok = True
        if t.channel_id and t.channel.manager_id == user.id:
            owner_ok = True
        if not owner_ok:
            bc.send_message(str(chat_id), 'دسترسی ندارید.')
            return True
        text = free_days_text_for_tariff(t, days=14)
        kb = bc.inline_keyboard([
            [
                {'text': '🔄 ۱۴ روز', 'callback_data': f'free:t:{t.id}'},
                {'text': '⬅️ لیست', 'callback_data': 'free:list'},
            ]
        ])
        bc.send_message(str(chat_id), text, reply_markup=kb)
        return True

    return False
