"""تقویم مدیر: کانال → تعرفه → ۱۴ روز (خالی/پر) + ثبت/حذف نوبت دستی."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from django.utils import timezone

from bot_flow.jalali import format_jalali, to_jalali
from bot_flow.messages import fa_money, fa_num
from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from orders.availability import (
    clear_manual_busy_slot,
    day_status_map,
    list_manual_busy_slots,
    mark_tariff_day_busy,
)
from users.models import User


def format_day(d: date) -> str:
    return format_jalali(d)


def _short_day(d: date) -> str:
    try:
        _jy, jm, jd = to_jalali(d)
        return fa_num(f'{jm}/{jd}')
    except Exception:
        return fa_num(f'{d.month}/{d.day}')


def _owner_label(tariff: Tariff) -> str:
    if tariff.group_id:
        return f'مجموعه «{tariff.group.name}» ({fa_num(tariff.group.channel_count)} کانال)'
    return tariff.channel.name if tariff.channel else '—'


def _hour_label(tariff: Tariff) -> str:
    if tariff.start_hour is not None:
        return fa_num(f'{tariff.start_hour:02d}:00')
    return 'ساعت ارسال ثابت نیست'


def calendar_text_for_tariff(tariff: Tariff, days: int = 14) -> str:
    statuses = day_status_map(tariff, days=days)
    free_n = sum(1 for _, status in statuses if status == 'free')
    busy_n = sum(1 for _, status in statuses if status == 'full')
    past_n = sum(1 for _, status in statuses if status == 'past')
    lines = [
        '📅 تقویم نوبت‌ها',
        f'برای: {_owner_label(tariff)}',
        f'تعرفه: {tariff.name}',
        f'نوبت: {_hour_label(tariff)} | {fa_num(tariff.duration_hours)}س | {fa_money(tariff.price)}',
        '',
        f'✅ خالی: {fa_num(free_n)} | ❌ پر: {fa_num(busy_n)} | گذشته: {fa_num(past_n)}',
        '',
    ]
    marks = {'free': '✅', 'full': '❌', 'past': '·'}
    for d, status in statuses:
        lines.append(f'{marks.get(status, "·")} {format_day(d)}')
    return '\n'.join(lines)


def calendar_main_keyboard(tariff_id: int) -> Dict[str, Any]:
    return bc.inline_keyboard([
        [
            {'text': '🔒 ثبت نوبت دستی (روز پر)', 'callback_data': f'free:busy:{tariff_id}'},
        ],
        [
            {'text': '🗑 حذف نوبت دستی', 'callback_data': f'free:unbusy:{tariff_id}'},
        ],
        [
            {'text': '🔄 تازه‌سازی', 'callback_data': f'free:t:{tariff_id}'},
            {'text': '⬅️ لیست', 'callback_data': 'free:list'},
        ],
        [
            {'text': '🏠 بخش کانال‌دار', 'callback_data': 'mgr:home'},
        ],
    ])


def show_tariff_calendar(chat_id: str, tariff: Tariff) -> None:
    text = calendar_text_for_tariff(tariff, days=14)
    bc.send_message(str(chat_id), text, reply_markup=calendar_main_keyboard(tariff.id))


def ask_mark_busy_day(chat_id: str, tariff: Tariff) -> None:
    """روزهایی که هنوز خالی‌اند برای ثبت دستی پیشنهاد می‌شوند؛ همه ۱۴ روز قابل انتخاب‌اند."""
    statuses = day_status_map(tariff, days=14)
    rows = []
    row = []
    for d, status in statuses:
        mark = '✅' if status == 'free' else ('·' if status == 'past' else '❌')
        row.append({
            'text': f'{mark} {_short_day(d)}',
            'callback_data': f'free:busy_day:{tariff.id}:{d.isoformat()}',
        })
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        {'text': '⬅️ بازگشت به تقویم', 'callback_data': f'free:t:{tariff.id}'},
    ])
    bc.send_message(
        str(chat_id),
        'روزی را انتخاب کنید که می‌خواهید پر شود.\n'
        '✅ خالی است و ❌ از قبل پر است.',
        reply_markup=bc.inline_keyboard(rows),
    )


def ask_clear_manual_busy(chat_id: str, tariff: Tariff) -> None:
    slots = list_manual_busy_slots(tariff)
    if not slots:
        bc.send_message(
            str(chat_id),
            'روز دستی برای حذف نمانده.',
            reply_markup=calendar_main_keyboard(tariff.id),
        )
        return
    lines = ['🗑 نوبت‌های دستی\nبرای حذف، روی دکمه بزنید:']
    rows = []
    for slot in slots:
        day = timezone.localtime(slot.start).date()
        lines.append(f'• {format_day(day)}')
        rows.append([{
            'text': f'حذف {_short_day(day)}',
            'callback_data': f'free:unbusy_slot:{tariff.id}:{slot.id}',
        }])
    rows.append([{'text': '⬅️ بازگشت به تقویم', 'callback_data': f'free:t:{tariff.id}'}])
    bc.send_message(
        str(chat_id),
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(rows),
    )


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
                'text': f'📦 {g.name} ({fa_num(g.channel_count)})',
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
    rows.append([{'text': '🏠 بخش کانال‌دار', 'callback_data': 'mgr:home'}])
    return bc.inline_keyboard(rows)


def tariffs_keyboard_channel(channel: Channel) -> Optional[Dict[str, Any]]:
    tariffs = list(channel.tariffs.order_by('id')[:20])
    if not tariffs:
        return None
    rows = [
        [{
            'text': f'{t.name} — {fa_money(t.price, " ت")}',
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
            'text': f'{t.name} — {fa_money(t.price, " ت")}',
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
            'هنوز کانالی با قیمت ندارید. اول از بخش کانال‌دار تعرفه را بنویسید.',
        )
        return
    bc.send_message(
        str(chat_id),
        'تقویم\nکانال یا مجموعه را انتخاب کنید:',
        reply_markup=kb,
    )


def _tariff_owned_by(user: User, tariff: Tariff) -> bool:
    if tariff.group_id and tariff.group.manager_id == user.id:
        return True
    if tariff.channel_id and tariff.channel.manager_id == user.id:
        return True
    return False


def handle_free_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
) -> bool:
    if not data.startswith('free:'):
        return False

    if cq_id:
        try:
            bc.answer_callback_query(str(cq_id))
        except Exception:
            pass

    from bot_flow.handlers import ensure_user

    user = ensure_user(bale_user_id)
    parts = data.split(':')

    if data in ('free:list', 'free'):
        send_manager_channel_picker(chat_id, user)
        return True

    if len(parts) == 3 and parts[1] == 'ch':
        ch = Channel.objects.filter(id=int(parts[2]), manager=user).first()
        if not ch:
            bc.send_message(str(chat_id), 'این کانال را پیدا نکردم.')
            return True
        kb = tariffs_keyboard_channel(ch)
        if not kb:
            bc.send_message(str(chat_id), 'برای این کانال هنوز قیمتی نگذاشته‌اید.')
            return True
        bc.send_message(str(chat_id), f'تعرفه «{ch.name}» را انتخاب کنید:', reply_markup=kb)
        return True

    if len(parts) == 3 and parts[1] == 'g':
        g = ChannelGroup.objects.filter(id=int(parts[2]), manager=user).first()
        if not g:
            bc.send_message(str(chat_id), 'این مجموعه را پیدا نکردم.')
            return True
        kb = tariffs_keyboard_group(g)
        if not kb:
            bc.send_message(str(chat_id), 'برای این مجموعه هنوز قیمتی نگذاشته‌اید.')
            return True
        bc.send_message(str(chat_id), f'تعرفه مجموعه «{g.name}»:', reply_markup=kb)
        return True

    if len(parts) == 3 and parts[1] == 't':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t or not _tariff_owned_by(user, t):
            bc.send_message(str(chat_id), 'این تعرفه مال کانال شما نیست.')
            return True
        show_tariff_calendar(chat_id, t)
        return True

    # free:busy:TID — pick day to mark manual busy
    if len(parts) == 3 and parts[1] == 'busy':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t or not _tariff_owned_by(user, t):
            bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
            return True
        ask_mark_busy_day(chat_id, t)
        return True

    # free:busy_day:TID:YYYY-MM-DD
    if len(parts) == 4 and parts[1] == 'busy_day':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t or not _tariff_owned_by(user, t):
            bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
            return True
        try:
            day = date.fromisoformat(parts[3])
        except ValueError:
            bc.send_message(str(chat_id), 'این تاریخ درست نیست.')
            return True
        try:
            slot = mark_tariff_day_busy(t, day)
        except Exception as exc:
            from orders.slots import SlotConflict

            if isinstance(exc, SlotConflict):
                bc.send_message(str(chat_id), 'این روز از قبل پر است.')
                show_tariff_calendar(chat_id, t)
                return True
            raise
        bc.send_message(
            str(chat_id),
            f'روز {format_jalali(day)} برای «{t.name}» پر شد.',
        )
        show_tariff_calendar(chat_id, t)
        return True

    # free:unbusy:TID — list manual slots
    if len(parts) == 3 and parts[1] == 'unbusy':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t or not _tariff_owned_by(user, t):
            bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
            return True
        ask_clear_manual_busy(chat_id, t)
        return True

    # free:unbusy_slot:TID:SLOT_ID
    if len(parts) == 4 and parts[1] == 'unbusy_slot':
        t = Tariff.objects.select_related('channel', 'group').filter(id=int(parts[2])).first()
        if not t or not _tariff_owned_by(user, t):
            bc.send_message(str(chat_id), 'این تعرفه را پیدا نکردم.')
            return True
        ok = clear_manual_busy_slot(int(parts[3]), t)
        if ok:
            bc.send_message(str(chat_id), 'نوبت دستی برداشته شد و روز دوباره خالی است.')
        else:
            bc.send_message(str(chat_id), 'این نوبت را پیدا نکردم.')
        show_tariff_calendar(chat_id, t)
        return True

    return False
