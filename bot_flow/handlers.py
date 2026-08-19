"""Manager registration: single channels or multi-channel packages + publish mode."""
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
STATE_AWAIT_PUBLISH_MODE = 'await_publish_mode'
STATE_AWAIT_GROUP_NAME = 'await_group_name'
STATE_AWAIT_TARIFFS = 'await_tariffs'

TARIFF_LINE = re.compile(
    r'^\s*(.+?)\s*[|،,]\s*(\d+)\s*[|،,]\s*(\d+)\s*$'
    r'|^\s*(.+?)\s+(\d+)\s+(\d+)\s*$'
)

TARIFF_HELP = (
    'نام | ساعت_ارسال | مدت_ساعت | قیمت_تومان\n'
    'مثال: طرح عادی | 10 | 24 | 200\n'
    'یا: طرح عادی | ساعت 10 | 24 ساعت | 200 تومن'
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


def role_keyboard(is_operator: bool = False) -> Dict[str, Any]:
    rows = [
        [
            {'text': '🛒 پنل مشتری', 'callback_data': 'role:customer'},
            {'text': '📢 پنل مدیر کانال', 'callback_data': 'role:manager'},
        ],
    ]
    if is_operator:
        rows.append([{'text': '🛠️ پنل اپراتور', 'callback_data': 'op:home'}])
    rows.append([{'text': 'ℹ️ راهنما', 'callback_data': 'nav:help'}])
    return bc.inline_keyboard(rows)


def publish_mode_keyboard() -> Dict[str, Any]:
    return bc.inline_keyboard([
        [{'text': '✅ ۱) لینک‌ساز ادمین (پیشنهادی)', 'callback_data': f'pmode:{Channel.PUBLISH_BOT}'}],
        [{'text': '۲) لینک‌یار ادمین', 'callback_data': f'pmode:{Channel.PUBLISH_LINKYAR}'}],
        [{'text': '۳) ارسال دستی خودم', 'callback_data': f'pmode:{Channel.PUBLISH_MANUAL}'}],
    ])


def publish_mode_help_text() -> str:
    from integrations import linkyar_client as ly

    bot_name = '@linkbank_bot'
    ly_name = ly.linkyar_username()
    return (
        'نحوهٔ انتشار تبلیغ در کانال(ها) را انتخاب کنید:\n\n'
        f'1️⃣ *لینک‌ساز ادمین* (پایدارترین)\n'
        f'   {bot_name} را در کانال ادمین کنید تا خودش بفرستد.\n\n'
        f'2️⃣ *لینک‌یار ادمین*\n'
        f'   اگر ظرفیت add member پر است، {ly_name} را ادمین کنید.\n\n'
        f'3️⃣ *ارسال دستی*\n'
        f'   خودتان می‌فرستید؛ قبل از موعد یادآوری می‌شود.\n\n'
        'گزارش به مشتری همیشه فقط از لینک‌ساز است.'
    )


def start_message(user: User) -> Tuple[str, Dict[str, Any]]:
    from wallet.services import is_operator

    handle = user.bale_handle or user.bale_user_id or '—'
    text = (
        'سلام 👋\n'
        'به سامانه تبلیغات لینک‌بانک خوش آمدید.\n\n'
        f'آیدی شما: {handle}\n\n'
        'یک پنل را باز کنید:'
    )
    return text, role_keyboard(is_operator=is_operator(user.bale_user_id or ''))


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
        from bot_flow.customer import start_customer

        start_customer(chat_id, bale_user_id, username)
        return

    if role == 'manager':
        if Channel.objects.filter(manager=user).exists():
            from bot_flow.manager_panel import open_panel

            open_panel(chat_id, bale_user_id, username)
            return
        save_session(sess, STATE_AWAIT_LINKS, role='manager', verified_ids=[])
        proof = user.bale_handle or user.bale_user_id
        bc.send_message(
            str(chat_id),
            'نقش: مدیر کانال ✅\n\n'
            'لینک کانال‌ها را بفرستید (هر خط یکی).\n'
            '• یک لینک = تک‌کانال\n'
            '• چند لینک = مجموعه با تعرفه مشترک\n\n'
            f'آیدی در بیو: {proof}',
        )
        return

    bc.send_message(str(chat_id), 'نقش نامعتبر. /start')


def _verify_and_register_channels(
    manager: User, refs: List[str]
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
            fail.append(f'{title} ({norm}): آیدی در بیو نیست. «{proof}»')
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


def _ask_publish_mode(chat_id: str, sess: BotSession, channel_ids: List[int], package: bool) -> None:
    save_session(
        sess,
        STATE_AWAIT_PUBLISH_MODE,
        role='manager',
        pending_channel_ids=channel_ids,
        package_mode=package,
    )
    bc.send_message(str(chat_id), publish_mode_help_text(), reply_markup=publish_mode_keyboard())


def handle_links_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_LINKS:
        return False

    refs = extract_channel_refs(text)
    if not refs:
        bc.send_message(str(chat_id), 'لینک معتبر پیدا نشد.')
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

    if parts:
        bc.send_message(str(chat_id), '\n\n'.join(parts))

    channel_ids = [c.id for c in ok]
    _ask_publish_mode(chat_id, sess, channel_ids, package=len(ok) > 1)
    return True


def handle_publish_mode_callback(
    chat_id: str, bale_user_id: str, mode: str, cq_id: Optional[str] = None
) -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id), text='ثبت شد')

    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_PUBLISH_MODE:
        bc.send_message(str(chat_id), 'الان انتخاب حالت انتشار لازم نیست. /start')
        return

    if mode not in (Channel.PUBLISH_BOT, Channel.PUBLISH_LINKYAR, Channel.PUBLISH_MANUAL):
        bc.send_message(str(chat_id), 'حالت نامعتبر.')
        return

    manager = ensure_user(bale_user_id)
    ids = list(sess.data.get('pending_channel_ids') or [])
    channels = list(Channel.objects.filter(id__in=ids, manager=manager))
    if not channels:
        bc.send_message(str(chat_id), 'کانال پیدا نشد. /start')
        save_session(sess, STATE_AWAIT_LINKS)
        return

    Channel.objects.filter(id__in=[c.id for c in channels]).update(publish_mode=mode)
    label = dict(Channel.PUBLISH_MODE_CHOICES).get(mode, mode)

    hint = ''
    if mode == Channel.PUBLISH_BOT:
        hint = '\nلطفاً @linkbank_bot را در کانال(ها) ادمین کنید.'
    elif mode == Channel.PUBLISH_LINKYAR:
        from integrations import linkyar_client as ly

        hint = f'\nلطفاً {ly.linkyar_username()} را در کانال(ها) ادمین کنید.'

    bc.send_message(str(chat_id), f'حالت انتشار: {label} ✅{hint}')

    package_mode = bool(sess.data.get('package_mode')) and len(channels) > 1
    if package_mode:
        save_session(
            sess,
            STATE_AWAIT_GROUP_NAME,
            role='manager',
            pending_channel_ids=ids,
            package_mode=True,
            publish_mode=mode,
        )
        names = '\n'.join(f'{i+1}. {c.name} — {c.link}' for i, c in enumerate(channels))
        bc.send_message(
            str(chat_id),
            f'📦 مجموعه ({len(channels)} کانال)\n{names}\n\nنام مجموعه را بفرستید:',
        )
        return

    save_session(
        sess,
        STATE_AWAIT_TARIFFS,
        role='manager',
        package_mode=False,
        tariff_channel_id=channels[0].id,
        tariff_group_id=None,
        pending_channel_ids=ids,
        publish_mode=mode,
    )
    bc.send_message(
        str(chat_id),
        f'تعرفه «{channels[0].name}»:\n{TARIFF_HELP}',
    )


