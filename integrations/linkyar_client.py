"""لینک‌یار = حساب کاربری شخصی via aiobale + BALE_TOKEN (نه Bot API).

بدون نقل‌قول:
- Bot API: copyMessage (فقط بازو مثل لینک‌ساز)
- aiobale کاربر: forward همیشه ارجاع دارد؛ بدون نقل‌قول = send_* با
  DocumentMessage و use_own_content=True (ارسال مجدد محتوا، نه ForwardMessages)
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ROOT / '.env', override=False)
    load_dotenv(_ROOT / 'config' / '.env', override=False)


_load_dotenv()


def user_token() -> str:
    try:
        from django.conf import settings

        if settings.configured:
            t = getattr(settings, 'BALE_TOKEN', None) or getattr(settings, 'LINKYAR_TOKEN', None)
            if t:
                return str(t).strip()
    except Exception:
        pass
    return (os.environ.get('BALE_TOKEN', '') or os.environ.get('LINKYAR_TOKEN', '') or '').strip()


def linkyar_username() -> str:
    u = os.environ.get('LINKYAR_USERNAME', '@linkyar').strip()
    if u and not u.startswith('@'):
        u = '@' + u
    return u or '@linkyar'


def _inject_token(client, token: str) -> None:
    from aiobale.utils import parse_jwt
    from aiobale.types import ClientData, UserAuth

    parsed = parse_jwt(token)
    if not parsed:
        raise ValueError('BALE_TOKEN is not a valid JWT')
    payload, _ = parsed
    data = (
        payload['payload']
        if 'payload' in payload and isinstance(payload['payload'], dict)
        else payload
    )
    user_id = data.get('user_id') or data.get('id')
    if not user_id:
        raise ValueError('user_id missing in JWT')
    user = UserAuth(
        id=int(user_id),
        name=str(data.get('name') or data.get('first_name') or 'LinkYar'),
        access_hash=int(data.get('access_hash', -1)),
    )
    me = ClientData(
        id=int(user_id),
        user=user,
        app_id=int(data.get('app_id', 4)),
        auth_id=str(data.get('auth_id', '')),
        auth_sid=int(data.get('auth_sid', 0)),
        service=str(data.get('service', '')),
    )
    object.__setattr__(client, '_Client__token', token)
    object.__setattr__(client, '_me', me)


def _run(coro):
    """Always use a fresh event loop (Python 3.12+ MainThread has none by default)."""

    def _runner():
        return asyncio.run(coro)

    try:
        asyncio.get_running_loop()
        # already inside async → run in thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_runner).result(timeout=90)
    except RuntimeError:
        return _runner()


async def _with_client(async_fn):
    from aiobale import Client

    token = user_token()
    if not token or token == 'your_access_token_here':
        return {'ok': False, 'error': 'BALE_TOKEN missing (user session JWT for Link Yar)'}

    session_path = str(_ROOT / 'linkyar_session')
    client = Client(session_file=session_path)
    try:
        _inject_token(client, token)
    except Exception as e:
        return {'ok': False, 'error': f'token_inject: {e}'}

    try:
        return await async_fn(client)
    except Exception as e:
        logger.exception('linkyar aiobale call failed')
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        try:
            if client.session:
                await client.session.close()
        except Exception:
            pass


def get_me() -> Dict[str, Any]:
    async def _fn(client):
        me = await client.get_me()
        data = me.model_dump() if hasattr(me, 'model_dump') else {'raw': str(me)}
        return {'ok': True, 'result': data, 'user_id': client.id}

    return _run(_with_client(_fn))


async def _resolve_peer(client, channel_ref: str) -> Dict[str, Any]:
    ref = str(channel_ref).strip()
    if ref.lstrip('-').isdigit():
        return {'ok': True, 'peer_id': int(ref), 'access_hash': None}

    uname = ref.lstrip('@')
    try:
        resp = await client.search_username(uname)
        g = getattr(resp, 'group', None)
        if g is not None and getattr(g, 'id', None):
            return {
                'ok': True,
                'peer_id': int(g.id),
                'access_hash': getattr(g, 'access_hash', None),
                'title': getattr(g, 'title', '') or '',
            }
        # sometimes result structure differs
        for attr in ('peer', 'user', 'contact'):
            obj = getattr(resp, attr, None)
            if obj is not None and getattr(obj, 'id', None):
                return {'ok': True, 'peer_id': int(obj.id), 'access_hash': getattr(obj, 'access_hash', None)}
    except Exception as e:
        logger.info('search_username: %s', e)

    try:
        from aiobale.methods.user.search_contact import SearchContact
        from aiobale.utils import clean_grpc
        from aiobale.utils.grpc_post import add_header
        import aiohttp

        session = client.session
        if not session.session or session.session.closed:
            session.session = aiohttp.ClientSession()
        method = SearchContact(request=uname)
        headers = {
            'User-Agent': session.user_agent,
            'Origin': 'https://web.bale.ai',
            'content-type': 'application/grpc-web+proto',
            **{k[0].upper() + k[1:]: v for k, v in session._get_meta().items()},
            **session._build_headers(client.token),
        }
        url = f'{session.post_url}/{method.__service__}/{method.__method__}'
        data = method.model_dump(by_alias=True, exclude_none=True)
        payload = add_header(session.encoder(data))
        req = await session.session.post(url=url, headers=headers, data=payload)
        content = await req.read()
        if req.headers.get('grpc-message'):
            return {'ok': False, 'error': req.headers.get('grpc-message')}
        raw = session.decoder(clean_grpc(content))
        group = (raw or {}).get('5') or {}
        if group.get('1'):
            return {
                'ok': True,
                'peer_id': int(group['1']),
                'access_hash': int(group.get('2') or 0),
                'raw_keys': list((raw or {}).keys()),
            }
        return {'ok': False, 'error': 'channel_not_found', 'raw': raw}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def resolve_channel(username: str) -> Dict[str, Any]:
    async def _fn(client):
        return await _resolve_peer(client, username)

    return _run(_with_client(_fn))


def is_admin_of_channel(channel_ref: str) -> bool:
    async def _fn(client):
        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'is_admin': False, 'error': resolved.get('error')}
        peer_id = resolved['peer_id']
        try:
            perms = await client.get_member_permissions(peer_id, client.id)
        except Exception as e:
            return {'ok': False, 'is_admin': False, 'error': str(e), 'peer_id': peer_id}

        def _b(v):
            if v is None:
                return False
            if hasattr(v, 'value'):
                return bool(v.value)
            return bool(v)

        can_send = _b(getattr(perms, 'send_message', None)) or _b(getattr(perms, 'send_media', None))
        can_del = _b(getattr(perms, 'delete_message', None))
        can_pin = _b(getattr(perms, 'pin_message', None))
        is_adm = can_send and (can_del or can_pin)
        return {
            'ok': True,
            'is_admin': is_adm,
            'peer_id': peer_id,
            'permissions': {
                'send_message': can_send,
                'delete_message': can_del,
                'pin_message': can_pin,
            },
        }

    result = _run(_with_client(_fn))
    return bool(isinstance(result, dict) and result.get('is_admin'))


def send_text_to_channel(channel_ref: str, text: str) -> Dict[str, Any]:
    """پست متنی جدید = بدون نقل‌قول."""

    async def _fn(client):
        from aiobale.enums import ChatType

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': f"resolve: {resolved.get('error')}", 'resolved': resolved}
        peer_id = int(resolved['peer_id'])

        # عضویت/ادمین بودن کمک می‌کند InvalidArgument کمتر شود
        try:
            await client.join_public_chat(peer_id)
        except Exception as e:
            logger.info('join_public_chat (may already be member): %s', e)

        errors: List[str] = []
        for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
            try:
                msg = await client.send_message(text=text, chat_id=peer_id, chat_type=ctype)
                return {
                    'ok': True,
                    'message_id': getattr(msg, 'message_id', None),
                    'date': getattr(msg, 'date', None),
                    'peer_id': peer_id,
                    'chat_type': str(ctype),
                    'without_quote': True,
                }
            except Exception as e:
                errors.append(f'{ctype}: {e}')
                logger.info('send_message %s failed: %s', ctype, e)

        return {'ok': False, 'error': 'InvalidArgument/send_failed', 'peer_id': peer_id, 'tries': errors}

    return _run(_with_client(_fn))


def send_document_without_quote(
    channel_ref: str,
    document_message,
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """ارسال مجدد مدیا با use_own_content=True → بدون برچسب بازارسال.

    document_message: aiobale DocumentMessage از پیام مبدأ که لینک‌یار به آن دسترسی دارد.
    """

    async def _fn(client):
        from aiobale.enums import ChatType

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error')}
        peer_id = int(resolved['peer_id'])
        try:
            await client.join_public_chat(peer_id)
        except Exception:
            pass

        errors = []
        for ctype in (ChatType.GROUP, ChatType.CHANNEL):
            try:
                msg = await client.send_document(
                    document_message,
                    chat_id=peer_id,
                    chat_type=ctype,
                    caption=caption,
                    use_own_content=True,
                )
                return {
                    'ok': True,
                    'message_id': getattr(msg, 'message_id', None),
                    'date': getattr(msg, 'date', None),
                    'peer_id': peer_id,
                    'without_quote': True,
                }
            except Exception as e:
                errors.append(str(e))
        return {'ok': False, 'error': 'send_document_failed', 'tries': errors}

    return _run(_with_client(_fn))


def forward_to_channel(
    channel_ref: str,
    from_peer_id: int,
    message_id: int,
    message_date: int,
    from_peer_type: int = 1,
) -> Dict[str, Any]:
    """ForwardMessages — معمولاً با نقل‌قول/ارجاع مبدأ."""

    async def _fn(client):
        from aiobale.enums import ChatType, PeerType
        from aiobale.types import InfoMessage, Peer

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error')}
        peer_id = int(resolved['peer_id'])

        ptype = PeerType.PRIVATE if from_peer_type == 1 else PeerType.GROUP
        info = InfoMessage(
            peer=Peer(id=int(from_peer_id), type=ptype),
            message_id=int(message_id),
            date=int(message_date),
        )
        resp = await client.forward_message(
            message=info,
            chat_id=peer_id,
            chat_type=ChatType.GROUP,
        )
        return {
            'ok': True,
            'result': str(resp),
            'peer_id': peer_id,
            'without_quote': False,
            'note': 'forward معمولاً با برچسب بازارسال است',
        }

    return _run(_with_client(_fn))


def delete_channel_message(
    channel_ref: str,
    message_id: int,
    message_date: int,
) -> Dict[str, Any]:
    async def _fn(client):
        from aiobale.enums import ChatType

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error')}
        peer_id = int(resolved['peer_id'])
        last_err = None
        for ctype in (ChatType.GROUP, ChatType.CHANNEL):
            try:
                resp = await client.delete_message(
                    message_id=int(message_id),
                    message_date=int(message_date),
                    chat_id=peer_id,
                    chat_type=ctype,
                    just_me=False,
                )
                return {'ok': True, 'result': str(resp), 'chat_type': str(ctype)}
            except Exception as e:
                last_err = e
        return {'ok': False, 'error': str(last_err)}

    return _run(_with_client(_fn))


def send_message(chat_id: str, text: str, **kwargs) -> Dict[str, Any]:
    return send_text_to_channel(str(chat_id), text)


def delete_message(chat_id: str, message_id: int, message_date: int = 0) -> Dict[str, Any]:
    return delete_channel_message(str(chat_id), int(message_id), int(message_date or 0))


def copy_message(
    to_chat_id: str,
    from_chat_id: str,
    message_id: int,
    caption: Optional[str] = None,
    message_date: int = 0,
) -> Dict[str, Any]:
    """نام سازگار — برای کاربر معادل forward است (با نقل‌قول).
    بدون نقل‌قول از send_document_without_quote استفاده کن.
    """
    try:
        from_peer = int(str(from_chat_id)) if str(from_chat_id).lstrip('-').isdigit() else 0
    except ValueError:
        from_peer = 0
    if not from_peer or not message_date:
        if caption:
            return send_text_to_channel(str(to_chat_id), caption)
        return {'ok': False, 'error': 'need_from_peer_and_date; for no-quote use send_document_without_quote'}
    return forward_to_channel(
        str(to_chat_id),
        from_peer_id=from_peer,
        message_id=int(message_id),
        message_date=int(message_date),
        from_peer_type=1,
    )


def forward_message(
    to_chat_id: str, from_chat_id: str, message_id: int, message_date: int = 0
) -> Dict[str, Any]:
    return copy_message(to_chat_id, from_chat_id, message_id, message_date=message_date)
