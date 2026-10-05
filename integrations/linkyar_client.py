"""لینک‌یار = حساب کاربری شخصی via baleclient (اولویت) / aiobale + BALE_TOKEN.

پیوند مطلب: https://ble.ir/{username}/{message_id}/{date_ms}
message_id داخلی بله ≠ message_id برگشتی Bot API.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent

_BALE_LIB_NAME = None


def _bale_lib():
    """کلاینت حساب کاربری: baleclient اولویت، وگرنه aiobale.

    زیرماژول‌های aiobale به baleclient alias می‌شوند تا importهای موجود کار کنند.
    """
    global _BALE_LIB_NAME
    if _BALE_LIB_NAME == 'baleclient':
        import baleclient as m
        return m
    if _BALE_LIB_NAME == 'aiobale':
        import aiobale as m
        return m
    try:
        import sys
        import baleclient as m
        import baleclient.enums
        import baleclient.types
        import baleclient.types.values
        import baleclient.types.responses
        import baleclient.methods
        import baleclient.methods.messaging
        import baleclient.methods.messaging.send_message
        import baleclient.methods.messaging.forward_message
        import baleclient.methods.messaging.load_history
        import baleclient.methods.user
        import baleclient.methods.user.search_contact
        import baleclient.utils
        import baleclient.utils.grpc_post

        sys.modules['aiobale'] = m
        sys.modules['aiobale.enums'] = baleclient.enums
        sys.modules['aiobale.types'] = baleclient.types
        sys.modules['aiobale.types.values'] = baleclient.types.values
        sys.modules['aiobale.types.responses'] = baleclient.types.responses
        sys.modules['aiobale.methods'] = baleclient.methods
        sys.modules['aiobale.methods.messaging'] = baleclient.methods.messaging
        sys.modules['aiobale.methods.messaging.send_message'] = (
            baleclient.methods.messaging.send_message
        )
        sys.modules['aiobale.methods.messaging.forward_message'] = (
            baleclient.methods.messaging.forward_message
        )
        sys.modules['aiobale.methods.messaging.load_history'] = (
            baleclient.methods.messaging.load_history
        )
        sys.modules['aiobale.methods.user'] = baleclient.methods.user
        sys.modules['aiobale.methods.user.search_contact'] = (
            baleclient.methods.user.search_contact
        )
        sys.modules['aiobale.utils'] = baleclient.utils
        sys.modules['aiobale.utils.grpc_post'] = baleclient.utils.grpc_post
        _BALE_LIB_NAME = 'baleclient'
        logger.info('linkyar using library=baleclient')
        return m
    except ImportError:
        pass
    try:
        import aiobale as m
        _BALE_LIB_NAME = 'aiobale'
        logger.info('linkyar using library=aiobale (fallback)')
        return m
    except ImportError:
        _BALE_LIB_NAME = None
        raise ModuleNotFoundError('baleclient/aiobale not installed')


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


def message_permalink(channel_username: str, message_id: int, date_ms: int) -> str:
    """https://ble.ir/linktest/4694750267996327172/1786442151499"""
    uname = str(channel_username).lstrip('@').strip()
    return f'https://ble.ir/{uname}/{int(message_id)}/{int(date_ms)}'


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
    def _runner():
        return asyncio.run(coro)

    try:
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_runner).result(timeout=180)
        except RuntimeError:
            return _runner()
    except ModuleNotFoundError:
        logger.warning('baleclient/aiobale نصب نیست.')
        return {'ok': False, 'error': 'client_lib_missing'}


async def _with_client(async_fn):
    lib = _bale_lib()
    Client = lib.Client

    token = user_token()
    if not token or token == 'your_access_token_here':
        return {'ok': False, 'error': 'BALE_TOKEN missing'}

    client = Client(session_file=str(_ROOT / 'linkyar_session'))
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


async def _search_contact_raw(client, uname: str) -> Dict[str, Any]:
    from aiobale.methods.user.search_contact import SearchContact
    from aiobale.utils import clean_grpc
    from aiobale.utils.grpc_post import add_header
    import aiohttp

    session = client.session
    if not session.session or session.session.closed:
        session.session = aiohttp.ClientSession()
    method = SearchContact(request=uname.lstrip('@'))
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
            'source': 'SearchContact',
            'raw_group': group,
        }
    return {'ok': False, 'error': 'channel_not_found', 'raw': raw}


async def _enrich_access_hash(client, peer_id: int, access_hash: Any = None) -> Optional[int]:
    """اگر AH نبود از get_full_group / dialogs بگیر."""
    try:
        ah = int(access_hash) if access_hash not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        ah = None
    if ah:
        return ah
    try:
        await client.join_public_chat(int(peer_id))
    except Exception:
        pass
    try:
        full = await client.get_full_group(int(peer_id))
        ah2 = getattr(full, 'access_hash', None)
        if ah2 not in (None, 0, '0'):
            return int(ah2)
    except Exception as e:
        logger.info('get_full_group ah: %s', e)
    try:
        dialogs = await client.load_dialogs(limit=80)
        for d in dialogs or []:
            peer = getattr(d, 'peer', None) or (d.get('peer') if isinstance(d, dict) else None)
            if peer is None:
                continue
            pid = getattr(peer, 'id', None) if not isinstance(peer, dict) else peer.get('id') or peer.get('2')
            try:
                if int(pid) != int(peer_id):
                    continue
            except (TypeError, ValueError):
                continue
            pah = getattr(peer, 'access_hash', None) if not isinstance(peer, dict) else peer.get('access_hash') or peer.get('3')
            if pah not in (None, 0, '0'):
                return int(pah)
    except Exception as e:
        logger.info('load_dialogs ah: %s', e)
    return None


async def _resolve_peer(client, channel_ref: str) -> Dict[str, Any]:
    ref = str(channel_ref).strip()
    if ref.lstrip('-').isdigit():
        pid = int(ref)
        ah = await _enrich_access_hash(client, pid, None)
        return {'ok': True, 'peer_id': pid, 'access_hash': ah, 'source': 'numeric'}

    uname = ref.lstrip('@')
    sc = await _search_contact_raw(client, uname)
    if sc.get('ok') and sc.get('peer_id'):
        ah = await _enrich_access_hash(client, int(sc['peer_id']), sc.get('access_hash'))
        sc['access_hash'] = ah
        return sc

    try:
        resp = await client.search_username(uname)
        g = getattr(resp, 'group', None)
        if g is not None and getattr(g, 'id', None):
            pid = int(g.id)
            ah = await _enrich_access_hash(client, pid, getattr(g, 'access_hash', None))
            return {
                'ok': True,
                'peer_id': pid,
                'access_hash': ah,
                'title': getattr(g, 'title', '') or '',
                'source': 'search_username',
            }
    except Exception as e:
        logger.info('search_username: %s', e)

    return sc if sc else {'ok': False, 'error': 'resolve_failed'}


def _parse_raw_message_item(item: Any, channel_username: str) -> Optional[Dict[str, Any]]:
    """Parse one MessageData dict from raw LoadHistory (aliases as str keys)."""
    if not isinstance(item, dict):
        return None

    def g(*keys):
        for k in keys:
            if k in item:
                return item[k]
            sk = str(k)
            if sk in item:
                return item[sk]
        return None

    sender = g(1, '1')
    mid = g(2, '2')
    date = g(3, '3')
    content = g(4, '4')

    if mid is None:
        return None

    kind = 'unknown'
    preview = ''
    mime = None
    file_id = None
    file_access_hash = None
    file_size = None
    file_name = None

    if isinstance(content, dict):
        # MessageContent: text alias 1, document alias 2 (approx)
        text = content.get(1) or content.get('1')
        doc = content.get(2) or content.get('2')
        if isinstance(text, dict):
            kind = 'text'
            preview = str(text.get(1) or text.get('1') or '')[:120]
        elif isinstance(doc, dict):
            mime = str(doc.get(5) or doc.get('5') or '')
            file_id = doc.get(1) or doc.get('1')
            try:
                file_access_hash = int(doc.get(2) or doc.get('2') or 0) or None
            except (TypeError, ValueError):
                file_access_hash = None
            try:
                file_size = int(doc.get(3) or doc.get('3') or 0) or None
            except (TypeError, ValueError):
                file_size = None
            name = doc.get(4) or doc.get('4')
            if isinstance(name, dict):
                name = str(name)
            file_name = name if isinstance(name, str) else None
            cap = doc.get(8) or doc.get('8')
            cap_text = ''
            if isinstance(cap, dict):
                cap_text = str(cap.get(1) or cap.get('1') or '')
            if mime.startswith('image/') or (
                isinstance(name, str) and name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ):
                kind = 'photo'
            elif mime.startswith('video/'):
                kind = 'video'
            else:
                kind = 'document'
            preview = (cap_text or (name if isinstance(name, str) else '') or mime)[:120]

    try:
        mid_i = int(mid)
    except (TypeError, ValueError):
        return None
    try:
        date_i = int(date) if date is not None else None
    except (TypeError, ValueError):
        date_i = None
    try:
        sender_i = int(sender) if sender is not None else None
    except (TypeError, ValueError):
        sender_i = None

    permalink = None
    if date_i is not None and channel_username:
        permalink = message_permalink(channel_username, mid_i, date_i)

    return {
        'message_id': mid_i,
        'date': date_i,
        'sender_id': sender_i,
        'kind': kind,
        'preview': preview,
        'mime_type': mime,
        'file_id': file_id,
        'file_access_hash': file_access_hash,
        'file_size': file_size,
        'file_name': file_name,
        'permalink': permalink,
        'raw_keys': list(item.keys()) if isinstance(item, dict) else None,
    }