def handle_group_name_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_GROUP_NAME:
        return False

    name = (text or '').strip()
    if not name or name.startswith('/'):
        bc.send_message(str(chat_id), 'نام مجموعه را بفرستید.')
        return True

    manager = ensure_user(bale_user_id)
    ids = list(sess.data.get('pending_channel_ids') or [])
    channels = list(Channel.objects.filter(id__in=ids, manager=manager))
    if len(channels) < 2:
        bc.send_message(str(chat_id), 'کانال‌ها ناقص. /start')
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
        f'مجموعه «{group.name}» ذخیره شد.\nتعرفه مشترک:\n{TARIFF_HELP}',
    )
    return True


def _extract_int(s: str) -> Optional[int]:
    m = re.search(r'(\d{1,4})', s or '')
    return int(m.group(1)) if m else None


def parse_tariff_lines(text: str) -> List[Tuple[str, Optional[int], int, int]]:
    """نام | ساعت_ارسال | مدت | قیمت — چهارتایی یا سه‌تایی قدیمی."""
    rows: List[Tuple[str, Optional[int], int, int]] = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r'[|،,]', line) if p.strip()]
        if len(parts) >= 4:
            name = parts[0]
            hour = _extract_int(parts[1])
            dur = _extract_int(parts[2])
            price = _extract_int(parts[3])
            if name and hour is not None and dur is not None and price is not None:
                if 0 <= hour <= 23 and dur > 0 and price >= 0:
                    rows.append((name, hour, dur, price))
            continue
        if len(parts) == 3:
            name = parts[0]
            dur = _extract_int(parts[1])
            price = _extract_int(parts[2])
            if name and dur is not None and price is not None and dur > 0:
                rows.append((name, None, dur, price))
            continue
        m = TARIFF_LINE.match(line)
        if not m:
            continue
        if m.group(1) is not None:
            name, hours, price = m.group(1), m.group(2), m.group(3)
        else:
            name, hours, price = m.group(4), m.group(5), m.group(6)
        rows.append((name.strip(), None, int(hours), int(price)))
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
        hour = f'{t.start_hour:02d}:00' if t.start_hour is not None else '—'
        lines.append(f'• {t.name} . ارسال {hour} . {t.duration_hours}س . {t.price:,} ت')
    rows = [
        [{'text': f'{t.name} — {t.price:,} ت', 'callback_data': f'order_tariff:{t.id}'}]
        for t in tariffs
    ]
    rows.append([{'text': '📝 ثبت سفارش', 'callback_data': f'order_group:{group.id}'}])
    return bc.send_message(
        reference_channel(), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows)
    )


