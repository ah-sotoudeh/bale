"""Customer business profiles and their independent category selections."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, HttpRequest, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from orders.models import CustomerBusiness

logger = logging.getLogger(__name__)


def _normalize_bale_ref(value: str) -> str:
    value = re.sub(r'^https?://', '', str(value or '').strip(), flags=re.I)
    value = value.split('?', 1)[0].split('#', 1)[0]
    return value.strip().strip('/').strip()[:255]


def _bale_ref_key(value: str) -> str:
    """Canonical comparison key, so @name, name, and ble.ir/name are one channel."""
    normalized = _normalize_bale_ref(value).lower().strip()
    normalized = normalized.lstrip('@')
    for host in ('ble.ir/', 'bale.ai/'):
        if normalized.startswith(host):
            normalized = normalized[len(host):]
            break
    return normalized.strip('/')


def _store_business_avatar(business: CustomerBusiness, metadata: dict) -> str:
    """Download the public Bale channel photo to local media without exposing bot tokens."""
    try:
        raw = metadata.get('raw') if isinstance(metadata, dict) else None
        photo = raw.get('photo') if isinstance(raw, dict) else None
        if not isinstance(photo, dict):
            return business.avatar_url or ''
        file_id = str(photo.get('big_file_id') or photo.get('small_file_id') or '').strip()
        if not file_id:
            return business.avatar_url or ''
        from integrations import bale_client as bc
        info = bc.get_file(file_id)
        file_path = str((info.get('result') or {}).get('file_path') or '') if isinstance(info, dict) else ''
        if not file_path:
            return business.avatar_url or ''
        data = bc.download_file_bytes(file_path)
        if not data or len(data) > 2 * 1024 * 1024:
            return business.avatar_url or ''
        if data.startswith(b'\xff\xd8\xff'):
            ext = '.jpg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            ext = '.png'
        elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
            ext = '.gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            ext = '.webp'
        else:
            return business.avatar_url or ''
        folder = Path(settings.MEDIA_ROOT) / 'business_avatars'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'{int(business.id)}{ext}'
        for old in folder.glob(f'{int(business.id)}.*'):
            if old != target and old.is_file():
                old.unlink(missing_ok=True)
        target.write_bytes(data)
        url = f'/miniapp/api/businesses/{int(business.id)}/avatar'
        if business.avatar_url != url:
            business.avatar_url = url
            business.save(update_fields=['avatar_url', 'updated_at'])
        return url
    except Exception:
        logger.exception('business avatar refresh failed for business=%s', getattr(business, 'id', '?'))
        return business.avatar_url or ''


@require_http_methods(['GET'])
def api_business_avatar(request: HttpRequest, business_id: int) -> HttpResponse:
    """Public channel avatar file. The stored local path contains no provider token."""
    business = CustomerBusiness.objects.filter(id=business_id, is_deleted=False).only('id').first()
    if business is None:
        return HttpResponse(status=404)
    folder = Path(settings.MEDIA_ROOT) / 'business_avatars'
    path = next((p for p in folder.glob(f'{int(business_id)}.*') if p.is_file()), None) if folder.is_dir() else None
    if path is None:
        return HttpResponse(status=404)
    content_types = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
    response = FileResponse(path.open('rb'), content_type=content_types.get(path.suffix.lower(), 'application/octet-stream'))
    response['Cache-Control'] = 'public, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _categories(value):
    if not isinstance(value, dict):
        return {'main': [], 'sub': []}
    main = value.get('main', [])
    sub = value.get('sub', [])
    if not isinstance(main, list) or not isinstance(sub, list):
        return None
    # Keep identifiers as short strings; do not infer subcategories from main categories.
    main = list(dict.fromkeys(str(x).strip()[:80] for x in main if str(x).strip()))
    sub = list(dict.fromkeys(str(x).strip()[:100] for x in sub if str(x).strip()))
    if len(main) > 30 or len(sub) > 100:
        return None
    return {'main': main, 'sub': sub}


def _row(b):
    return {
        'id': b.id,
        'kind': b.kind,
        'source_ref': b.source_ref,
        'name': b.name,
        'avatar_url': b.avatar_url,
        'categories': b.categories or {'main': [], 'sub': []},
        'info_source': b.info_source,
        'info_checked_at': b.info_checked_at.isoformat() if b.info_checked_at else '',
        'created_at': b.created_at.isoformat(),
        'updated_at': b.updated_at.isoformat(),
        'banner_count': b.banners.filter(is_active=True).count(),
    }


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_businesses(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if request.method == 'GET':
        rows = CustomerBusiness.objects.filter(customer=user, is_deleted=False)
        return JsonResponse({'ok': True, 'businesses': [_row(b) for b in rows]})

    body = _json_body(request)
    name = str(body.get('name') or '').strip()[:160]
    kind = str(body.get('kind') or 'bale').strip().lower()
    source_ref = str(body.get('source_ref') or '').strip()[:255]
    avatar_url = str(body.get('avatar_url') or '').strip()[:1000]
    categories = _categories(body.get('categories', {}))
    if kind not in ('bale', 'external'):
        return JsonResponse({'ok': False, 'error': 'bad_kind', 'message': 'نوع کسب‌وکار نامعتبر است.'}, status=400)
    if not name:
        return JsonResponse({'ok': False, 'error': 'name_required', 'message': 'نام کسب‌وکار را وارد کنید.'}, status=400)
    if categories is None or not categories['main']:
        return JsonResponse({'ok': False, 'error': 'categories_required', 'message': 'حداقل یک دسته‌بندی اصلی انتخاب کنید.'}, status=400)
    if kind == 'bale' and source_ref:
        normalized = _normalize_bale_ref(source_ref)
        candidate_key = _bale_ref_key(normalized)
        existing = next((row for row in CustomerBusiness.objects.filter(
            customer=user, kind='bale', is_deleted=False
        ) if _bale_ref_key(row.source_ref) == candidate_key), None)
        if existing:
            return JsonResponse({'ok': False, 'error': 'already_exists', 'business': _row(existing), 'message': 'این کانال قبلاً در کسب‌وکارهای شما ثبت شده است.'}, status=409)
        source_ref = normalized
    from django.utils import timezone
    is_auto = kind == 'bale' and body.get('info_source') == 'auto'
    # Store the latest metadata-attempt time, including an unsuccessful attempt, so
    # auto-refresh can be limited to once per day without preventing an explicit retry.
    attempted = kind == 'bale' and bool(source_ref) and bool(body.get('metadata_attempted'))
    b = CustomerBusiness.objects.create(
        customer=user, kind=kind, source_ref=source_ref, name=name,
        avatar_url=avatar_url, categories=categories,
        info_source='auto' if is_auto else 'manual',
        info_checked_at=timezone.now() if (is_auto or attempted) else None,
    )
    return JsonResponse({'ok': True, 'business': _row(b)}, status=201)


@csrf_exempt
@require_http_methods(['POST', 'PATCH'])
def api_business_update(request: HttpRequest, business_id: int) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    b = CustomerBusiness.objects.filter(id=business_id, customer=user, is_deleted=False).first()
    if not b:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کسب‌وکار پیدا نشد.'}, status=404)
    body = _json_body(request)
    fields = []
    if 'name' in body:
        name = str(body.get('name') or '').strip()[:160]
        if not name:
            return JsonResponse({'ok': False, 'error': 'name_required', 'message': 'نام کسب‌وکار نمی‌تواند خالی باشد.'}, status=400)
        b.name = name
        fields.append('name')
    if 'avatar_url' in body:
        b.avatar_url = str(body.get('avatar_url') or '').strip()[:1000]
        fields.append('avatar_url')
    if 'source_ref' in body and b.kind == 'bale':
        new_ref = _normalize_bale_ref(str(body.get('source_ref') or ''))
        if _bale_ref_key(new_ref) != _bale_ref_key(b.source_ref):
            # A changed channel key must be looked up again immediately; do not let the
            # old channel's 24-hour metadata cooldown suppress this new lookup.
            from django.utils import timezone
            b.info_checked_at = None
            b.info_source = 'manual'
            fields.extend(['info_checked_at', 'info_source'])
        b.source_ref = new_ref
        fields.append('source_ref')
    if 'categories' in body:
        categories = _categories(body.get('categories'))
        if categories is None or not categories['main']:
            return JsonResponse({'ok': False, 'error': 'categories_required', 'message': 'حداقل یک دسته‌بندی اصلی انتخاب کنید.'}, status=400)
        b.categories = categories
        fields.append('categories')
    if fields:
        fields.append('updated_at')
        b.save(update_fields=fields)
    return JsonResponse({'ok': True, 'business': _row(b)})


@csrf_exempt
@require_http_methods(['POST'])
def api_business_delete(request: HttpRequest, business_id: int) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    b = CustomerBusiness.objects.filter(id=business_id, customer=user, is_deleted=False).first()
    if not b:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کسب‌وکار پیدا نشد.'}, status=404)
    # Soft-delete: preserve banners and historical orders; a later re-registration is a fresh profile.
    b.is_deleted = True
    b.save(update_fields=['is_deleted', 'updated_at'])
    return JsonResponse({'ok': True, 'business_id': b.id, 'deleted': True, 'message': 'کسب‌وکار از فهرست شما حذف شد؛ بنرها و سفارش‌های قبلی حفظ می‌شوند.'})


@csrf_exempt
@require_http_methods(['POST'])
def api_business_metadata(request: HttpRequest) -> JsonResponse:
    """Refresh Bale metadata with a daily cooldown; an explicit force retry bypasses it."""
    from datetime import timedelta
    from django.utils import timezone
    from integrations.bale_client import get_channel_info

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    source_ref = str(body.get('source_ref') or '').strip()[:255]
    business_id = body.get('business_id')
    force = str(body.get('force') or '').lower() in ('1', 'true', 'yes') or body.get('force') is True
    business = None
    if business_id not in (None, '', 0, '0'):
        try:
            business = CustomerBusiness.objects.filter(id=int(business_id), customer=user, is_deleted=False).first()
        except (TypeError, ValueError):
            business = None
        if business is None:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کسب‌وکار پیدا نشد.'}, status=404)
        if business.kind != 'bale':
            return JsonResponse({'ok': False, 'error': 'not_bale_business', 'message': 'این کسب‌وکار کانال بله نیست.'}, status=400)
        supplied_ref = _normalize_bale_ref(source_ref) if source_ref else ''
        current_ref = _normalize_bale_ref(business.source_ref)
        source_changed = bool(supplied_ref and _bale_ref_key(supplied_ref) != _bale_ref_key(current_ref))
        source_ref = supplied_ref or business.source_ref
        if (not force and not source_changed and business.info_checked_at and
                business.info_checked_at >= timezone.now() - timedelta(hours=24)):
            return JsonResponse({'ok': True, 'skipped': True, 'business': _row(business),
                                 'message': 'اطلاعات این کانال طی ۲۴ ساعت گذشته بررسی شده است.'})
    if not source_ref:
        return JsonResponse({'ok': False, 'error': 'source_ref_required', 'message': 'لینک یا شناسه کانال را وارد کنید.'}, status=400)
    # Accept @username and common Bale channel links; remove tracking query/fragment.
    normalized = _normalize_bale_ref(source_ref)
    key = normalized.rsplit('/', 1)[-1].lstrip('@')
    if not key or any(x in key for x in (' ', '?', '#')):
        return JsonResponse({'ok': False, 'error': 'bad_source_ref', 'message': 'لینک یا شناسه کانال معتبر نیست.'}, status=400)
    attempted_at = timezone.now()
    try:
        result = get_channel_info('@' + key)
    except Exception:
        result = {'error': 'metadata_exception'}
    title = str((result or {}).get('title') or '').strip() if isinstance(result, dict) else ''
    if not title or title == '(no title)' or (isinstance(result, dict) and result.get('error')):
        # Record failed attempts too, but never overwrite name, avatar, categories, banners, or orders.
        if business is not None:
            business.info_checked_at = attempted_at
            business.save(update_fields=['info_checked_at', 'updated_at'])
        return JsonResponse({'ok': False, 'error': 'metadata_unavailable', 'source_ref': normalized,
                             'metadata_attempted': True,
                             'message': 'اطلاعات کانال دریافت نشد.'}, status=200)
    if business is not None:
        # Update metadata only; independent categories and all historical records survive.
        business.name = title[:160]
        business.source_ref = normalized
        business.info_source = 'auto'
        business.info_checked_at = attempted_at
        business.save(update_fields=['name', 'source_ref', 'info_source', 'info_checked_at', 'updated_at'])
        avatar_url = _store_business_avatar(business, result if isinstance(result, dict) else {})
        return JsonResponse({'ok': True, 'business': _row(business),
                             'metadata': {'name': title, 'avatar_url': avatar_url, 'source_ref': normalized}})
    return JsonResponse({'ok': True, 'metadata': {'name': title, 'avatar_url': '', 'source_ref': normalized}})