async def _load_history_raw(
    client,
    peer_id: int,
    access_hash: Optional[int],
    limit: int = 6,
    peer_type: int | None = None,
) -> Dict[str, Any]:
    """Call LoadHistory and decode without pydantic MessageContent validation."""
    from aiobale.enums import PeerType, ListLoadMode, Services
    from aiobale.utils import clean_grpc
    from aiobale.utils.grpc_post import add_header
    import aiohttp

    session = client.session
    if not session.session or session.session.closed:
        session.session = aiohttp.ClientSession()

    ptype = int(peer_type) if peer_type is not None else int(PeerType.GROUP)
    peer: Dict[str, Any] = {'1': ptype, '2': int(peer_id)}
    if access_hash is not None:
        peer['3'] = int(access_hash)

    body = {
        '1': peer,
        '2': -1,  # offset_date
        '4': int(ListLoadMode.BACKWARD),
        '5': int(limit),
    }

    headers = {
        'User-Agent': session.user_agent,
        'Origin': 'https://web.bale.ai',
        'content-type': 'application/grpc-web+proto',
        **{k[0].upper() + k[1:]: v for k, v in session._get_meta().items()},
        **session._build_headers(client.token),
    }
    service = Services.MESSAGING.value
    url = f'{session.post_url}/{service}/LoadHistory'
    payload = add_header(session.encoder(body))
    req = await session.session.post(url=url, headers=headers, data=payload)
    content = await req.read()
    grpc_err = req.headers.get('grpc-message')
    if grpc_err:
        return {'ok': False, 'error': grpc_err}

    raw = session.decoder(clean_grpc(content))
    data = (raw or {}).get('1') or (raw or {}).get(1)
    if data is None:
        return {'ok': False, 'error': 'empty_history', 'raw_keys': list((raw or {}).keys())}

    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return {'ok': False, 'error': f'unexpected_data_type:{type(data)}', 'raw': str(data)[:500]}

    return {'ok': True, 'items': items, 'raw_count': len(items)}


def get_me() -> Dict[str, Any]:
    async def _fn(client):
        me = await client.get_me()
        data = me.model_dump() if hasattr(me, 'model_dump') else {'raw': str(me)}
        return {'ok': True, 'result': data, 'user_id': client.id}

    return _run(_with_client(_fn))


def resolve_channel(username: str) -> Dict[str, Any]:
    async def _fn(client):
        return await _resolve_peer(client, username)

    return _run(_with_client(_fn))


def diagnose_channel(channel_ref: str) -> Dict[str, Any]:
    async def _fn(client):
        out: Dict[str, Any] = {'user_id': client.id}
        resolved = await _resolve_peer(client, channel_ref)
        out['resolve'] = resolved
        if not resolved.get('ok'):
            return out
        pid = int(resolved['peer_id'])
        try:
            j = await client.join_public_chat(pid)
            out['join'] = j.model_dump() if hasattr(j, 'model_dump') else str(j)
        except Exception as e:
            out['join_error'] = f'{type(e).__name__}: {e}'
        try:
            perms = await client.get_member_permissions(pid, client.id)
            out['permissions'] = perms.model_dump() if hasattr(perms, 'model_dump') else str(perms)
        except Exception as e:
            out['permissions_error'] = f'{type(e).__name__}: {e}'
        return out

    return _run(_with_client(_fn))


def linkyar_admin_state(channel_ref: str) -> str:
    """admin، not_admin، یا unknown. قطع ارتباط آمار را با حذف تعرفه عوض نمی‌کند."""
    try:
        d = diagnose_channel(channel_ref)
    except Exception:
        return 'unknown'
    if not isinstance(d, dict) or d.get('error') or d.get('permissions_error'):
        return 'unknown'
    resolve = d.get('resolve') or {}
    if isinstance(resolve, dict) and resolve and not resolve.get('ok', True):
        return 'unknown'
    perms = d.get('permissions')
    if not isinstance(perms, dict) or not perms:
        return 'unknown'

    def _b(key):
        v = perms.get(key)
        if isinstance(v, dict):
            return bool(v.get('value') or v.get('1'))
        return bool(v)

    if _b('send_message') or _b('send_media'):
        return 'admin'
    return 'not_admin'


def is_admin_of_channel(channel_ref: str) -> bool:
    return linkyar_admin_state(channel_ref) == 'admin'


def load_channel_history(channel_ref: str, limit: int = 6) -> Dict[str, Any]:
    """آخرین پیام‌های کانال + پیوند واقعی ble.ir (raw parser)."""

    async def _fn(client):
        ref = str(channel_ref).strip()
        uname = ref.lstrip('@') if not ref.lstrip('-').isdigit() else ''

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error'), 'resolved': resolved}

        peer_id = int(resolved['peer_id'])
        access_hash = resolved.get('access_hash')
        try:
            await client.join_public_chat(peer_id)
        except Exception as e:
            logger.info('join: %s', e)

        raw = await _load_history_raw(client, peer_id, access_hash, limit=int(limit))
        if not raw.get('ok'):
            return {
                'ok': False,
                'error': raw.get('error'),
                'peer_id': peer_id,
                'detail': raw,
            }

        items = []
        for it in raw.get('items') or []:
            parsed = _parse_raw_message_item(it, uname)
            if parsed:
                items.append(parsed)

        return {
            'ok': True,
            'peer_id': peer_id,
            'access_hash': access_hash,
            'username': uname,
            'count': len(items),
            'messages': items,
            'parser': 'raw_load_history',
        }

    return _run(_with_client(_fn))


async def _post_method_raw(client, method) -> Dict[str, Any]:
    """پست خام. پاسخ SendMessage در aiobale بدون context کلاینت می‌شکند، ولی خود ارسال انجام شده."""
    from aiobale.utils import clean_grpc
    from aiobale.utils.grpc_post import add_header
    import aiohttp

    session = client.session
    if not session.session or session.session.closed:
        session.session = aiohttp.ClientSession()
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
    grpc_err = req.headers.get('grpc-message')
    if grpc_err:
        return {'ok': False, 'error': str(grpc_err)}
    raw = session.decoder(clean_grpc(content)) or {}
    if not isinstance(raw, dict):
        raw = {}
    return {'ok': True, 'raw': raw}