def publish_channel_to_reference(channel: Channel) -> Dict[str, Any]:
    tariffs = list(Tariff.objects.filter(channel=channel).order_by('id'))
    if not tariffs:
        return {'error': 'no_tariffs'}
    lines = [f'📢 {channel.name}', _channel_handle(channel), '', 'تعرفه‌ها:']
    for t in tariffs:
        hour = f'{t.start_hour:02d}:00' if t.start_hour is not None else '—'
        lines.append(f'• {t.name}: ارسال {hour} | {t.duration_hours}س | {t.price:,} ت')
    rows = [
        [{'text': f'{t.name} — {t.price:,} ت', 'callback_data': f'order_tariff:{t.id}'}]
        for t in tariffs
    ]
    rows.append([{'text': '📝 ثبت سفارش', 'callback_data': f'order_channel:{channel.id}'}])
    return bc.send_message(
        reference_channel(), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows)
    )


def handle_tariffs_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_TARIFFS:
        return False

    rows = parse_tariff_lines(text)
    if not rows:
        bc.send_message(str(chat_id), f'فرمت نامعتبر.\n{TARIFF_HELP}')
        return True

    package_mode = bool(sess.data.get('package_mode'))
    group_id = sess.data.get('tariff_group_id')
    ch_id = sess.data.get('tariff_channel_id')
    created = []

    if package_mode and group_id:
        try:
            group = ChannelGroup.objects.get(id=group_id)
        except ChannelGroup.DoesNotExist:
            bc.send_message(str(chat_id), 'مجموعه نیست. /start')
            return True
        with transaction.atomic():
            for name, start_hour, hours, price in rows:
                t, _ = Tariff.objects.update_or_create(
                    group=group,
                    name=name,
                    defaults={
                        'channel': None,
                        'start_hour': start_hour,
                        'duration_hours': hours,
                        'price': price,
                    },
                )
                created.append(t)
        label = group.name
        pub = publish_package_to_reference(group)
    else:
        try:
            channel = Channel.objects.get(id=ch_id)
        except Channel.DoesNotExist:
            bc.send_message(str(chat_id), 'کانال نیست. /start')
            return True
        with transaction.atomic():
            for name, start_hour, hours, price in rows:
                t, _ = Tariff.objects.update_or_create(
                    channel=channel,
                    name=name,
                    defaults={
                        'group': None,
                        'start_hour': start_hour,
                        'duration_hours': hours,
                        'price': price,
                    },
                )
                created.append(t)
        label = channel.name
        pub = publish_channel_to_reference(channel)

    summary = '\n'.join(
        f'• {x.name}: ارسال '
        f'{x.start_hour if x.start_hour is not None else "—"} | '
        f'{x.duration_hours}س | {x.price:,}ت'
        for x in created
    )
    bc.send_message(str(chat_id), f'ذخیره شد:\n{summary}')

    if pub.get('error') and pub.get('error') != 'no_tariffs':
        bc.send_message(str(chat_id), f'انتشار ناموفق: {pub.get("error")}')
    elif not pub.get('error'):
        bc.send_message(str(chat_id), f'✅ «{label}» در {reference_channel()}')

    save_session(sess, STATE_IDLE, role='manager', package_mode=False)
    from bot_flow.manager_panel import open_panel

    open_panel(chat_id, bale_user_id)
    return True


