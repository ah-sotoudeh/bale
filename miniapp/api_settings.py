"""تنظیمات سامانه برای پنل پشتیبان."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from users import access as ws


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_operator_settings(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    from config.system_settings import get_settings, update_settings

    if request.method == 'GET':
        return JsonResponse({'ok': True, 'settings': get_settings()})
    body = _json_body(request) or {}
    patch = body.get('settings') if isinstance(body.get('settings'), dict) else body
    updated = update_settings(patch or {})
    return JsonResponse({'ok': True, 'settings': updated})



@csrf_exempt
@require_http_methods(['GET'])
def api_public_pay_info(request: HttpRequest) -> JsonResponse:
    """اطلاعات کارت‌به‌کارت برای مشتری (بدون نیاز به نقش پشتیبان)."""
    user, err = _auth_user(request)
    if err:
        return err
    from config.system_settings import public_card_info, get_settings
    s = get_settings()
    return JsonResponse({
        'ok': True,
        'card': public_card_info(),
        'min_topup_toman': s.get('min_topup_toman'),
        'max_topup_toman': s.get('max_topup_toman'),
    })
