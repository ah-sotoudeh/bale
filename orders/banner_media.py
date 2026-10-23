"""بنر روی دیسک، بدون ستون تازه. نام فایل همان شناسهٔ بنر است."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from django.conf import settings

from orders.models import CustomerBanner

logger = logging.getLogger(__name__)

_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
_VIDEO_EXT = {'.mp4', '.webm'}
_MEDIA_EXT = _IMAGE_EXT | _VIDEO_EXT
_MISS_TTL = 3600


def banner_draft_dir() -> Path:
    path = Path(settings.BASE_DIR) / 'media' / 'banner_drafts'
    path.mkdir(parents=True, exist_ok=True)
    return path


def banner_draft_file(customer_id: int) -> Path | None:
    """Return the one safe persisted media file for an unfinished customer draft."""
    root = banner_draft_dir()
    files = [x for x in root.glob(f'{int(customer_id)}.*') if x.is_file()]
    return max(files, key=lambda x: x.stat().st_mtime) if files else None


def save_banner_draft_upload(customer_id: int, upload) -> tuple[Path | None, str]:
    """Store a draft upload using a numeric owner name and an allow-listed extension."""
    import mimetypes
    import os
    import uuid

    allowed = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.webm'}
    if getattr(upload, 'size', 0) > 15 * 1024 * 1024:
        return None, 'file_too_large'
    name = Path(str(getattr(upload, 'name', '') or '')).name
    ext = Path(name).suffix.lower()
    content_type = str(getattr(upload, 'content_type', '') or '').lower()
    if ext not in allowed:
        ext = mimetypes.guess_extension(content_type) or ''
        if ext == '.jpe':
            ext = '.jpg'
    if ext not in allowed or not (content_type.startswith('image/') or content_type.startswith('video/')):
        return None, 'bad_media'
    root = banner_draft_dir()
    tmp = root / f'.{int(customer_id)}-{uuid.uuid4().hex}.tmp'
    final = root / f'{int(customer_id)}{ext}'
    size = 0
    try:
        with tmp.open('wb') as out:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > 15 * 1024 * 1024:
                    out.close()
                    tmp.unlink(missing_ok=True)
                    return None, 'file_too_large'
                out.write(chunk)
        with tmp.open('rb') as src:
            head = src.read(32)
        is_image = (
            head.startswith(b'\xff\xd8\xff')
            or head.startswith(b'\x89PNG\r\n\x1a\n')
            or head.startswith((b'GIF87a', b'GIF89a'))
            or (ext == '.webp' and head[:4] == b'RIFF' and head[8:12] == b'WEBP')
        )
        is_video = b'ftyp' in head[:32] or head.startswith(b'\x1a\x45\xdf\xa3')
        if not (is_image or is_video):
            tmp.unlink(missing_ok=True)
            return None, 'bad_media'
        for old in root.glob(f'{int(customer_id)}.*'):
            if old.is_file():
                old.unlink(missing_ok=True)
        os.replace(tmp, final)
        return final, ('video' if is_video else 'photo')
    except OSError:
        tmp.unlink(missing_ok=True)
        logger.exception('saving banner draft media failed')
        return None, 'bad_media'


def clear_banner_draft_media(customer_id: int) -> None:
    try:
        for path in banner_draft_dir().glob(f'{int(customer_id)}.*'):
            if path.is_file():
                path.unlink(missing_ok=True)
    except OSError:
        logger.exception('clearing banner draft media failed')



def banner_dir() -> Path:
    path = Path(settings.BASE_DIR) / 'media' / 'banners'
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_from_message(message: dict) -> tuple[str, str]:
    if not isinstance(message, dict):
        return '', ''
    photos = message.get('photo') or []
    if isinstance(photos, list) and photos:
        best = photos[-1] if isinstance(photos[-1], dict) else {}
        fid = str(best.get('file_id') or '')
        return (fid, 'photo') if fid else ('', '')
    for key, kind in (('video', 'video'), ('animation', 'animation')):
        media = message.get(key) or {}
        if isinstance(media, dict) and media.get('file_id'):
            return str(media['file_id']), kind
    document = message.get('document') or {}
    if isinstance(document, dict) and document.get('file_id'):
        return str(document['file_id']), 'document'
    return '', ''


def stored_banner_file(banner_id: int) -> Path | None:
    root = Path(settings.BASE_DIR) / 'media' / 'banners'
    if not root.is_dir():
        return None
    found = [
        path
        for path in root.glob(f'{int(banner_id)}.*')
        if path.suffix.lower() in _MEDIA_EXT and path.is_file() and path.stat().st_size >= 32
    ]
    if not found:
        return None
    found.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return found[0]


def content_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
    }.get(ext, 'application/octet-stream')


def public_media_url(banner: CustomerBanner) -> str:
    if ensure_local_file(banner) is None:
        return ''
    return f'/miniapp/api/banners/{int(banner.id)}/media'


def file_for_request(banner_id: int) -> tuple[Path, str] | None:
    banner = CustomerBanner.objects.filter(id=int(banner_id), is_active=True).first()
    if banner is None:
        return None
    path = ensure_local_file(banner)
    if path is None:
        return None
    return path, content_type_for(path)


def save_banner_from_message(banner_id: int, message: dict) -> Path | None:
    file_id, kind = file_from_message(message)
    if not file_id:
        return None
    return _download(int(banner_id), file_id, kind)


def ensure_local_file(banner: CustomerBanner) -> Path | None:
    found = stored_banner_file(banner.id)
    if found is not None:
        return found
    if (banner.media_kind or '') not in ('photo', 'video', 'animation', 'document', ''):
        # allow empty media_kind for linkbank banners
        if not (banner.from_linkbank and banner.linkbank_message_id):
            return None
    path = _pull_stored_message(banner)
    if path is not None:
        return path
    return _pull_linkbank_message(banner)


def _pull_linkbank_message(banner: CustomerBanner) -> Path | None:
    """دانلود بنر از کانال مرجع لینک‌بانک با بات (برای ارسال لینک‌یار)."""
    mid = str(banner.linkbank_message_id or '').strip()
    if not mid.isdigit():
        return None
    chat = str(banner.linkbank_chat_id or '').strip()
    if not chat:
        try:
            from orders.banner_publish import linkbank_channel
            chat = linkbank_channel()
        except Exception:
            return None
    from integrations import bale_client as bc
    if not bc._token():
        return None
    root = banner_dir()
    miss = root / f'{int(banner.id)}.lb.miss'
    if miss.is_file() and time.time() - miss.stat().st_mtime < _MISS_TTL:
        return None
    # فوروارد به خود بات برای گرفتن file_id
    me = bc.get_me()
    bot_id = (me.get('result') or me).get('id') if isinstance(me, dict) else None
    target = str(bot_id or chat)
    sent = bc.forward_message(target, chat, int(mid))
    message = sent.get('result') if isinstance(sent, dict) else None
    if not isinstance(message, dict):
        # امتحان مستقیم به storage_chat
        if banner.storage_chat_id:
            sent = bc.forward_message(str(banner.storage_chat_id), chat, int(mid))
            message = sent.get('result') if isinstance(sent, dict) else None
    if not isinstance(message, dict):
        miss.write_bytes(b'')
        return None
    saved = None
    try:
        file_id, kind = file_from_message(message)
        saved = _download(banner.id, file_id, kind or banner.media_kind or 'photo')
    finally:
        del_mid = message.get('message_id')
        del_chat = str(message.get('chat', {}).get('id') or target)
        if del_mid:
            try:
                bc.delete_message(del_chat, int(del_mid))
            except Exception:
                pass
    if saved is None:
        miss.write_bytes(b'')
    return saved


def _looks_like_media(data: bytes, kind: str) -> str:
    if len(data) < 32:
        return ''
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'GIF8'):
        return '.gif'
    if data.startswith(b'RIFF') and b'WEBP' in data[:16]:
        return '.webp'
    if b'ftyp' in data[:16]:
        return '.mp4'
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        return '.webm'
    if kind in ('video', 'animation'):
        return '.mp4'
    return ''


def _save_bytes(banner_id: int, data: bytes, kind: str) -> Path | None:
    ext = _looks_like_media(data, kind)
    if not ext:
        return None
    root = banner_dir()
    for old in root.glob(f'{int(banner_id)}.*'):
        if old.suffix.lower() in _MEDIA_EXT and old.suffix.lower() != ext:
            old.unlink(missing_ok=True)
    dest = root / f'{int(banner_id)}{ext}'
    dest.write_bytes(data)
    miss = root / f'{int(banner_id)}.miss'
    miss.unlink(missing_ok=True)
    return dest


def _download(banner_id: int, file_id: str, kind: str) -> Path | None:
    if not file_id:
        return None
    from integrations import bale_client as bc

    if not bc._token():
        return None
    meta = bc.get_file(file_id)
    file_path = str((meta.get('result') or {}).get('file_path') or '') if isinstance(meta, dict) else ''
    if not file_path:
        return None
    data = bc.download_file_bytes(file_path)
    if not data:
        return None
    return _save_bytes(banner_id, data, kind)


def _pull_stored_message(banner: CustomerBanner) -> Path | None:
    if not str(banner.storage_message_id or '').isdigit():
        return None
    chat_id = str(banner.storage_chat_id or '').strip()
    if not chat_id:
        return None
    from integrations import bale_client as bc

    if not bc._token():
        return None
    root = banner_dir()
    miss = root / f'{int(banner.id)}.miss'
    if miss.is_file() and time.time() - miss.stat().st_mtime < _MISS_TTL:
        return None
    sent = bc.forward_message(chat_id, chat_id, int(banner.storage_message_id))
    message = sent.get('result') if isinstance(sent, dict) else None
    if not isinstance(message, dict):
        miss.write_bytes(b'')
        return None
    saved = None
    try:
        file_id, kind = file_from_message(message)
        saved = _download(banner.id, file_id, kind or banner.media_kind or '')
    finally:
        mid = message.get('message_id')
        if mid:
            try:
                bc.delete_message(chat_id, int(mid))
            except Exception:
                logger.exception('delete forwarded banner copy')
    if saved is None:
        miss.write_bytes(b'')
    return saved


def save_uploaded_bytes(banner_id: int, data: bytes, kind: str = 'photo') -> Path | None:
    """ذخیرهٔ فایل آپلودشده از مینی‌اپ (بدون file_id بله)."""
    if not data:
        return None
    return _save_bytes(int(banner_id), data, kind or 'photo')


def materialize_banner_file(banner) -> 'Path | None':
    """مسیر فایل محلی بنر (دیسک، storage یا لینک‌بانک)."""
    found = stored_banner_file(int(banner.id))
    if found is not None:
        return found
    path = _pull_stored_message(banner)
    if path is not None:
        return path
    return _pull_linkbank_message(banner)
