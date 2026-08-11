"""لینک‌یار = حساب کاربری شخصی via aiobale + BALE_TOKEN.

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
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_runner).result(timeout=180)
    except RuntimeError:
        return _runner()


async def _with_client(async_fn):
    from aiobale import Client

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


async def _resolve_peer(client, channel_ref: str) -> Dict[str, Any]:
    ref = str(channel_ref).strip()
    if ref.lstrip('-').isdigit():
        return {'ok': True, 'peer_id': int(ref), 'access_hash': None, 'source': 'numeric'}

    uname = ref.lstrip('@')
    sc = await _search_contact_raw(client, uname)
    if sc.get('ok'):
        return sc

    try:
        resp = await client.search_username(uname)
        g = getattr(resp, 'group', None)
        if g is not None and getattr(g, 'id', None):
            return {
                'ok': True,
                'peer_id': int(g.id),
                'access_hash': int(getattr(g, 'access_hash', 0) or 0) or None,
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
            name = doc.get(4) or doc.get('4')
            if isinstance(name, dict):
                name = str(name)
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
        'permalink': permalink,
        'raw_keys': list(item.keys()) if isinstance(item, dict) else None,
    }


async def _load_history_raw(
    client,
    peer_id: int,
    access_hash: Optional[int],
    limit: int = 6,
) -> Dict[str, Any]:
    """Call LoadHistory and decode without pydantic MessageContent validation."""
    from aiobale.enums import PeerType, ListLoadMode, Services
    from aiobale.utils import clean_grpc
    from aiobale.utils.grpc_post import add_header
    import aiohttp

    session = client.session
    if not session.session or session.session.closed:
        session.session = aiohttp.ClientSession()

    peer: Dict[str, Any] = {'1': int(PeerType.GROUP), '2': int(peer_id)}
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


def is_admin_of_channel(channel_ref: str) -> bool:
    d = diagnose_channel(channel_ref)
    perms = d.get('permissions') or {}
    if not isinstance(perms, dict):
        return False

    def _b(key):
        v = perms.get(key)
        if isinstance(v, dict):
            return bool(v.get('value') or v.get('1'))
        return bool(v)

    return _b('send_message') or _b('send_media')


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


async def _send_text_raw(client, peer_id: int, access_hash: Optional[int], text: str) -> Dict[str, Any]:
    from aiobale.enums import ChatType, PeerType
    from aiobale.types import Chat, Peer, MessageContent, TextMessage
    from aiobale.methods.messaging.send_message import SendMessage
    from aiobale.utils import generate_id

    errors: List[str] = []
    mid = generate_id()
    content = MessageContent(text=TextMessage(value=text))
    combos = [
        (PeerType.GROUP, ChatType.GROUP),
        (PeerType.GROUP, ChatType.CHANNEL),
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
            result = await client(call)
            msg = getattr(result, 'message', result)
            return {
                'ok': True,
                'message_id': getattr(msg, 'message_id', mid),
                'date': getattr(msg, 'date', None),
                'peer_id': peer_id,
                'combo': f'{ptype}/{ctype}',
                'without_quote': True,
            }
        except Exception as e:
            errors.append(f'{ptype}/{ctype}: {e}')

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


def forward_to_channel(
    channel_ref: str,
    from_peer_id: int,
    message_id: int,
    message_date: int,
    from_peer_type: int = 1,
) -> Dict[str, Any]:
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
            message=info, chat_id=peer_id, chat_type=ChatType.GROUP
        )
        return {'ok': True, 'result': str(resp), 'without_quote': False}

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
    try:
        from_peer = int(str(from_chat_id)) if str(from_chat_id).lstrip('-').isdigit() else 0
    except ValueError:
        from_peer = 0
    if not from_peer or not message_date:
        if caption:
            return send_text_to_channel(str(to_chat_id), caption)
        return {'ok': False, 'error': 'need_from_peer_and_date'}
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
