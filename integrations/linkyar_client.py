"""لینک‌یار = حساب کاربری شخصی (نه بازو) از طریق aiobale + BALE_TOKEN.

الگو از ریپوی bale-ai: inject_token از JWT سشن web.bale.ai
بازوی گفتگو همچنان BALE_BOT_TOKEN / لینک‌سازه است.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
    return (
        os.environ.get('BALE_TOKEN', '')
        or os.environ.get('LINKYAR_TOKEN', '')
        or ''
    ).strip()


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
    """Run async aiobale call from sync Django code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # nested: create new loop in thread would be safer; for jobs use fresh
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result(timeout=60)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


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
        result = await async_fn(client)
        return result
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


def resolve_channel(username: str) -> Dict[str, Any]:
    """Resolve @username → peer_id (group/channel)."""

    async def _fn(client):
        uname = username.lstrip('@')
        # Prefer search_username; fallback raw SearchContact like bale-ai
        try:
            resp = await client.search_username(uname)
            # ContactResponse: group or user
            g = getattr(resp, 'group', None) or getattr(resp, 'peer', None)
            if g is not None:
                gid = getattr(g, 'id', None) or getattr(g, 'peer_id', None)
                ah = getattr(g, 'access_hash', None)
                title = getattr(g, 'title', None) or getattr(g, 'name', '')
                if gid:
                    return {
                        'ok': True,
                        'peer_id': int(gid),
                        'access_hash': int(ah) if ah is not None else None,
                        'title': title,
                    }
        except Exception as e:
            logger.info('search_username failed: %s', e)

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
        grpc_msg = req.headers.get('grpc-message')
        if grpc_msg:
            return {'ok': False, 'error': grpc_msg}
        raw = session.decoder(clean_grpc(content))
        group = (raw or {}).get('5') or {}
        if not group.get('1'):
            return {'ok': False, 'error': 'channel_not_found', 'raw': raw}
        return {
            'ok': True,
            'peer_id': int(group['1']),
            'access_hash': int(group.get('2') or 0),
            'title': '',
            'raw': raw,
        }

    return _run(_with_client(_fn))


def is_admin_of_channel(channel_ref: str) -> bool:
    """channel_ref: @username or numeric peer id."""

    async def _fn(client):
        peer_id = None
        ref = str(channel_ref).strip()
        if ref.startswith('@') or (ref and not ref.lstrip('-').isdigit()):
            resolved = await _resolve_async(client, ref)
            if not resolved.get('ok'):
                return {'ok': False, 'error': resolved.get('error'), 'is_admin': False}
            peer_id = resolved['peer_id']
        else:
            peer_id = int(ref)

        try:
            perms = await client.get_member_permissions(peer_id, client.id)
        except Exception as e:
            logger.info('get_member_permissions: %s', e)
            return {'ok': False, 'error': str(e), 'is_admin': False}

        def _b(v):
            if v is None:
                return False
            if hasattr(v, 'value'):
                return bool(v.value)
            return bool(v)

        # admin-like: can send + delete (or pin)
        can_send = _b(getattr(perms, 'send_message', None)) or _b(
            getattr(perms, 'send_media', None)
        )
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

    async def _resolve_async(client, username: str):
        # inline minimal resolve to avoid nested _run
        uname = username.lstrip('@')
        try:
            resp = await client.search_username(uname)
            g = getattr(resp, 'group', None)
            if g is not None and getattr(g, 'id', None):
                return {'ok': True, 'peer_id': int(g.id)}
        except Exception:
            pass
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
        if not group.get('1'):
            return {'ok': False, 'error': 'not_found'}
        return {'ok': True, 'peer_id': int(group['1'])}

    result = _run(_with_client(_fn))
    if isinstance(result, dict) and 'is_admin' in result:
        return bool(result['is_admin'])
    return False


