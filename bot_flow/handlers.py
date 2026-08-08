"""Manager-side registration conversation for the Bale ads bot.

Ownership proof: manager's public @id (e.g. @linkpakhsh) must appear in channel bio.
Channels + tariffs are always persisted in DB (Channel / Tariff models).
Catalog posts go to REFERENCE_CHANNEL (default @linktest).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import Prefetch

from bot_flow.links import extract_channel_refs, normalize_channel_ref
from channels_app.models import Channel, Tariff
from integrations import bale_client as bc
from users.models import BotSession, User

logger = logging.getLogger(__name__)

STATE_IDLE = 'idle'
STATE_AWAIT_ROLE = 'await_role'
STATE_AWAIT_LINKS = 'await_links'
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
    """Create/update User; store public Bale @id in bale_username when available."""
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
    """Strings that count as proof in channel bio (prefer public @id)."""
    tokens: List[str] = []
    if manager.bale_username:
        u = manager.bale_username.lstrip('@')
        tokens.append(f'@{u}')
        tokens.append(u)
    if manager.bale_user_id:
        tokens.append(str(manager.bale_user_id))
    # unique, non-empty
    seen = set()
    out = []
    for t in tokens:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def bio_matches_owner(bio: str, manager: User) -> bool:
    text = bio or ''
    text_lower = text.lower()
    for tok in ownership_tokens(manager):
        if tok.lower() in text_lower:
            return True
    return False


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
        'لطفاً نقش خود را انتخاب کنید:'
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
            'شما به‌عنوان مشتری ثبت شدید.\n'
            'به‌زودی لیست کانال‌ها و تعرفه‌ها از دیتابیس برایتان نمایش داده می‌شود.\n'
            f'کانال نمایش تعرفه: {reference_channel()}\n\n'
            'برای شروع دوباره: /start',
        )
        return

    if role == 'manager':
        save_session(sess, STATE_AWAIT_LINKS, role='manager', verified_ids=[])
        proof = user.bale_handle or user.bale_user_id
        if not user.bale_username:
            tip = (
                '\n⚠️ برای حساب شما آیدی عمومی (@...) دیده نشد؛ '
                'فعلاً از شناسه عددی استفاده می‌شود. اگر آیدی دارید، یک‌بار دیگر /start بزنید.'
            )
        else:
            tip = ''
        bc.send_message(
            str(chat_id),
            'نقش شما: مدیر کانال ✅\n\n'
            'لینک یا آیدی کانال‌هایی که مدیریت می‌کنید را بفرستید.\n'
            'می‌توانید چند مورد در یک پیام بفرستید (هر خط یکی).\n\n'
            'مثال:\n'
            '@mychannel\n'
            'ble.ir/otherchannel\n\n'
            f'⚠️ آیدی شما باید داخل بیو/توضیحات کانال باشد تا مالکیت تأیید شود.\n'
            f'آیدی قابل قبول: {proof}'
            f'{tip}',
        )
        return

    bc.send_message(str(chat_id), 'نقش نامعتبر. /start را بزنید.')


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
            fail.append(f'{norm}: نتوانستیم اطلاعات بگیریم ({info.get("error")})')
            continue

        bio = str(info.get('bio') or info.get('description') or '')
        title = info.get('title') or norm
        if not bio_matches_owner(bio, manager):
            fail.append(
                f'{title} ({norm}): آیدی شما در بیو نیست.\n'
                f'لطفاً «{proof}» را در بیو/توضیحات کانال بگذارید و دوباره لینک را بفرستید.'
            )
            continue

        with transaction.atomic():
            ch, created = Channel.objects.get_or_create(
                link=norm,
                defaults={
                    'name': title,
                    'description': bio,
                    'manager': manager,
                },
            )
            ch.name = title
            ch.description = bio
            ch.manager = manager
            ch.save()
            ok.append(ch)
            notes.append(f'{"ثبت در دیتابیس" if created else "به‌روزرسانی دیتابیس"}: {title} ({norm}) #id={ch.id}')

    return ok, fail, notes


def handle_links_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_LINKS:
        return False

    refs = extract_channel_refs(text)
    if not refs:
        bc.send_message(
            str(chat_id),
            'لینک یا آیدی معتبری پیدا نشد.\n'
            'مثال: @mychannel یا ble.ir/mychannel',
        )
        return True

    manager = ensure_user(bale_user_id)
    ok, fail, notes = _verify_and_register_channels(manager, refs)

    parts: List[str] = []
    if notes:
        parts.append('✅ کانال‌های تأیید و ذخیره‌شده:\n' + '\n'.join(f'• {n}' for n in notes))
    if fail:
        parts.append('⚠️ نیاز به اصلاح:\n' + '\n\n'.join(fail))

    if not ok:
        parts.append('\nپس از گذاشتن آیدی در بیو، دوباره لینک‌ها را بفرستید.')
        bc.send_message(str(chat_id), '\n\n'.join(parts))
        return True

    verified_ids = list(sess.data.get('verified_ids') or [])
    for ch in ok:
        if ch.id not in verified_ids:
            verified_ids.append(ch.id)
    save_session(
        sess,
        STATE_AWAIT_TARIFFS,
        verified_ids=verified_ids,
        tariff_channel_id=ok[0].id,
        tariff_queue=[c.id for c in ok],
    )

    first = ok[0]
    parts.append(
        f'\nحالا تعرفه برای کانال «{first.name}» را بفرستید (در دیتابیس ذخیره می‌شود).\n'
        'هر خط یک تعرفه:\n'
        'نام | ساعت | قیمت\n\n'
        'مثال:\n'
        'روزانه | 24 | 50000\n'
        'شبانه | 12 | 30000'
    )
    bc.send_message(str(chat_id), '\n\n'.join(parts))
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


def publish_channel_to_reference(channel: Channel) -> Dict[str, Any]:
    """Build post from DB tariffs and send to catalog channel."""
    tariffs = list(Tariff.objects.filter(channel=channel).order_by('id'))
    if not tariffs:
        return {'error': 'no_tariffs'}

    lines = [
        f'📢 {channel.name}',
        channel.link or '',
        '',
        'تعرفه‌ها:',
    ]
    for t in tariffs:
        lines.append(f'• {t.name}: {t.price:,} ریال / {t.duration_hours} ساعت')

    rows = []
    for t in tariffs:
        rows.append([
            {
                'text': f'{t.name} — {t.price:,} ریال',
                'callback_data': f'order_tariff:{t.id}',
            }
        ])
    rows.append([
        {'text': '📝 ثبت سفارش تبلیغ', 'callback_data': f'order_channel:{channel.id}'}
    ])

    target = reference_channel()
    return bc.send_message(
        target,
        '\n'.join(lines),
        reply_markup=bc.inline_keyboard(rows),
    )


def catalog_from_db() -> List[Channel]:
    """All channels that have at least one tariff — for future customer picker."""
    return list(
        Channel.objects.filter(tariffs__isnull=False)
        .distinct()
        .prefetch_related(Prefetch('tariffs', queryset=Tariff.objects.order_by('id')))
        .order_by('name')
    )


def handle_tariffs_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state != STATE_AWAIT_TARIFFS:
        return False

    rows = parse_tariff_lines(text)
    if not rows:
        bc.send_message(
            str(chat_id),
            'فرمت تعرفه درست نبود.\nمثال:\nروزانه | 24 | 50000',
        )
        return True

    ch_id = sess.data.get('tariff_channel_id')
    queue = list(sess.data.get('tariff_queue') or [])
    try:
        channel = Channel.objects.get(id=ch_id)
    except Channel.DoesNotExist:
        bc.send_message(str(chat_id), 'کانال پیدا نشد. /start')
        save_session(sess, STATE_IDLE)
        return True

    created = []
    with transaction.atomic():
        for name, hours, price in rows:
            t, _ = Tariff.objects.update_or_create(
                channel=channel,
                name=name,
                defaults={'duration_hours': hours, 'price': price},
            )
            created.append(t)

    summary = '\n'.join(
        f'• {t.name}: {t.price} ریال / {t.duration_hours}س (db id={t.id})' for t in created
    )
    bc.send_message(
        str(chat_id),
        f'تعرفه‌های «{channel.name}» در دیتابیس ذخیره شد:\n{summary}',
    )

    pub = publish_channel_to_reference(channel)
    if pub.get('error') and pub.get('error') != 'no_tariffs':
        bc.send_message(
            str(chat_id),
            f'⚠️ انتشار در {reference_channel()} ناموفق بود: {pub.get("error")}\n'
            'ربات باید در آن کانال عضو/ادمین باشد.',
        )
    elif not pub.get('error'):
        bc.send_message(
            str(chat_id),
            f'✅ در کانال {reference_channel()} منتشر شد.',
        )

    if ch_id in queue:
        queue = [x for x in queue if x != ch_id]
    if queue:
        next_id = queue[0]
        save_session(sess, STATE_AWAIT_TARIFFS, tariff_channel_id=next_id, tariff_queue=queue)
        next_ch = Channel.objects.filter(id=next_id).first()
        name = next_ch.name if next_ch else str(next_id)
        bc.send_message(
            str(chat_id),
            f'کانال بعدی: «{name}»\nتعرفه‌ها را با همان فرمت بفرستید.',
        )
    else:
        save_session(sess, STATE_AWAIT_LINKS, role='manager', tariff_queue=[], tariff_channel_id=None)
        n_ch = Channel.objects.filter(manager__bale_user_id=str(bale_user_id)).count()
        n_t = Tariff.objects.filter(channel__manager__bale_user_id=str(bale_user_id)).count()
        bc.send_message(
            str(chat_id),
            'ثبت تمام شد ✅\n'
            f'در دیتابیس شما: {n_ch} کانال، {n_t} تعرفه.\n'
            'می‌توانید لینک کانال جدید بفرستید یا /start بزنید.',
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
        t = Tariff.objects.select_related('channel').filter(id=obj_id).first()
        if not t:
            bc.send_message(str(chat_id), 'تعرفه در دیتابیس پیدا نشد.')
            return
        bc.send_message(
            str(chat_id),
            f'سفارش تعرفه «{t.name}» — کانال {t.channel.name}\n'
            f'مبلغ: {t.price:,} ریال / {t.duration_hours} ساعت\n'
            f'(از دیتابیس، tariff_id={t.id})\n\n'
            'فلو کامل سفارش مشتری مرحله بعد است.',
        )
    else:
        ch = Channel.objects.filter(id=obj_id).first()
        name = ch.name if ch else obj_id
        bc.send_message(
            str(chat_id),
            f'ثبت سفارش برای کانال «{name}» (channel_id={obj_id})\n'
            'به‌زودی از روی لیست دیتابیس انتخاب کامل می‌شود.',
        )


def try_handle_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
    username: str = '',
) -> bool:
    if data.startswith('role:'):
        handle_role_callback(
            chat_id,
            bale_user_id,
            data.split(':', 1)[1],
            cq_id=cq_id,
            username=username,
        )
        return True
    if data.startswith('order_tariff:'):
        handle_order_callback(
            chat_id, bale_user_id, 'tariff', int(data.split(':')[1]), cq_id=cq_id
        )
        return True
    if data.startswith('order_channel:'):
        handle_order_callback(
            chat_id, bale_user_id, 'channel', int(data.split(':')[1]), cq_id=cq_id
        )
        return True
    return False


def try_handle_text(chat_id: str, bale_user_id: str, text: str) -> bool:
    sess = get_session(bale_user_id)
    if sess.state == STATE_AWAIT_LINKS:
        return handle_links_text(chat_id, bale_user_id, text)
    if sess.state == STATE_AWAIT_TARIFFS:
        return handle_tariffs_text(chat_id, bale_user_id, text)
    return False
