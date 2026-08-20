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