def send_text_to_channel(channel_ref: str, text: str) -> Dict[str, Any]:
    async def _fn(client):
        from aiobale.enums import ChatType

        peer_id = await _peer_id(client, channel_ref)
        if peer_id is None:
            return {'ok': False, 'error': 'resolve_failed'}
        msg = await client.send_message(
            text=text,
            chat_id=peer_id,
            chat_type=ChatType.GROUP,
        )
        mid = getattr(msg, 'message_id', None)
        date = getattr(msg, 'date', None)
        return {
            'ok': True,
            'message_id': mid,
            'date': date,
            'peer_id': peer_id,
        }

    return _run(_with_client(_fn))


def forward_to_channel(
    channel_ref: str,
    from_peer_id: int,
    message_id: int,
    message_date: int,
    from_peer_type: int = 1,
) -> Dict[str, Any]:
    """Forward a known message into channel. from_peer_type: 1=private, 2=group."""

    async def _fn(client):
        from aiobale.enums import ChatType, PeerType
        from aiobale.types import InfoMessage, Peer

        peer_id = await _peer_id(client, channel_ref)
        if peer_id is None:
            return {'ok': False, 'error': 'resolve_failed'}

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
        return {'ok': True, 'result': str(resp), 'peer_id': peer_id}

    return _run(_with_client(_fn))


def delete_channel_message(
    channel_ref: str,
    message_id: int,
    message_date: int,
) -> Dict[str, Any]:
    async def _fn(client):
        from aiobale.enums import ChatType

        peer_id = await _peer_id(client, channel_ref)
        if peer_id is None:
            return {'ok': False, 'error': 'resolve_failed'}
        resp = await client.delete_message(
            message_id=int(message_id),
            message_date=int(message_date),
            chat_id=peer_id,
            chat_type=ChatType.GROUP,
            just_me=False,
        )
        return {'ok': True, 'result': str(resp)}

    return _run(_with_client(_fn))


async def _peer_id(client, channel_ref: str) -> Optional[int]:
    ref = str(channel_ref).strip()
    if ref.lstrip('-').isdigit():
        return int(ref)
    uname = ref.lstrip('@')
    try:
        resp = await client.search_username(uname)
        g = getattr(resp, 'group', None)
        if g is not None and getattr(g, 'id', None):
            return int(g.id)
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
            return None
        raw = session.decoder(clean_grpc(content))
        group = (raw or {}).get('5') or {}
        if group.get('1'):
            return int(group['1'])
    except Exception as e:
        logger.info('SearchContact resolve: %s', e)
    return None


# Back-compat aliases used by orders/publish.py (bot-style names)
def is_admin_of_channel_bool(channel_ref: str) -> bool:
    return is_admin_of_channel(channel_ref)


def send_message(chat_id: str, text: str, **kwargs) -> Dict[str, Any]:
    """Send text as Link Yar user into channel (@username or peer id)."""
    return send_text_to_channel(str(chat_id), text)


def delete_message(chat_id: str, message_id: int, message_date: int = 0) -> Dict[str, Any]:
    if not message_date:
        # delete may need real date; caller should pass it
        message_date = 0
    return delete_channel_message(str(chat_id), int(message_id), int(message_date))


def copy_message(
    to_chat_id: str,
    from_chat_id: str,
    message_id: int,
    caption: Optional[str] = None,
    message_date: int = 0,
) -> Dict[str, Any]:
    """Best-effort: forward into channel (user API has no copyMessage)."""
    try:
        from_peer = int(str(from_chat_id).lstrip('@')) if str(from_chat_id).lstrip('-').isdigit() else 0
    except ValueError:
        from_peer = 0
    if not from_peer or not message_date:
        # fallback text-only post with caption
        if caption:
            return send_text_to_channel(str(to_chat_id), caption)
        return {'ok': False, 'error': 'need_from_peer_and_date_for_forward'}
    return forward_to_channel(
        str(to_chat_id),
        from_peer_id=from_peer,
        message_id=int(message_id),
        message_date=int(message_date),
        from_peer_type=1,
    )


def forward_message(to_chat_id: str, from_chat_id: str, message_id: int, message_date: int = 0) -> Dict[str, Any]:
    return copy_message(to_chat_id, from_chat_id, message_id, message_date=message_date)