def handle_pmode_edit_start(chat_id: str, bale_user_id: str, cq_id: Optional[str] = None) -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id))
    manager = ensure_user(bale_user_id)
    channels = list(Channel.objects.filter(manager=manager).order_by('id')[:20])
    if not channels:
        bc.send_message(str(chat_id), 'کانالی ثبت نشده.')
        return
    rows = []
    for ch in channels:
        rows.append([{
            'text': f'{ch.name} ({ch.publish_mode})',
            'callback_data': f'pmode_ch:{ch.id}',
        }])
    bc.send_message(
        str(chat_id),
        'کانال را برای تغییر حالت انتشار انتخاب کنید:',
        reply_markup=bc.inline_keyboard(rows),
    )


def handle_pmode_channel_pick(
    chat_id: str, bale_user_id: str, channel_id: int, cq_id: Optional[str] = None
) -> None:
    if cq_id:
        bc.answer_callback_query(str(cq_id))
    manager = ensure_user(bale_user_id)
    ch = Channel.objects.filter(id=channel_id, manager=manager).first()
    if not ch:
        bc.send_message(str(chat_id), 'کانال یافت نشد.')
        return
    sess = get_session(bale_user_id)
    save_session(sess, STATE_AWAIT_PUBLISH_MODE, pending_channel_ids=[ch.id], package_mode=False)
    bc.send_message(
        str(chat_id),
        f'حالت فعلی «{ch.name}»: {ch.publish_mode_label}\n' + publish_mode_help_text(),
        reply_markup=publish_mode_keyboard(),
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
    if data == 'nav:start':
        handle_start(chat_id, bale_user_id, username)
        return True
    if data == 'nav:help':
        if cq_id:
            bc.answer_callback_query(str(cq_id))
        bc.send_message(
            str(chat_id),
            'راهنما:\n'
            '• مشتری: بنر → فهرست → سبد → پرداخت\n'
            '• مدیر: کانال/تعرفه/تقویم/مالی\n'
            '• اپراتور: تسویه و تأیید بنر\n\n'
            '/start منوی اصلی\n/customer پنل مشتری\n/panel پنل مدیر',
        )
        return True
    if data.startswith('role:'):
        handle_role_callback(
            chat_id, bale_user_id, data.split(':', 1)[1], cq_id=cq_id, username=username
        )
        return True
    if data.startswith('pmode:') and not data.startswith('pmode_'):
        handle_publish_mode_callback(
            chat_id, bale_user_id, data.split(':', 1)[1], cq_id=cq_id
        )
        return True
    if data == 'pmode_edit:start':
        handle_pmode_edit_start(chat_id, bale_user_id, cq_id=cq_id)
        return True
    if data.startswith('pmode_ch:'):
        handle_pmode_channel_pick(
            chat_id, bale_user_id, int(data.split(':')[1]), cq_id=cq_id
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
