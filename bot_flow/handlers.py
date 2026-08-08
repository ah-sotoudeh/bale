"""Manager registration: single channels or multi-channel packages."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from bot_flow.links import extract_channel_refs, normalize_channel_ref
from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from users.models import BotSession, User

logger = logging.getLogger(__name__)

STATE_IDLE = 'idle'
STATE_AWAIT_ROLE = 'await_role'
STATE_AWAIT_LINKS = 'await_links'
STATE_AWAIT_GROUP_NAME = 'await_group_name'
STATE_AWAIT_TARIFFS = 'await_tariffs'

TARIFF_LINE = re.compile(
    r'^\s*(.+?)\s*[|،,]\s*(\d+)\s*[|،,]\s*(\d+)\s*$'
    r'|^\s*(.+?)\s+(\d+)\s+(\d+)\s*$'
)


def reference_channel() -> str:
    return os.environ.get('REFERENCE_CHANNEL', '@linktest')


def get_session(bale_user_id: str) -> BotSession:
    sess, _ = BotSession.objects.get_or_create(
        bale_user_id=str(bale_user_id),
        defaults={'state': STATE_IDLE, 'data': {}},
    )
    return sess


def save_session(sess: BotSession, state: Optional[str] = None, **data_updates) -> None:
    if state is not None:
        sess.state = state
    if data_updates:
        d = dict(sess.data or {})
        d.update(data_updates)
        sess.data = d
    sess.save()


def ensure_user(bale_user_id: str, username_hint: str = '') -> User:
    uid = str(bale_user_id)
    handle = (username_hint or '').lstrip('@').strip() or None

    user = User.objects.filter(bale_user_id=uid).first()
    if user:
        if handle and user.bale_username != handle:
            user.bale_username = handle
            user.save(update_fields=['bale_username'])
        return user

    base = (handle or f'bale_{uid}')[:30]
    candidate = base
    n = 0
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f'{base}_{n}'
    user = User(username=candidate, bale_user_id=uid, bale_username=handle)
    user.set_unusable_password()
    user.save()
    return user


def ownership_tokens(manager: User) -> List[str]:
    tokens: List[str] = []
    if manager.bale_username:
        u = manager.bale_username.lstrip('@')
        tokens.extend([f'@{u}', u])
    if manager.bale_user_id:
        tokens.append(str(manager.bale_user_id))
    seen = set()
    out: List[str] = []
    for t in tokens:
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def bio_matches_owner(bio: str, manager: User) -> bool:
    text_lower = (bio or '').lower()
    return any(tok.lower() in text_lower for tok in ownership_tokens(manager))


def role_keyboard() -> Dict[str, Any]:
    return bc.inline_keyboard([
        [
            {'text': '📢 مدیر کانال هستم', 'callback_data': 'role:manager'},
            {'text': '🛒 مشتری هستم', 'callback_data': 'role:customer'},
        ]
    ])


def start_message(user: User) -> Tuple[str, Dict[str, Any]]:
    handle = user.bale_handle or user.bale_user_id or '—'
    text = (
        'سلام 👋 به ربات تبلیغات بله خوش آمدید.\n\n'
        f'آیدی شما: {handle}\n\n'
        'نقش خود را انتخاب کنید.\n'
        'مدیر: تک‌کانال یا چند کانال باهم (مجموعه).\n'
        'روزهای خالی: /free'
    )
    return text, role_keyboard()


def handle_start(chat_id: str, bale_user_id: str, username: str = '') -> None:
    user = ensure_user(bale_user_id, username)
    sess = get_session(bale_user_id)
    save_session(sess, STATE_AWAIT_ROLE, role=None)
    text, kb = start_message(user)
    bc.send_message(str(chat_id), text, reply_markup=kb)


def handle_role_callback(
    chat_id: str,
    bale_user_id: str,
    role: str,
    cq_id: Optional[str] = None,
    username: str = '',
) -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id), text='ثبت شد')
    sess = get_session(bale_user_id)
    user = ensure_user(bale_user_id, username)

    if role == 'customer':
        save_session(sess, STATE_IDLE, role='customer')
        bc.send_message(
            str(chat_id),
            f'شما مشتری شدید.\nکانال تعرفه: {reference_channel()}\n/start',
        )
        return

    if role == 'manager':
        save_session(sess, STATE_AWAIT_LINKS, role='manager', verified_ids=[])
        proof = user.bale_handle or user.bale_user_id
        bc.send_message(
            str(chat_id),
            'نقش: مدیر کانال ✅\n\n'
            'لینک کانال‌ها را بفرستید (هر خط یکی).\n'
            '• یک لینک = تک‌کانال\n'
            '• چند لینک در یک پیام = یک مجموعه با تعرفه مشترک\n\n'
            f'آیدی شما باید در بیوی هر کانال باشد: {proof}\n\n'
            'مثال مجموعه:\n'
            '@cooking1\n'
            '@inja_iran\n'
            '@cake_decoration',
        )
        return

    bc.send_message(str(chat_id), 'نقش نامعتبر. /start')


def _verify_and_register_channels(
    manager: User,
    refs: List[str],
) -> Tuple[List[Channel], List[str], List[str]]:
    ok: List[Channel] = []
    fail: List[str] = []
    notes: List[str] = []
    proof = manager.bale_handle or manager.bale_user_id or '?'

    for ref in refs:
        norm = normalize_channel_ref(ref)
        info = bc.get_channel_info(norm)
        if info.get('error'):
            fail.append(f'{norm}: خطا ({info.get("error")})')
            continue

        bio = str(info.get('bio') or info.get('description') or '')
        title = info.get('title') or norm
        if not bio_matches_owner(bio, manager):
            fail.append(
                f'{title} ({norm}): آیدی در بیو نیست. «{proof}» را بگذارید.'
            )
            continue

        with transaction.atomic():
            ch, created = Channel.objects.get_or_create(
                link=norm,
                defaults={'name': title, 'description': bio, 'manager': manager},
            )
            ch.name = title
            ch.description = bio
            ch.manager = manager
            ch.save()
            ok.append(ch)
            notes.append(f'{"ثبت" if created else "به‌روز"}: {title} ({norm})')

    return ok, fail, notes


def handle_links_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_LINKS:
        return False

    refs = extract_channel_refs(text)
    if not refs:
        bc.send_message(str(chat_id), 'لینک معتبر پیدا نشد. مثال: @mychannel')
        return True

    manager = ensure_user(bale_user_id)
    ok, fail, notes = _verify_and_register_channels(manager, refs)

    parts: List[str] = []
    if notes:
        parts.append('✅ تأییدشده:\n' + '\n'.join(f'• {n}' for n in notes))
    if fail:
        parts.append('⚠️ اصلاح:\n' + '\n'.join(fail))

    if not ok:
        parts.append('بعد از اصلاح بیو دوباره بفرستید.')
        bc.send_message(str(chat_id), '\n\n'.join(parts))
        return True

    channel_ids = [c.id for c in ok]

    # چند کانال → مجموعه
    if len(ok) > 1:
        save_session(
            sess,
            STATE_AWAIT_GROUP_NAME,
            role='manager',
            pending_channel_ids=channel_ids,
            package_mode=True,
            tariff_group_id=None,
            tariff_channel_id=None,
        )
        names = '\n'.join(f'{i+1}. {c.name} — {c.link}' for i, c in enumerate(ok))
        parts.append(
            f'\n📦 {len(ok)} کانال به‌صورت یک مجموعه ثبت می‌شوند (تعرفه و نوبت مشترک).\n'
            f'{names}\n\n'
            'نام مجموعه را بفرستید.\n'
            'مثال: کانال های آشپزی'
        )
        bc.send_message(str(chat_id), '\n\n'.join(parts))
        return True

    # تک‌کانال
    save_session(
        sess,
        STATE_AWAIT_TARIFFS,
        role='manager',
        package_mode=False,
        tariff_channel_id=ok[0].id,
        tariff_group_id=None,
        pending_channel_ids=channel_ids,
    )
    parts.append(
        f'\nتعرفه برای «{ok[0].name}»:\n'
        'نام | مدت_ساعت | قیمت_تومان\n'
        'مثال:\nروزانه | 24 | 300\nشبانه | 12 | 250'
    )
    bc.send_message(str(chat_id), '\n\n'.join(parts))
    return True


def handle_group_name_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_GROUP_NAME:
        return False

    name = (text or '').strip()
    if not name or name.startswith('/'):
        bc.send_message(str(chat_id), 'نام مجموعه را متنی بفرستید. مثال: کانال های آشپزی')
        return True

    manager = ensure_user(bale_user_id)
    ids = list(sess.data.get('pending_channel_ids') or [])
    channels = list(Channel.objects.filter(id__in=ids, manager=manager))
    if len(channels) < 2:
        bc.send_message(str(chat_id), 'کانال‌های مجموعه ناقص است. /start')
        save_session(sess, STATE_AWAIT_LINKS)
        return True

    with transaction.atomic():
        group = ChannelGroup.objects.create(name=name[:200], manager=manager)
        group.channels.set(channels)

    save_session(
        sess,
        STATE_AWAIT_TARIFFS,
        package_mode=True,
        tariff_group_id=group.id,
        tariff_channel_id=None,
        pending_channel_ids=ids,
    )
    bc.send_message(
        str(chat_id),
        f'مجموعه «{group.name}» با {len(channels)} کانال ذخیره شد.\n\n'
        'تعرفه‌های مشترک مجموعه را بفرستید (قیمت برای همه با هم):\n'
        'نام | مدت_ساعت | قیمت_تومان\n\n'
        'مثال:\n'
        '۲۴ ساعته روزانه | 24 | 300\n'
        '۱۲ ساعته شبانه | 12 | 250',
    )
    return True


def parse_tariff_lines(text: str) -> List[Tuple[str, int, int]]:
    rows: List[Tuple[str, int, int]] = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        m = TARIFF_LINE.match(line)
        if not m:
            continue
        if m.group(1) is not None:
            name, hours, price = m.group(1), m.group(2), m.group(3)
        else:
            name, hours, price = m.group(4), m.group(5), m.group(6)
        rows.append((name.strip(), int(hours), int(price)))
    return rows


def _channel_handle(ch: Channel) -> str:
    link = (ch.link or '').strip()
    if link.startswith('@'):
        return link
    if 'ble.ir/' in link:
        return '@' + link.rstrip('/').split('/')[-1]
    return link or ch.name


def publish_package_to_reference(group: ChannelGroup) -> Dict[str, Any]:
    tariffs = list(group.tariffs.order_by('id'))
    channels = list(group.channels.order_by('id'))
    if not tariffs:
        return {'error': 'no_tariffs'}

    lines = [f'📺 «{group.name}»']
    for i, ch in enumerate(channels, 1):
        lines.append(f'{i}. {ch.name} . {_channel_handle(ch)}')
    lines.append(f'💳 تعرفه ({len(channels)} کانال با هم)')
    for t in tariffs:
        lines.append(f'• {t.name} . {t.duration_hours}س . {t.price:,} ت')

    rows = []
    for t in tariffs:
        rows.append([
            {
                'text': f'{t.name} — {t.price:,} ت',
                'callback_data': f'order_tariff:{t.id}',
            }
        ])
    rows.append([
        {'text': '📝 ثبت سفارش تبلیغ', 'callback_data': f'order_group:{group.id}'}
    ])

    return bc.send_message(
        reference_channel(),
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(rows),
    )


def publish_channel_to_reference(channel: Channel) -> Dict[str, Any]:
    tariffs = list(Tariff.objects.filter(channel=channel).order_by('id'))
    if not tariffs:
        return {'error': 'no_tariffs'}

    lines = [
        f'📢 {channel.name}',
        _channel_handle(channel),
        '',
        'تعرفه‌ها:',
    ]
    for t in tariffs:
        lines.append(f'• {t.name}: {t.price:,} تومان / {t.duration_hours} ساعت')

    rows = []
    for t in tariffs:
        rows.append([
            {'text': f'{t.name} — {t.price:,} ت', 'callback_data': f'order_tariff:{t.id}'}
        ])
    rows.append([
        {'text': '📝 ثبت سفارش تبلیغ', 'callback_data': f'order_channel:{channel.id}'}
    ])

    return bc.send_message(
        reference_channel(),
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(rows),
    )


def handle_tariffs_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_TARIFFS:
        return False

    rows = parse_tariff_lines(text)
    if not rows:
        bc.send_message(
            str(chat_id),
            'فرمت تعرفه نادرست.\nمثال:\n۲۴ ساعته روزانه | 24 | 300',
        )
        return True

    package_mode = bool(sess.data.get('package_mode'))
    group_id = sess.data.get('tariff_group_id')
    ch_id = sess.data.get('tariff_channel_id')

    created = []
    if package_mode and group_id:
        try:
            group = ChannelGroup.objects.get(id=group_id)
        except ChannelGroup.DoesNotExist:
            bc.send_message(str(chat_id), 'مجموعه پیدا نشد. /start')
            save_session(sess, STATE_IDLE)
            return True

        with transaction.atomic():
            for name, hours, price in rows:
                t, _ = Tariff.objects.update_or_create(
                    group=group,
                    name=name,
                    defaults={
                        'channel': None,
                        'duration_hours': hours,
                        'price': price,
                    },
                )
                created.append(t)

        summary = '\n'.join(
            f'• {t.name}: {t.price} ت / {t.duration_hours}س' for t in created
        )
        bc.send_message(
            str(chat_id),
            f'تعرفه مشترک «{group.name}» ذخیره شد:\n{summary}',
        )
        pub = publish_package_to_reference(group)
        label = group.name
    else:
        try:
            channel = Channel.objects.get(id=ch_id)
        except Channel.DoesNotExist:
            bc.send_message(str(chat_id), 'کانال پیدا نشد. /start')
            save_session(sess, STATE_IDLE)
            return True

        with transaction.atomic():
            for name, hours, price in rows:
                t, _ = Tariff.objects.update_or_create(
                    channel=channel,
                    name=name,
                    defaults={
                        'group': None,
                        'duration_hours': hours,
                        'price': price,
                    },
                )
                created.append(t)

        summary = '\n'.join(
            f'• {t.name}: {t.price} ت / {t.duration_hours}س' for t in created
        )
        bc.send_message(
            str(chat_id),
            f'تعرفه «{channel.name}» ذخیره شد:\n{summary}',
        )
        pub = publish_channel_to_reference(channel)
        label = channel.name

    if pub.get('error') and pub.get('error') != 'no_tariffs':
        bc.send_message(
            str(chat_id),
            f'⚠️ انتشار در {reference_channel()} ناموفق: {pub.get("error")}',
        )
    elif not pub.get('error'):
        bc.send_message(str(chat_id), f'✅ «{label}» در {reference_channel()} منتشر شد.')

    save_session(
        sess,
        STATE_AWAIT_LINKS,
        role='manager',
        package_mode=False,
        tariff_group_id=None,
        tariff_channel_id=None,
        pending_channel_ids=[],
    )
    kb = bc.inline_keyboard([[{'text': '📅 روزهای خالی', 'callback_data': 'free:list'}]])
    bc.send_message(
        str(chat_id),
        'می‌توانید کانال/مجموعه جدید بفرستید، /free یا دکمه زیر:',
        reply_markup=kb,
    )
    return True


def handle_order_callback(
    chat_id: str,
    bale_user_id: str,
    kind: str,
    obj_id: int,
    cq_id: Optional[str] = None,
) -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id), text='دریافت شد')

    if kind == 'tariff':
        t = Tariff.objects.select_related('channel', 'group').filter(id=obj_id).first()
        if not t:
            bc.send_message(str(chat_id), 'تعرفه پیدا نشد.')
            return
        from bot_flow.calendar_ui import free_days_text_for_tariff

        owner = t.group.name if t.group_id else (t.channel.name if t.channel else '?')
        n = t.group.channel_count if t.group_id else 1
        text = (
            f'سفارش «{t.name}»\n'
            f'هدف: {owner}' + (f' ({n} کانال با هم)' if n > 1 else '') + '\n'
            f'{t.price:,} تومان / {t.duration_hours} ساعت\n\n'
            + free_days_text_for_tariff(t, days=7)
            + '\n\n(فلو کامل سفارش مشتری مرحله بعد.)'
        )
        bc.send_message(str(chat_id), text)
        return

    if kind == 'group':
        g = ChannelGroup.objects.filter(id=obj_id).first()
        name = g.name if g else obj_id
        bc.send_message(
            str(chat_id),
            f'ثبت سفارش برای مجموعه «{name}».\nبه‌زودی فلو مشتری کامل می‌شود.',
        )
        return

    ch = Channel.objects.filter(id=obj_id).first()
    name = ch.name if ch else obj_id
    bc.send_message(
        str(chat_id),
        f'ثبت سفارش برای «{name}».\nبه‌زودی فلو مشتری کامل می‌شود.',
    )


def try_handle_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
    username: str = '',
) -> bool:
    from bot_flow.calendar_ui import handle_free_callback

    if handle_free_callback(chat_id, bale_user_id, data, cq_id=cq_id):
        return True
    if data.startswith('role:'):
        handle_role_callback(
            chat_id, bale_user_id, data.split(':', 1)[1], cq_id=cq_id, username=username
        )
        return True
    if data.startswith('order_tariff:'):
        handle_order_callback(
            chat_id, bale_user_id, 'tariff', int(data.split(':')[1]), cq_id=cq_id
        )
        return True
    if data.startswith('order_group:'):
        handle_order_callback(
            chat_id, bale_user_id, 'group', int(data.split(':')[1]), cq_id=cq_id
        )
        return True
    if data.startswith('order_channel:'):
        handle_order_callback(
            chat_id, bale_user_id, 'channel', int(data.split(':')[1]), cq_id=cq_id
        )
        return True
    return False


def try_handle_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    norm = (text or '').strip()
    if norm.startswith('/free'):
        from bot_flow.calendar_ui import send_manager_channel_picker

        send_manager_channel_picker(chat_id, ensure_user(bale_user_id))
        return True

    sess = get_session(bale_user_id)
    if sess.state == STATE_AWAIT_LINKS:
        return handle_links_text(chat_id, bale_user_id, text)
    if sess.state == STATE_AWAIT_GROUP_NAME:
        return handle_group_name_text(chat_id, bale_user_id, text)
    if sess.state == STATE_AWAIT_TARIFFS:
        return handle_tariffs_text(chat_id, bale_user_id, text)
    return False
