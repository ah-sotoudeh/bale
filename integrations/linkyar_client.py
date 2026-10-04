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
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_runner).result(timeout=180)
        except RuntimeError:
            return _runner()
    except ModuleNotFoundError:
        logger.warning('aiobale نصب نیست؛ کار لینک‌یار انجام نشد.')
        return {'ok': False, 'error': 'aiobale_missing'}


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


def forward_to_channel(
    channel_ref: str,
    from_peer_id: int,
    message_id: int,
    message_date: int,
    from_peer_type: int = 2,
) -> Dict[str, Any]:
    """فوروارد پیام کانال مبدأ به کانال مقصد. چند ترکیب peer/chat را امتحان می‌کند."""
    async def _fn(client):
        from aiobale.enums import ChatType, PeerType
        from aiobale.types import InfoMessage, Peer

        resolved = await _resolve_peer(client, channel_ref)
        if not resolved.get('ok'):
            return {'ok': False, 'error': resolved.get('error')}
        peer_id = int(resolved['peer_id'])

        # peer type مبدأ: کانال‌ها معمولاً GROUP
        peer_types = []
        for name in ('GROUP', 'CHANNEL', 'PRIVATE'):
            if hasattr(PeerType, name):
                peer_types.append(getattr(PeerType, name))
        if not peer_types:
            peer_types = [2]

        chat_types = []
        for name in ('GROUP', 'CHANNEL'):
            if hasattr(ChatType, name):
                chat_types.append(getattr(ChatType, name))
        if not chat_types:
            chat_types = [ChatType.GROUP]

        # تاریخ: هم ms هم sec (اگر خیلی بزرگ بود)
        dates = [int(message_date)]
        md = int(message_date or 0)
        if md > 10_000_000_000:  # ms
            dates.append(md // 1000)
        elif md > 0:
            dates.append(md * 1000)

        errors = []
        for ptype in peer_types:
            for ctype in chat_types:
                for d in dates:
                    try:
                        info = InfoMessage(
                            peer=Peer(id=int(from_peer_id), type=ptype),
                            message_id=int(message_id),
                            date=int(d),
                        )
                        resp = await client.forward_message(
                            message=info, chat_id=peer_id, chat_type=ctype
                        )
                        return {
                            'ok': True,
                            'result': str(resp),
                            'from_peer_type': str(ptype),
                            'chat_type': str(ctype),
                            'date_used': int(d),
                            'message_id': int(message_id),
                            'message_date': int(d),
                        }
                    except Exception as e:
                        errors.append(f'{ptype}/{ctype}/d={d}: {type(e).__name__}: {e}')
        return {
            'ok': False,
            'error': 'InvalidArgument' if any('InvalidArgument' in x for x in errors) else 'forward_failed',
            'tries': errors[:12],
        }

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