async def _send_text_raw(client, peer_id: int, access_hash: Optional[int], text: str) -> Dict[str, Any]:
    from aiobale.enums import ChatType, PeerType
    from aiobale.types import Chat, Peer, MessageContent, TextMessage
    from aiobale.methods.messaging.send_message import SendMessage
    from aiobale.utils import generate_id

    errors: List[str] = []
    mid = generate_id()
    content = MessageContent(text=TextMessage(value=text))
    # کانال بله با نوع کانال قبول می‌شود. گروه و سوپرگروه InvalidArgument می‌دهند.
    combos = [
        (PeerType.GROUP, ChatType.CHANNEL),
        (PeerType.GROUP, ChatType.GROUP),
        (PeerType.GROUP, ChatType.SUPER_GROUP),
    ]

    for ptype, ctype in combos:
        peer_kwargs: Dict[str, Any] = {'type': ptype, 'id': peer_id}
        if access_hash is not None:
            peer_kwargs['access_hash'] = int(access_hash)
        peer = Peer(**peer_kwargs)
        chat = Chat(id=peer_id, type=ctype)
        call = SendMessage(peer=peer, message_id=mid, content=content, chat=chat)
        try:
            posted = await _post_method_raw(client, call)
        except Exception as e:
            errors.append(f'{ptype}/{ctype}: {e}')
            continue
        if not posted.get('ok'):
            errors.append(f'{ptype}/{ctype}: {posted.get("error")}')
            continue
        raw = posted.get('raw') or {}
        date = raw.get('2', raw.get(2))
        try:
            date_i = int(date) if date is not None else None
        except (TypeError, ValueError):
            date_i = None
        return {
            'ok': True,
            'message_id': int(mid),
            'date': date_i,
            'peer_id': peer_id,
            'combo': f'{ptype}/{ctype}',
            'without_quote': True,
        }

    return {'ok': False, 'error': 'send_failed', 'tries': errors, 'peer_id': peer_id}


def send_text_to_channel(channel_ref: str, text: str) -> Dict[str, Any]:
    async def _fn(client):
        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': f"resolve: {resolved.get('error')}", 'resolved': resolved}

        peer_id = int(resolved['peer_id'])
        access_hash = resolved.get('access_hash')
        try:
            await client.join_public_chat(peer_id)
        except Exception as e:
            logger.info('join: %s', e)
        return await _send_text_raw(client, peer_id, access_hash, text)

    return _run(_with_client(_fn))


async def _send_uploaded_document(
    client,
    peer_id: int,
    access_hash: Optional[int],
    file_info,
    caption: str,
    kind: str,
) -> Dict[str, Any]:
    from aiobale.enums import ChatType, PeerType
    from aiobale.types import (
        Chat,
        Peer,
        MessageContent,
        DocumentMessage,
        MessageCaption,
        DocumentsExt,
        PhotoExt,
        VideoExt,
    )
    from aiobale.methods.messaging.send_message import SendMessage
    from aiobale.utils import generate_id

    cap = MessageCaption(content=caption) if caption else None
    ext = None
    if kind == 'photo':
        ext = DocumentsExt(photo=PhotoExt(w=1000, h=1000))
    elif kind == 'video':
        try:
            ext = DocumentsExt(video=VideoExt(w=1280, h=720))
        except Exception:
            ext = None

    document = DocumentMessage(
        file_id=file_info.file_id,
        size=file_info.size,
        name=file_info.name,
        mime_type=file_info.mime_type,
        access_hash=file_info.access_hash,
        caption=cap,
        ext=ext,
    )
    content = MessageContent(document=document)
    errors: List[str] = []

    for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
        peer_kwargs: Dict[str, Any] = {'type': PeerType.GROUP, 'id': peer_id}
        if access_hash is not None:
            peer_kwargs['access_hash'] = int(access_hash)
        peer = Peer(**peer_kwargs)
        chat = Chat(id=peer_id, type=ctype)
        mid = generate_id()
        call = SendMessage(peer=peer, message_id=mid, content=content, chat=chat)
        try:
            result = await client(call)
            msg = getattr(result, 'message', result)
            return {
                'ok': True,
                'message_id': getattr(msg, 'message_id', mid),
                'date': getattr(msg, 'date', None),
                'peer_id': peer_id,
                'access_hash': access_hash,
                'chat_type': str(ctype),
                'without_quote': True,
                'method': 'raw_send_document',
            }
        except Exception as e:
            errors.append(f'raw/{ctype}: {e}')

    return {'ok': False, 'error': 'raw_send_failed', 'tries': errors}


def send_local_file_to_channel(
    channel_ref: str,
    file_path: str,
    caption: str = '',
    kind: str = 'photo',
) -> Dict[str, Any]:
    async def _fn(client):
        from aiobale.enums import ChatType, SendType
        from aiobale.types import FileInput

        path = Path(file_path)
        if not path.exists():
            return {'ok': False, 'error': f'file_missing: {file_path}'}

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error'), 'resolved': resolved}
        peer_id = int(resolved['peer_id'])
        access_hash = resolved.get('access_hash')

        try:
            await client.join_public_chat(peer_id)
        except Exception as e:
            logger.info('join: %s', e)

        fin = FileInput(str(path))
        send_type = {
            'photo': SendType.PHOTO,
            'video': SendType.VIDEO,
            'document': SendType.DOCUMENT,
        }.get(kind, SendType.DOCUMENT)

        errors: List[str] = []

        try:
            file_info = await client.upload_file(
                file=fin,
                chat_id=peer_id,
                chat_type=ChatType.GROUP,
                send_type=send_type,
            )
            raw = await _send_uploaded_document(
                client, peer_id, access_hash, file_info, caption or '', kind
            )
            if raw.get('ok'):
                return raw
            errors.extend(raw.get('tries') or [raw.get('error')])
        except Exception as e:
            errors.append(f'upload_or_raw: {e}')

        try:
            if kind == 'photo':
                msg = await client.send_photo(
                    fin, chat_id=peer_id, chat_type=ChatType.GROUP, caption=caption or None
                )
            elif kind == 'video':
                msg = await client.send_video(
                    fin, chat_id=peer_id, chat_type=ChatType.GROUP, caption=caption or None
                )
            else:
                msg = await client.send_document(
                    fin, chat_id=peer_id, chat_type=ChatType.GROUP, caption=caption or None
                )
            return {
                'ok': True,
                'message_id': getattr(msg, 'message_id', None),
                'date': getattr(msg, 'date', None),
                'peer_id': peer_id,
                'method': f'send_{kind}_highlevel',
            }
        except Exception as e:
            errors.append(f'highlevel_GROUP: {e}')

        return {
            'ok': False,
            'error': 'upload_send_failed',
            'tries': errors,
            'peer_id': peer_id,
            'hint': 'use load_channel_history after send to recover real ids',
        }

    return _run(_with_client(_fn))


def forward_banner_from_linkbank(
    target_channel_ref: str,
    source_channel_ref: str,
    *,
    caption_match: str = '',
    limit: int = 40,
    bot_from_chat_id: str = '',
    bot_message_id: int = 0,
    dst_peer_id: int | None = None,
    dst_title: str = '',
) -> Dict[str, Any]:
    """فوروارد با نقل‌قول از لینک‌بانک.

    اولویت ۱: bale-sdk (forward_messages با rid+date)
    اولویت ۲: baleclient/aiobale
    """
    sdk_err = ''
    try:
        result = _forward_via_bale_sdk(
            target_channel_ref,
            source_channel_ref,
            caption_match=caption_match,
            limit=limit,
            dst_peer_id=dst_peer_id,
            dst_title=dst_title,
        )
        if isinstance(result, dict) and result.get('ok'):
            return result
        if isinstance(result, dict) and result.get('error'):
            sdk_err = str(result.get('error'))
            if result.get('tries'):
                sdk_err = sdk_err + ' | ' + str(result['tries'][0])[:120]
            # اگر bale-sdk نصب بود ولی فوروارد شکست → همان خطا را برگردان
            # (fallback فقط وقتی sdk نصب نیست)
            if result.get('lib') == 'bale-sdk' and result.get('error') != 'BALE_TOKEN missing':
                return result
    except ModuleNotFoundError:
        logger.info('bale-sdk not installed; fallback to baleclient/aiobale')
    except Exception as e:
        logger.exception('bale-sdk forward exception')
        sdk_err = f'{type(e).__name__}: {e}'

    result = _forward_via_aiobale_stack(
        target_channel_ref,
        source_channel_ref,
        caption_match=caption_match,
        limit=limit,
    )
    if isinstance(result, dict) and sdk_err and not result.get('ok'):
        result = dict(result)
        result['sdk_error'] = sdk_err[:200]
    return result


