"""Server-persisted banner draft: one active draft per customer."""
from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from orders.models import BannerSubmissionDraft, CustomerBusiness

_ALLOWED = {'mode', 'title', 'caption', 'business_id'}

def _payload(value):
    if not isinstance(value, dict):
        return None
    mode = str(value.get('mode') or 'media').lower()
    if mode not in ('media', 'text'):
        return None
    title = str(value.get('title') or '').strip()[:120]
    caption = str(value.get('caption') or '')[:800]
    raw_business = value.get('business_id')
    try:
        business_id = int(raw_business) if raw_business not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        return None
    return {'mode': mode, 'title': title, 'caption': caption, 'business_id': business_id}

@csrf_exempt
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_banner_draft(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if request.method == 'GET':
        draft = BannerSubmissionDraft.objects.filter(customer=user, is_active=True).first()
        payload = draft.payload if draft else None
        if payload is not None:
            from orders.banner_media import banner_draft_file
            media = banner_draft_file(user.pk)
            payload = dict(payload)
            payload['has_media'] = bool(media and media.is_file())
            if media and media.is_file():
                payload['media_file_name'] = payload.get('media_file_name') or media.name
        return JsonResponse({'ok': True, 'draft': payload, 'revision': draft.revision if draft else 0})
    if request.method == 'DELETE':
        with transaction.atomic():
            draft = BannerSubmissionDraft.objects.select_for_update().filter(customer=user, is_active=True).first()
            if draft:
                draft.is_active = False
                draft.payload = {}
                draft.revision += 1
                draft.save(update_fields=['is_active', 'payload', 'revision', 'updated_at'])
        from orders.banner_media import clear_banner_draft_media
        clear_banner_draft_media(user.pk)
        return JsonResponse({'ok': True, 'cancelled': True})

    from orders.banner_media import save_banner_draft_upload
    is_multipart = 'multipart/form-data' in (request.content_type or '').lower()
    if is_multipart:
        body = {
            'mode': request.POST.get('mode', 'media'),
            'title': request.POST.get('title', ''),
            'caption': request.POST.get('caption', ''),
            'business_id': request.POST.get('business_id', ''),
        }
    else:
        body = _json_body(request)
    clean = _payload(body.get('draft', body))
    if clean is None:
        return JsonResponse({'ok': False, 'error': 'bad_draft', 'message': 'اطلاعات پیش‌نویس معتبر نیست.'}, status=400)
    business_id = clean.get('business_id')
    if business_id and not CustomerBusiness.objects.filter(id=business_id, customer=user, is_deleted=False).exists():
        return JsonResponse({'ok': False, 'error': 'bad_business', 'message': 'کسب‌وکار انتخاب‌شده معتبر نیست.'}, status=400)
    upload = request.FILES.get('file') if is_multipart else None
    if upload is not None:
        media_path, media_kind = save_banner_draft_upload(user.pk, upload)
        if media_path is None:
            status = 413 if media_kind == 'file_too_large' else 400
            msg = 'حجم فایل حداکثر باید ۱۵ مگابایت باشد.' if media_kind == 'file_too_large' else 'فقط فایل تصویر یا ویدیوی معتبر پذیرفته می‌شود.'
            return JsonResponse({'ok': False, 'error': media_kind, 'message': msg}, status=status)
        clean.update({'has_media': True, 'media_file_name': str(upload.name or media_path.name)[:255], 'media_kind': media_kind})
    with transaction.atomic():
        draft = BannerSubmissionDraft.objects.select_for_update().filter(customer=user).first()
        # Text edits must retain a previously uploaded media file unless explicitly cleared.
        if draft and draft.is_active and upload is None:
            for field in ('has_media', 'media_file_name', 'media_kind'):
                if field not in clean and field in (draft.payload or {}):
                    clean[field] = draft.payload[field]
        if draft is None:
            draft = BannerSubmissionDraft.objects.create(customer=user, payload=clean, is_active=True)
        else:
            draft.payload = clean
            draft.is_active = True
            draft.revision += 1
            draft.save(update_fields=['payload', 'is_active', 'revision', 'updated_at'])
    return JsonResponse({'ok': True, 'draft': draft.payload, 'revision': draft.revision, 'locked': True})
