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