def _forward_via_bale_sdk(
    target_channel_ref: str,
    source_channel_ref: str,
    *,
    caption_match: str = '',
    limit: int = 40,
    dst_peer_id: int | None = None,
    dst_title: str = '',
) -> Dict[str, Any]:
    """فوروارد پایدار: لینک‌بانک → (خصوصی خود لینک‌یار) → کانال مقصد.

    ارسال مستقیم به کانال با API بی‌اثر بود؛ ارسال به خود (me) کار می‌کند.
    """

    def _u64(val) -> int:
        if val is None:
            return 0
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, int):
            return int(val)
        if isinstance(val, float):
            return int(val)
        if isinstance(val, str) and val.strip().lstrip('-').isdigit():
            return int(val.strip())
        try:
            inner = getattr(val, 'value', None)
            if inner is not None and inner is not val:
                return _u64(inner)
        except Exception:
            pass
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    async def _fn():
        import asyncio
        import random
        import time as _time
        from bale import BaleClient, pb
        from bale.peer import Peer

        token = user_token()
        if not token or token == 'your_access_token_here':
            return {'ok': False, 'error': 'BALE_TOKEN missing', 'lib': 'bale-sdk'}

        src_ref_in = str(source_channel_ref or '').strip()
        dst_ref_in = str(target_channel_ref or '').strip()
        if not src_ref_in or not dst_ref_in:
            return {'ok': False, 'error': 'channel_ref_required', 'lib': 'bale-sdk'}

        async with BaleClient(token) as client:
            me_id = int(getattr(client, '_me_id', 0) or 0)
            me_peer = Peer.user(id=me_id, access_hash=0) if me_id else None

            async def _resolve_any(ref: str, role: str, peer_id: int | None = None, title_hint: str = ''):
                """Resolve بدون SearchPeer فازی:

                1) peer_id دیتابیس
                2) SearchContacts با تطبیق دقیق nick (مثل ble.ir/name)
                3) دیالوگ‌های عضو با عنوان/nick
                """
                from bale.peer import Peer, PeerInfo

                raw = str(ref or '').strip()
                # ble.ir/linkya → linkya
                if 'ble.ir/' in raw or 'bale.ai/' in raw:
                    s = raw.replace('https://', '').replace('http://', '')
                    for prefix in ('ble.ir/', 'bale.ai/'):
                        if s.lower().startswith(prefix):
                            s = s[len(prefix):]
                            break
                    raw = s.split('/')[0].strip()

                last_err = None
                want = raw.lstrip('@').strip().lower() if raw else ''

                def _nick_of(group_or_full) -> str:
                    n = getattr(group_or_full, 'nick', None)
                    if n is None:
                        n = getattr(group_or_full, 'username', None)
                    if n is None:
                        return ''
                    if hasattr(n, 'value'):
                        n = n.value
                    return str(n or '').lstrip('@').strip().lower()

                # 1) peer_id
                if peer_id:
                    try:
                        info = PeerInfo(peer=Peer.channel(int(peer_id)))
                        full = await client.get_full(info)
                        return full, str(peer_id)
                    except Exception as e:
                        last_err = f'peer_id={peer_id}: {e}'

                if raw.lstrip('-').isdigit():
                    try:
                        info = PeerInfo(peer=Peer.channel(int(raw)))
                        full = await client.get_full(info)
                        return full, raw
                    except Exception as e:
                        last_err = f'numeric: {e}'

                # 2) SearchContacts — nick دقیق (نه SearchPeer فازی)
                if want and not want.lstrip('-').isdigit():
                    queries = [want, '@' + want]
                    if role == 'src':
                        try:
                            from orders.banner_publish import linkbank_channel
                            lb = str(linkbank_channel()).lstrip('@')
                            if lb and lb not in queries:
                                queries.append(lb)
                        except Exception:
                            pass
                    for q in queries:
                        try:
                            req = pb.SearchContactsRequest()
                            req.request = q
                            resp = await client.call(
                                'bale.users.v1.Users', 'SearchContacts', req, timeout=10.0
                            )
                            groups = list(getattr(resp, 'groups', []) or [])
                            gpeers = list(getattr(resp, 'groupPeers', []) or [])
                            # map access hash by id
                            ah_map = {}
                            for gp in gpeers:
                                try:
                                    ah_map[int(gp.groupId)] = int(gp.accessHash)
                                except Exception:
                                    pass
                            for g in groups:
                                nick = _nick_of(g)
                                gid = int(getattr(g, 'id', 0) or 0)
                                if not gid:
                                    continue
                                if nick == want or nick == q.lstrip('@').lower():
                                    ah = int(
                                        getattr(g, 'accessHash', 0)
                                        or ah_map.get(gid)
                                        or 1
                                    )
                                    peer = Peer.channel(gid, access_hash=ah)
                                    info = PeerInfo(
                                        peer=peer,
                                        title=str(getattr(g, 'title', '') or '')[:80],
                                        username=nick or want,
                                    )
                                    try:
                                        full = await client.get_full(info)
                                    except Exception:
                                        full = info
                                    return full, '@' + (nick or want)
                            last_err = (
                                f'SearchContacts q={q!r} groups='
                                f'{[(_nick_of(g), int(getattr(g,"id",0) or 0)) for g in groups][:5]}'
                            )
                        except Exception as e:
                            last_err = f'SearchContacts: {type(e).__name__}: {e}'

                # 3) دیالوگ‌ها
                title_want = (title_hint or '').strip().lower()
                if title_want or want:
                    try:
                        dialogs = await client.get_dialogs(limit=100)
                        for d in dialogs:
                            d_title = str(getattr(d, 'title', None) or '').strip()
                            peer_obj = getattr(d, 'peer', None)
                            if peer_obj is None:
                                continue
                            if not getattr(peer_obj, 'is_channel', True):
                                # فقط کانال/گروه
                                if int(getattr(peer_obj, 'type', 0) or 0) == 1:
                                    continue
                            if want:
                                try:
                                    full = await client.get_full(PeerInfo(peer=peer_obj))
                                    if _nick_of(full) == want:
                                        return full, '@' + want
                                except Exception:
                                    pass
                            if title_want and d_title and (
                                d_title.lower() == title_want
                                or title_want in d_title.lower()
                            ):
                                info = PeerInfo(peer=peer_obj, title=d_title)
                                try:
                                    full = await client.get_full(info)
                                except Exception:
                                    full = info
                                return full, f'title:{d_title}'
                        last_err = f'not in dialogs title={title_want!r} @={want}'
                    except Exception as e:
                        last_err = f'dialogs: {type(e).__name__}: {e}'

                raise LookupError(
                    f'cannot resolve {role} ref={raw!r} peer_id={peer_id} '
                    f'title={title_hint!r}: {last_err}'
                )

            async def _enrich(info):
                peer = info.peer
                steps = []
                try:
                    req_j = pb.JoinPublicGroupRequest()
                    req_j.peer.type = int(peer.type)
                    req_j.peer.id = int(peer.id)
                    await client.call(
                        'bale.groups.v1.Groups', 'JoinPublicGroup', req_j, timeout=8.0
                    )
                    steps.append('joined')
                except Exception as e:
                    steps.append(f'join:{type(e).__name__}')
                try:
                    full = await client.get_full(info)
                    steps.append(f'ah={int(full.peer.access_hash)}')
                    return full, steps
                except Exception as e:
                    steps.append(f'full:{type(e).__name__}')
                    return info, steps

            async def _load_hist(peer, lim=20):
                req = pb.LoadHistoryRequest()
                req.peer.CopyFrom(peer.to_proto())
                req.date = -1
                req.loadMode = 2
                req.limit = int(lim)
                resp = await client.call(
                    'bale.messaging.v2.Messaging', 'LoadHistory', req, timeout=12.0
                )
                return list(getattr(resp, 'history', []) or [])

            def _parse_items(hist_list):
                items = []
                for h in hist_list:
                    rid = _u64(getattr(h, 'rid', 0))
                    date = _u64(getattr(h, 'date', 0))
                    seq = _u64(getattr(h, 'seq', 0))
                    preview, kind = '', 'text'
                    try:
                        msg = h.message
                        has = getattr(msg, 'HasField', None)
                        if callable(has) and has('textMessage'):
                            preview = str(getattr(msg.textMessage, 'text', '') or '')[:200]
                        elif callable(has) and has('documentMessage'):
                            kind = 'document'
                            preview = str(getattr(msg.documentMessage, 'name', '') or '')[:200]
                    except Exception:
                        pass
                    if rid and date:
                        items.append({
                            'rid': rid, 'date': date, 'seq': seq,
                            'preview': preview, 'kind': kind,
                        })
                return items

            def _find_text(hist_list, needle: str) -> bool:
                for h in hist_list:
                    try:
                        msg = h.message
                        has = getattr(msg, 'HasField', None)
                        if callable(has) and has('textMessage'):
                            if needle in str(getattr(msg.textMessage, 'text', '') or ''):
                                return True
                    except Exception:
                        pass
                return False

            async def _forward(to_peer, from_peer, msg_rid, msg_date, msg_seq=0):
                req = pb.ForwardMessagesRequest()
                op = pb.OutPeer()
                op.type = int(to_peer.type)
                op.id = int(to_peer.id)
                op.accessHash = int(to_peer.access_hash or 1) or 1
                req.peer.CopyFrom(op)
                fwd = req.forwardedMessages.add()
                sp = pb.Peer()
                sp.type = int(from_peer.type)
                sp.id = int(from_peer.id)
                sp.accessHash = int(from_peer.access_hash or 1) or 1
                fwd.peer.CopyFrom(sp)
                fwd.rid = int(msg_rid)
                fwd.date.value = int(msg_date)
                if msg_seq:
                    fwd.seq.value = int(msg_seq)
                req.rid.append(random.getrandbits(63))
                return await client.call(
                    'bale.messaging.v2.Messaging', 'ForwardMessages', req, timeout=12.0
                )

            async def _ids(peer):
                try:
                    h = await _load_hist(peer, 15)
                    s = {_u64(getattr(x, 'rid', 0)) for x in h}
                    s.discard(0)
                    return s, h
                except Exception:
                    return set(), []

            # resolve + enrich
            try:
                src_info, src_used = await _resolve_any(src_ref_in, 'src')
                dst_info, dst_used = await _resolve_any(
                    dst_ref_in,
                    'dst',
                    peer_id=int(dst_peer_id) if dst_peer_id else None,
                    title_hint=str(dst_title or ''),
                )
            except Exception as e:
                return {
                    'ok': False,
                    'error': f'resolve: {type(e).__name__}: {e}',
                    'lib': 'bale-sdk',
                    'me_id': me_id,
                }

            src_info, src_steps = await _enrich(src_info)
            dst_info, dst_steps = await _enrich(dst_info)
            src_peer = src_info.peer
            dst_peer = dst_info.peer
            src_id = _u64(src_peer.id)
            dst_id = _u64(dst_peer.id)

            # full group diagnostics
            group_info: Dict[str, Any] = {}
            try:
                req_fg = pb.GetFullGroupRequest()
                req_fg.peer.groupId = int(dst_id)
                req_fg.peer.accessHash = int(dst_peer.access_hash or 1)
                resp_fg = await client.call(
                    'bale.groups.v1.Groups', 'GetFullGroup', req_fg, timeout=8.0
                )
                fg = resp_fg.fullGroup
                ah = _u64(getattr(fg, 'accessHash', 0))
                group_info = {
                    'ownerUid': _u64(getattr(fg, 'ownerUid', 0)),
                    'isMember': bool(getattr(fg, 'isMember', False)),
                    'accessHash': ah,
                    'title': str(getattr(fg, 'title', '') or '')[:40],
                }
                if ah:
                    dst_peer = Peer(
                        id=dst_id,
                        type=int(dst_peer.type),
                        access_hash=int(ah),
                    )
            except Exception as e:
                group_info = {'err': f'{type(e).__name__}: {e}'}

            def _is_real_ah(v: int) -> bool:
                return int(v or 0) not in (0, 1)

            ah_final = int(dst_peer.access_hash or 0)
            ah_src = 'initial'
            can_send = None

            # LoadGroups — accessHash و canSendMessage از خود گروه
            try:
                req_lg = pb.LoadGroupsRequest()
                gp = req_lg.peers.add()
                gp.groupId = int(dst_id)
                gp.accessHash = int(ah_final or 1)
                resp_lg = await client.call(
                    'bale.groups.v1.Groups', 'LoadGroups', req_lg, timeout=10.0
                )
                for g in list(getattr(resp_lg, 'groups', []) or []):
                    if int(getattr(g, 'id', 0) or 0) == int(dst_id):
                        cand = int(getattr(g, 'accessHash', 0) or 0)
                        can_send = bool(getattr(g, 'canSendMessage', False))
                        group_info['canSendMessage'] = can_send
                        group_info['groupType'] = int(getattr(g, 'groupType', 0) or 0)
                        if _is_real_ah(cand):
                            ah_final = cand
                            ah_src = 'LoadGroups'
                        break
            except Exception as e:
                group_info['ah_lg_err'] = f'{type(e).__name__}: {e}'

            # JoinPublicGroup response.group.accessHash
            if not _is_real_ah(ah_final):
                try:
                    req_j = pb.JoinPublicGroupRequest()
                    req_j.peer.type = int(dst_peer.type)
                    req_j.peer.id = int(dst_id)
                    resp_j = await client.call(
                        'bale.groups.v1.Groups', 'JoinPublicGroup', req_j, timeout=8.0
                    )
                    g = getattr(resp_j, 'group', None)
                    if g is not None:
                        cand = int(getattr(g, 'accessHash', 0) or 0)
                        if _is_real_ah(cand):
                            ah_final = cand
                            ah_src = 'JoinPublicGroup'
                except Exception as e:
                    group_info['ah_join_err'] = f'{type(e).__name__}: {e}'

            # dialogs
            if not _is_real_ah(ah_final):
                try:
                    for d in await client.get_dialogs(limit=120):
                        p = getattr(d, 'peer', None)
                        if p is not None and int(p.id) == int(dst_id):
                            cand = int(getattr(p, 'access_hash', 0) or 0)
                            if _is_real_ah(cand):
                                ah_final = cand
                                ah_src = 'dialogs'
                                break
                except Exception as e:
                    group_info['ah_dialogs_err'] = f'{type(e).__name__}: {e}'

            if not ah_final:
                ah_final = 1
                ah_src = 'sentinel_1'

            dst_peer = Peer(
                id=int(dst_id),
                type=int(dst_peer.type),
                access_hash=int(ah_final),
            )
            group_info['accessHash'] = int(ah_final)
            group_info['ah_source'] = ah_src

            src_ah = int(src_peer.access_hash or 0) or 1
            try:
                req_lg2 = pb.LoadGroupsRequest()
                gp2 = req_lg2.peers.add()
                gp2.groupId = int(src_id)
                gp2.accessHash = int(src_ah)
                resp_lg2 = await client.call(
                    'bale.groups.v1.Groups', 'LoadGroups', req_lg2, timeout=10.0
                )
                for g in list(getattr(resp_lg2, 'groups', []) or []):
                    if int(getattr(g, 'id', 0) or 0) == int(src_id):
                        cand = int(getattr(g, 'accessHash', 0) or 0)
                        if _is_real_ah(cand):
                            src_ah = cand
                        break
            except Exception:
                pass
            src_peer = Peer(
                id=int(src_id),
                type=int(src_peer.type),
                access_hash=int(src_ah or 1),
            )

            # member permissions
            perms_info: Dict[str, Any] = {}
            if me_id:
                try:
                    req_p = pb.GetMemberPermissionsRequest()
                    req_p.group.groupId = int(dst_id)
                    req_p.group.accessHash = int(dst_peer.access_hash or 1)
                    req_p.user.uid = int(me_id)
                    req_p.user.accessHash = 0
                    resp_p = await client.call(
                        'bale.groups.v1.Groups', 'GetMemberPermissions', req_p, timeout=8.0
                    )
                    p = resp_p.permissions
                    def _pb_bool(v):
                        if v is None:
                            return False
                        if isinstance(v, bool):
                            return v
                        return bool(getattr(v, 'value', False))
                    perms_info = {
                        'sendMessage': bool(getattr(p, 'sendMessage', False)),
                        'sendForwardedMessage': _pb_bool(
                            getattr(p, 'sendForwardedMessage', None)
                        ),
                        'sendMedia': _pb_bool(getattr(p, 'sendMedia', None)),
                    }
                except Exception as e:
                    perms_info = {'err': f'{type(e).__name__}: {e}'}

            # pick banner from linkbank
            try:
                src_hist = await _load_hist(src_peer, limit)
            except Exception as e:
                return {
                    'ok': False,
                    'error': f'LoadHistory_src: {type(e).__name__}: {e}',
                    'lib': 'bale-sdk',
                    'me_id': me_id,
                }
            items = _parse_items(src_hist)
            if not items:
                return {
                    'ok': False,
                    'error': 'history_empty',
                    'lib': 'bale-sdk',
                    'me_id': me_id,
                    'src_ref': src_used,
                }

            key = (caption_match or '').strip()[:40]
            chosen = None
            if key:
                for it in items:
                    if key in str(it.get('preview') or ''):
                        chosen = it
                        break
            if chosen is None:
                for it in items:
                    if it.get('kind') == 'document':
                        chosen = it
                        break
            if chosen is None:
                chosen = items[0]

            rid = int(chosen['rid'])
            date = int(chosen['date'])
            seq = int(chosen.get('seq') or 0)
            date_list = [date]
            if date > 10_000_000_000:
                date_list.append(date // 1000)
            elif date > 1_000_000_000:
                date_list.append(date * 1000)

            errors: List[str] = []
            path_used = None

            # ===== مسیر A: لینک‌بانک → me → کانال =====
            if me_peer is not None:
                me_before, _ = await _ids(me_peer)
                for dval in date_list:
                    try:
                        await _forward(me_peer, src_peer, rid, dval, seq)
                        await asyncio.sleep(2.0)
                        me_after, me_hist = await _ids(me_peer)
                        new_on_me = me_after - me_before
                        new_on_me.discard(0)
                        # پیدا کردن پیام جدید روی me
                        hop = None
                        for h in me_hist:
                            hr = _u64(getattr(h, 'rid', 0))
                            if hr in new_on_me or (not new_on_me and hr):
                                hop = {
                                    'rid': hr,
                                    'date': _u64(getattr(h, 'date', 0)),
                                    'seq': _u64(getattr(h, 'seq', 0)),
                                }
                                if hr in new_on_me:
                                    break
                        if not hop and me_hist:
                            h0 = me_hist[0]
                            hop = {
                                'rid': _u64(getattr(h0, 'rid', 0)),
                                'date': _u64(getattr(h0, 'date', 0)),
                                'seq': _u64(getattr(h0, 'seq', 0)),
                            }
                        if hop and hop['rid']:
                            dst_before, _ = await _ids(dst_peer)
                            await _forward(
                                dst_peer, me_peer, hop['rid'], hop['date'], hop.get('seq') or 0
                            )
                            await asyncio.sleep(2.0)
                            dst_after, _ = await _ids(dst_peer)
                            new_dst = dst_after - dst_before
                            new_dst.discard(0)
                            if new_dst:
                                return {
                                    'ok': True,
                                    'method': 'forward_via_self_hop',
                                    'lib': 'bale-sdk',
                                    'me_id': me_id,
                                    'message_id': hop['rid'],
                                    'message_date': hop['date'],
                                    'verified': True,
                                    'new_rids': list(new_dst)[:5],
                                    'src_ref': src_used,
                                    'dst_ref': dst_used,
                                    'direction': f'{src_used}→me→{dst_used}',
                                    'group_info': group_info,
                                    'perms': perms_info,
                                }
                            errors.append(
                                f'self_hop d={dval}: on_me={bool(new_on_me)} '
                                f'on_dst=False hop={hop}'
                            )
                        else:
                            errors.append(f'self_hop d={dval}: not_on_me')
                    except Exception as e:
                        errors.append(f'self_hop d={dval}: {type(e).__name__}: {e}')

            # ===== مسیر B: مستقیم لینک‌بانک → کانال =====
            dst_before, _ = await _ids(dst_peer)
            for dval in date_list:
                try:
                    await _forward(dst_peer, src_peer, rid, dval, seq)
                    await asyncio.sleep(2.0)
                    dst_after, _ = await _ids(dst_peer)
                    new_dst = dst_after - dst_before
                    new_dst.discard(0)
                    if new_dst:
                        return {
                            'ok': True,
                            'method': 'forward_direct',
                            'lib': 'bale-sdk',
                            'me_id': me_id,
                            'verified': True,
                            'new_rids': list(new_dst)[:5],
                            'src_ref': src_used,
                            'dst_ref': dst_used,
                            'direction': f'{src_used}→{dst_used}',
                        }
                    errors.append(f'direct d={dval}: no_new')
                except Exception as e:
                    errors.append(f'direct d={dval}: {type(e).__name__}: {e}')

            # probe: self + raw SendMessage to channel with final access_hash
            marker = f'[ly-probe-{int(_time.time())}]'
            write_probe: Dict[str, Any] = {
                'marker': marker,
                'me_id': me_id,
                'dst_ah_used': int(dst_peer.access_hash),
            }
            try:
                r1 = await client.send_message(me_peer, marker + '-self') if me_peer else None
                write_probe['self'] = {'seq': _u64(getattr(r1, 'seq', 0)) if r1 else 0}
            except Exception as e:
                write_probe['self'] = {'err': str(e)}
            try:
                # raw SendMessage مثل مسیر موفق self
                req_sm = pb.SendMessageRequest()
                req_sm.peer.CopyFrom(dst_peer.to_proto())
                req_sm.exPeer.CopyFrom(dst_peer.to_out_proto())
                req_sm.rid = random.getrandbits(63)
                req_sm.message.textMessage.text = marker + '-ch'
                r2 = await client.call(
                    'bale.messaging.v2.Messaging', 'SendMessage', req_sm, timeout=10.0
                )
                write_probe['ch_api'] = {
                    'seq': _u64(getattr(r2, 'seq', 0)),
                    'date': _u64(getattr(r2, 'date', 0)),
                    'raw': str(r2)[:80],
                }
                await asyncio.sleep(2.5)
                h_dst = await _load_hist(dst_peer, 12)
                write_probe['in_dst'] = _find_text(h_dst, marker)
                write_probe['dst_n'] = len(h_dst)
            except Exception as e:
                write_probe['ch_api'] = {'err': f'{type(e).__name__}: {e}'}
                write_probe['in_dst'] = False

            return {
                'ok': False,
                'error': 'linkyar_cannot_post_to_channel',
                'lib': 'bale-sdk',
                'me_id': me_id,
                'tries': errors[:8],
                'message_id': rid,
                'message_date': date,
                'src_id': src_id,
                'dst_id': dst_id,
                'src_ref': src_used,
                'dst_ref': dst_used,
                'direction': f'{src_used}({src_id}) → {dst_used}({dst_id})',
                'group_info': group_info,
                'perms': perms_info,
                'src_steps': src_steps,
                'dst_steps': dst_steps,
                'write_probe': write_probe,
                'hint': (
                    f'me={me_id} ownerUid={group_info.get("ownerUid")} '
                    f'isMember={group_info.get("isMember")} '
                    f'sendMessage={perms_info.get("sendMessage")} '
                    f'sendForwarded={perms_info.get("sendForwardedMessage")}'
                ),
            }

    return _run(_fn())



def _forward_via_aiobale_stack(
    target_channel_ref: str,
    source_channel_ref: str,
    *,
    caption_match: str = '',
    limit: int = 40,
) -> Dict[str, Any]:
    """مسیر baleclient/aiobale (fallback)."""

    async def _fn(client):
        from aiobale.enums import ChatType, ListLoadMode, PeerType
        from aiobale.types import InfoMessage, Peer
        from aiobale.types.values import IntValue

        lib_name = _BALE_LIB_NAME or 'unknown'
        errors: List[str] = []

        src = await _resolve_peer(client, source_channel_ref)
        if not src.get('ok'):
            return {'ok': False, 'error': f'source_resolve: {src.get("error")}', 'lib': lib_name}
        src_id = int(src['peer_id'])
        src_ah = src.get('access_hash')
        try:
            await client.join_public_chat(src_id)
        except Exception:
            pass
        if src_ah in (None, 0, '0'):
            try:
                src_ah = await _enrich_access_hash(client, src_id, None)
            except Exception:
                pass

        tgt = await _resolve_peer(client, target_channel_ref)
        if not tgt.get('ok'):
            return {'ok': False, 'error': f'target_resolve: {tgt.get("error")}', 'lib': lib_name}
        tgt_id = int(tgt['peer_id'])
        try:
            await client.join_public_chat(tgt_id)
        except Exception:
            pass

        loaded = []
        for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
            try:
                msgs = await client.load_history(
                    src_id, ctype, limit=int(limit), offset_date=-1,
                    load_mode=ListLoadMode.BACKWARD,
                )
                if msgs:
                    loaded = list(msgs)
                    break
            except Exception as e:
                errors.append(f'load_history/{ctype}: {type(e).__name__}: {e}')

        if loaded:
            chosen = loaded[0]
            for msg in loaded:
                try:
                    c = getattr(msg, 'content', None)
                    if c is not None and getattr(c, 'document', None) is not None:
                        chosen = msg
                        break
                except Exception:
                    pass
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    resp = await client.forward_message(
                        message=chosen, chat_id=tgt_id, chat_type=ctype
                    )
                    return {
                        'ok': True,
                        'result': str(resp),
                        'method': 'forward_message_Message',
                        'lib': lib_name,
                        'chat_type': str(ctype),
                        'message_id': int(getattr(chosen, 'message_id', 0) or 0),
                        'message_date': int(getattr(chosen, 'date', 0) or 0),
                    }
                except Exception as e:
                    errors.append(f'fwd_msg/{ctype}: {type(e).__name__}: {e}')

        return {
            'ok': False,
            'error': 'forward_failed',
            'lib': lib_name,
            'tries': errors[:10],
        }

    return _run(_with_client(_fn))



def forward_to_channel(
    channel_ref: str,
    from_peer_id: int,
    message_id: int,
    message_date: int,
    from_peer_type: int = 2,
    from_access_hash: int | None = None,
    source_channel_ref: str | None = None,
) -> Dict[str, Any]:
    """فوروارد واقعی. access_hash مبدأ اجباری است (از @username کانال مرجع)."""
    async def _fn(client):
        from aiobale.enums import ChatType, PeerType
        from aiobale.types import InfoMessage, Peer
        from aiobale.methods.messaging.forward_message import ForwardMessages
        from aiobale.utils import generate_id

        # --- مقصد ---
        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error'), 'where': 'resolve_target'}
        target_id = int(resolved['peer_id'])
        target_ah = resolved.get('access_hash')
        try:
            await client.join_public_chat(target_id)
        except Exception:
            pass

        # --- مبدأ: حتماً با username لینک‌بانک resolve کن تا access_hash بیاید ---
        src_id = int(from_peer_id)
        src_ah = int(from_access_hash) if from_access_hash not in (None, '', 0, '0') else None

        # همیشه username مرجع را resolve کن (شناسه عددی AH ندارد)
        for ref_try in (
            source_channel_ref,
            (source_channel_ref or '').lstrip('@') if source_channel_ref else None,
            '@' + (source_channel_ref or '').lstrip('@') if source_channel_ref else None,
        ):
            if not ref_try or str(ref_try).lstrip('-').isdigit():
                continue
            src_res = await _resolve_peer(client, str(ref_try))
            if src_res.get('ok'):
                if src_res.get('peer_id'):
                    src_id = int(src_res['peer_id'])
                ah = src_res.get('access_hash')
                if ah not in (None, 0, '0'):
                    src_ah = int(ah)
                    break

        if src_ah is None:
            return {
                'ok': False,
                'error': 'missing_source_access_hash',
                'hint': 'resolve @username کانال مرجع برای access_hash لازم است',
                'src_peer': src_id,
                'source_channel_ref': source_channel_ref,
            }

        try:
            await client.join_public_chat(src_id)
        except Exception:
            pass

        md = int(message_date or 0)
        dates = [md]
        if md > 10_000_000_000:
            dates.append(md // 1000)
        elif 0 < md < 10_000_000_000:
            dates.append(md * 1000)

        errors: List[str] = []
        src_peer = Peer(type=PeerType.GROUP, id=src_id, access_hash=int(src_ah))

        for d in dates:
            info = InfoMessage(
                peer=src_peer,
                message_id=int(message_id),
                date=int(d),
            )
            for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
                try:
                    resp = await client.forward_message(
                        message=info, chat_id=target_id, chat_type=ctype
                    )
                    return {
                        'ok': True,
                        'result': str(resp),
                        'method': 'client.forward_message',
                        'chat_type': str(ctype),
                        'date_used': int(d),
                        'message_id': int(message_id),
                        'message_date': int(d),
                        'src_access_hash': True,
                    }
                except Exception as e:
                    errors.append(f'high/{ctype}/d={d}: {type(e).__name__}: {e}')

                try:
                    tgt = Peer(
                        type=PeerType.GROUP,
                        id=target_id,
                        **({'access_hash': int(target_ah)} if target_ah not in (None, 0) else {}),
                    )
                    call = ForwardMessages(
                        peer=tgt,
                        message_ids=[generate_id()],
                        forwarded_messages=[info],
                    )
                    resp = await client(call)
                    return {
                        'ok': True,
                        'result': str(resp),
                        'method': 'ForwardMessages',
                        'chat_type': str(ctype),
                        'date_used': int(d),
                        'message_id': int(message_id),
                        'message_date': int(d),
                        'src_access_hash': True,
                    }
                except Exception as e:
                    errors.append(f'raw/{ctype}/d={d}: {type(e).__name__}: {e}')

        return {
            'ok': False,
            'error': 'InvalidArgument' if any('InvalidArgument' in x for x in errors) else 'forward_failed',
            'tries': errors[:12],
            'src_peer': src_id,
            'src_ah': src_ah,
            'target': target_id,
            'mid': int(message_id),
            'dates_tried': dates,
        }

    return _run(_with_client(_fn))


def send_existing_file_to_channel(
    channel_ref: str,
    *,
    file_id: Any,
    file_access_hash: int,
    file_size: int = 0,
    file_name: str = 'banner.jpg',
    mime_type: str = 'image/jpeg',
    caption: str = '',
    kind: str = 'photo',
) -> Dict[str, Any]:
    """ارسال همان فایل سرور بله (بدون دانلود مجدد) — معادل copy بدون نقل‌قول."""
    async def _fn(client):
        from aiobale.enums import ChatType, PeerType
        from aiobale.types import (
            Chat,
            Peer,
            MessageContent,
            DocumentMessage,
            MessageCaption,
            DocumentsExt,
            PhotoExt,
            VideoExt,
        )
        from aiobale.methods.messaging.send_message import SendMessage
        from aiobale.utils import generate_id

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error')}
        peer_id = int(resolved['peer_id'])
        access_hash = resolved.get('access_hash')
        try:
            await client.join_public_chat(peer_id)
        except Exception:
            pass

        cap = MessageCaption(content=caption) if caption else None
        ext = None
        if kind == 'photo':
            ext = DocumentsExt(photo=PhotoExt(w=1000, h=1000))
        elif kind == 'video':
            try:
                ext = DocumentsExt(video=VideoExt(w=1280, h=720))
            except Exception:
                ext = None

        document = DocumentMessage(
            file_id=file_id,
            size=int(file_size or 0),
            name=file_name or 'banner.jpg',
            mime_type=mime_type or 'image/jpeg',
            access_hash=int(file_access_hash),
            caption=cap,
            ext=ext,
        )
        content = MessageContent(document=document)
        errors = []
        for ctype in (ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPER_GROUP):
            peer_kwargs: Dict[str, Any] = {'type': PeerType.GROUP, 'id': peer_id}
            if access_hash not in (None, 0):
                peer_kwargs['access_hash'] = int(access_hash)
            peer = Peer(**peer_kwargs)
            chat = Chat(id=peer_id, type=ctype)
            mid = generate_id()
            call = SendMessage(peer=peer, message_id=mid, content=content, chat=chat)
            try:
                result = await client(call)
                msg = getattr(result, 'message', result)
                return {
                    'ok': True,
                    'message_id': getattr(msg, 'message_id', mid),
                    'date': getattr(msg, 'date', None),
                    'method': 'send_existing_file',
                    'chat_type': str(ctype),
                }
            except Exception as e:
                errors.append(f'{ctype}: {type(e).__name__}: {e}')
        return {'ok': False, 'error': 'send_existing_failed', 'tries': errors}

    return _run(_with_client(_fn))



def delete_channel_message(
    channel_ref: str, message_id: int, message_date: int
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
                return {'ok': True, 'result': str(resp)}
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
    """کپی/فوروارد کامل پیام (رسانه + متن).

    شناسه Bot API با شناسه داخلی لینک‌یار یکی نیست؛ اگر date نباشد از تاریخچه
    مبدأ با تطبیق id یا نزدیک‌ترین پست رسانه‌ای بازیابی می‌شود.
    """
    try:
        from_peer = int(str(from_chat_id)) if str(from_chat_id).lstrip('-').isdigit() else 0
    except ValueError:
        from_peer = 0
    md = int(message_date or 0)
    resolved_mid = int(message_id)

    if not from_peer or not md:
        try:
            hist = load_channel_history(str(from_chat_id), limit=100)
            if hist.get('ok'):
                if not from_peer and hist.get('peer_id'):
                    try:
                        from_peer = int(hist['peer_id'])
                    except (TypeError, ValueError):
                        pass
                posts = list(hist.get('messages') or hist.get('posts') or [])
                # 1) تطبیق دقیق message_id
                for post in posts:
                    try:
                        if int(post.get('message_id') or 0) == int(message_id):
                            md = int(post.get('date') or 0) or md
                            resolved_mid = int(post.get('message_id') or message_id)
                            break
                    except (TypeError, ValueError):
                        continue
                # 2) اگر id بات با داخلی یکی نبود: آخرین پست دارای رسانه
                if not md and posts:
                    for post in posts:
                        try:
                            pmid = int(post.get('message_id') or 0)
                            pdate = int(post.get('date') or 0)
                        except (TypeError, ValueError):
                            continue
                        if not pmid or not pdate:
                            continue
                        # اولویت به پست‌هایی که عکس/ویدیو دارند
                        kind = str(post.get('kind') or post.get('type') or post.get('media') or '')
                        has_media = bool(post.get('has_media') or post.get('photo') or post.get('video') or 'photo' in kind.lower() or 'video' in kind.lower())
                        if has_media or not any(p.get('has_media') or p.get('photo') for p in posts if isinstance(p, dict)):
                            md = pdate
                            resolved_mid = pmid
                            if has_media:
                                break
                    # اگر هنوز هیچ: اولین پست معتبر
                    if not md:
                        for post in posts:
                            try:
                                pmid = int(post.get('message_id') or 0)
                                pdate = int(post.get('date') or 0)
                            except (TypeError, ValueError):
                                continue
                            if pmid and pdate:
                                md = pdate
                                resolved_mid = pmid
                                break
        except Exception as e:
            logger.warning('copy_message history resolve failed: %s', e)

    if not from_peer or not md:
        return {
            'ok': False,
            'error': 'need_from_peer_and_date',
            'hint': 'تاریخ/شناسه مبدأ برای فوروارد پیدا نشد.',
            'from_chat_id': str(from_chat_id),
            'message_id': int(message_id),
        }

    last: Dict[str, Any] = {'ok': False, 'error': 'forward_failed'}
    for ptype in (2, 1):
        result = forward_to_channel(
            str(to_chat_id),
            from_peer_id=from_peer,
            message_id=int(resolved_mid),
            message_date=int(md),
            from_peer_type=ptype,
        )
        last = result if isinstance(result, dict) else last
        if result.get('ok'):
            result['message_date'] = int(md)
            result['from_peer_id'] = from_peer
            result['resolved_message_id'] = int(resolved_mid)
            return result
    return last


def forward_message(
    to_chat_id: str, from_chat_id: str, message_id: int, message_date: int = 0
) -> Dict[str, Any]:
    return copy_message(to_chat_id, from_chat_id, message_id, message_date=message_date)


def _named_int(value: Any, names: tuple, depth: int = 0) -> Optional[int]:
    if depth > 5 or value is None:
        return None
    if hasattr(value, 'model_dump'):
        try:
            value = value.model_dump()
        except Exception:
            value = None
    if isinstance(value, dict):
        for name in names:
            raw = value.get(name)
            if isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return int(raw)
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
        for child in value.values():
            found = _named_int(child, names, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)) and depth < 3:
        for child in value[:8]:
            found = _named_int(child, names, depth + 1)
            if found is not None:
                return found
    return None


def _named_str(value: Any, names: tuple, depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ''
    if hasattr(value, 'model_dump'):
        try:
            value = value.model_dump()
        except Exception:
            return ''
    if isinstance(value, dict):
        for name in names:
            raw = value.get(name)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for child in value.values():
            found = _named_str(child, names, depth + 1)
            if found:
                return found
    return ''


async def _fill_post_views(client, peer_id: int, posts: List[Dict[str, Any]]) -> Optional[str]:
    """بازدید هر پست از get_messages_views. شناسهٔ عددی به‌تنهایی برای این متد کافی نیست."""
    from aiobale.types import OtherMessage

    others = []
    slots = []
    for index, post in enumerate(posts):
        mid = post.get('message_id')
        date = post.get('date')
        if isinstance(mid, int) and isinstance(date, int):
            others.append(OtherMessage(date=int(date), message_id=int(mid)))
            slots.append(index)
    if not others:
        return None
    try:
        payload = await client.get_messages_views(others, peer_id)
    except Exception as e:
        return f'{type(e).__name__}: {e}'[:300]
    numbers: List[Optional[int]] = []
    for row in payload or []:
        count = getattr(row, 'views', None)
        if not isinstance(count, int):
            count = _named_int(row, ('views', 'view', 'views_count', 'view_count'))
        numbers.append(count if isinstance(count, int) else None)
    for slot, count in zip(slots, numbers):
        if isinstance(count, int):
            posts[slot]['views'] = count
    return None


def _admin_flag(perms: Any) -> Optional[bool]:
    data = perms.model_dump() if hasattr(perms, 'model_dump') else perms
    if not isinstance(data, dict) or not data:
        return None

    def _flag(key: str) -> bool:
        value = data.get(key)
        if isinstance(value, dict):
            return bool(value.get('value') or value.get('1'))
        return bool(value)

    return bool(_flag('send_message') or _flag('send_media'))


async def _read_full_group(client, peer_id: int):
    errors: List[str] = []
    for call in (
        lambda: client.get_full_group(peer_id),
        lambda: client.get_full_group(group_id=peer_id),
    ):
        try:
            full = await call()
            return full, None
        except Exception as e:
            errors.append(f'{type(e).__name__}: {e}')
    return None, '; '.join(errors)[:300]


def collect_channel_stats(channel_ref: str, limit: int = 30) -> Dict[str, Any]:
    """اعضا از get_full_group و بازدید از تاریخچه + get_messages_views.

    هر دو متد روی حساب کاربری لینک‌یار (aiobale) هستند، نه فرم مدیر و نه Bot API.
    """

    async def _fn(client):
        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error') or 'resolve_failed', 'resolved': resolved}

        peer_id = int(resolved['peer_id'])
        access_hash = resolved.get('access_hash')
        uname = str(channel_ref).lstrip('@') if not str(channel_ref).lstrip('-').isdigit() else ''
        try:
            await client.join_public_chat(peer_id)
        except Exception as e:
            logger.info('join before stats: %s', e)

        full, group_error = await _read_full_group(client, peer_id)
        members = _named_int(
            full,
            ('members_count', 'member_count', 'members', 'participants_count', 'users_count'),
        )
        about = _named_str(full, ('about', 'description', 'bio'))
        title = resolved.get('title') or _named_str(full, ('title', 'name'))

        raw = await _load_history_raw(client, peer_id, access_hash, limit=int(limit))
        posts: List[Dict[str, Any]] = []
        if raw.get('ok'):
            for item in raw.get('items') or []:
                parsed = _parse_raw_message_item(item, uname)
                if not parsed:
                    continue
                posts.append(
                    {
                        'message_id': parsed['message_id'],
                        'date': parsed.get('date'),
                        'views': _named_int(item, ('views', 'view', 'views_count', 'view_count')),
                        'forwards': _named_int(item, ('forwards', 'forward_count', 'forwards_count')) or 0,
                    }
                )

        views_error = await _fill_post_views(client, peer_id, posts)
        linkyar_is_admin = None
        try:
            perms = await client.get_member_permissions(peer_id, client.id)
            linkyar_is_admin = _admin_flag(perms)
        except Exception as e:
            logger.info('linkyar admin during stats: %s', type(e).__name__)

        if members is None and not any(isinstance(p.get('views'), int) for p in posts):
            return {
                'ok': False,
                'error': group_error or views_error or raw.get('error') or 'no_stats',
                'peer_id': peer_id,
                'group_error': group_error,
                'views_error': views_error,
                'linkyar_is_admin': linkyar_is_admin,
            }

        return {
            'ok': True,
            'peer_id': peer_id,
            'title': title,
            'about': about,
            'members': members,
            'posts': posts,
            'group_error': group_error,
            'views_error': views_error,
            'linkyar_is_admin': linkyar_is_admin,
        }

    return _run(_with_client(_fn))
