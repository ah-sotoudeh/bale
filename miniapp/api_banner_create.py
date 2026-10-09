"""Customer banner create from mini-app upload."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from orders.models import CustomerBanner


def _err(code: str, status: int = 400, message: str = '') -> JsonResponse:
    from bot_flow.messages import user_error
    ERR = {
        'need_media': 'تصویر یا ویدیو را انتخاب کنید.',
        'caption_short': 'متن بنر کوتاه است. چند خط درباره کالا بنویسید.',
        'banned': 'متن شامل عبارت غیرمجاز است.',
        'file_too_large': 'حجم فایل زیاد است. حداکثر ۱۵ مگابایت.',
        'bad_media': 'فقط تصویر یا ویدیو پذیرفته می‌شود.',
    }
    text = message or ERR.get(code) or user_error(code)
    return JsonResponse({'ok': False, 'error': code, 'message': text}, status=status)


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_create(request: HttpRequest) -> JsonResponse:
    """ساخت بنر از مینی‌اپ — آپلود فایل (multipart یا base64). رایگان. اعلان به پشتیبان از بازو."""
    import base64

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None

    from bot_flow.banned_words import is_allowed
    from orders.banner_media import public_media_url, save_uploaded_bytes
    from orders.banner_publish import banner_stage, create_publish_request

    title = ''
    caption = ''
    media_kind = 'photo'
    raw: bytes = b''

    ctype = (request.content_type or '').lower()
    if 'multipart/form-data' in ctype:
        title = str(request.POST.get('title') or '').strip()[:120]
        caption = str(request.POST.get('caption') or '').strip()[:800]
        media_kind = str(request.POST.get('media_kind') or 'photo').strip().lower() or 'photo'
        up = request.FILES.get('file') or request.FILES.get('media')
        if up is not None:
            raw = up.read()
            ct = (getattr(up, 'content_type', '') or '').lower()
            if ct.startswith('video'):
                media_kind = 'video'
            elif ct.startswith('image'):
                media_kind = 'photo'
    else:
        body = _json_body(request)
        title = str(body.get('title') or '').strip()[:120]
        caption = str(body.get('caption') or '').strip()[:800]
        media_kind = str(body.get('media_kind') or 'photo').strip().lower() or 'photo'
        b64 = body.get('media_base64') or body.get('file_base64') or ''
        if isinstance(b64, str) and b64:
            if ',' in b64 and b64.strip().startswith('data:'):
                b64 = b64.split(',', 1)[1]
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return _err('bad_media')

    if len(caption) < 12:
        return _err('caption_short')
    ok, _hits = is_allowed(caption)
    if not ok:
        return _err('banned')
    if title:
        ok, _hits = is_allowed(title)
        if not ok:
            return _err('banned')
    if not raw:
        return _err('need_media')
    if len(raw) > 15 * 1024 * 1024:
        return _err('file_too_large')

    if media_kind not in ('photo', 'video', 'animation', 'document'):
        media_kind = 'photo'
    head = raw[:12]
    if head.startswith(b'\xff\xd8\xff') or head[:8] == b'\x89PNG\r\n\x1a\n':
        media_kind = 'photo'
    elif b'ftyp' in raw[:32]:
        media_kind = 'video'

    if not title:
        title = caption.split('\n', 1)[0][:80]

    banner = CustomerBanner.objects.create(
        customer=user,
        title=title,
        caption=caption,
        storage_chat_id='miniapp',
        storage_message_id='pending',
        from_linkbank=False,
        media_kind=media_kind,
    )
    banner.storage_message_id = str(banner.id)
    banner.save(update_fields=['storage_message_id'])

    path = save_uploaded_bytes(banner.id, raw, media_kind)
    if path is None:
        banner.is_active = False
        banner.save(update_fields=['is_active'])
        return _err('bad_media')

    result = create_publish_request(
        user,
        storage_chat_id='miniapp',
        storage_message_id=str(banner.id),
        caption=caption,
        media_kind=media_kind,
        banner=banner,
    )
    stage = banner_stage(banner)
    req = result.get('request')
    return JsonResponse({
        'ok': True,
        'banner_id': banner.id,
        'stage': stage,
        'title': banner.display_title(),
        'fee': 0,
        'media_url': public_media_url(banner),
        'request_id': getattr(req, 'id', None),
    })
