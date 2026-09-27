"""API endpoints for manager mini-app."""
from __future__ import annotations

import json
import logging
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot_flow.jalali import format_jalali
from channels_app.models import Channel, ChannelGroup, Tariff
from miniapp.auth import validate_init_data
from orders.availability import free_days_for_tariff, mark_external_busy
from orders.models import OrderItem
from users.models import User
from wallet import services as ws
from wallet.models import BankAccount, PayoutRequest

logger = logging.getLogger(__name__)


def _json_body(request: HttpRequest) -> Dict[str, Any]:
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return {}


def _init_from_request(request: HttpRequest) -> str:
    body = _json_body(request) if request.method == 'POST' else {}
    return (
        request.headers.get('X-Bale-Init-Data')
        or request.META.get('HTTP_X_BALE_INIT_DATA')
        or body.get('initData')
        or request.GET.get('initData')
        or ''
    )


def _auth_user(request: HttpRequest) -> tuple[Optional[User], Optional[JsonResponse]]:
    init_data = _init_from_request(request)
    ok, payload = validate_init_data(init_data)
    if not ok:
        from miniapp.auth import allow_debug_auth

        if allow_debug_auth():
            debug_id = request.GET.get('debug_bale_id') or _json_body(request).get('debug_bale_id')
            if debug_id:
                user, _ = User.objects.get_or_create(
                    bale_user_id=str(debug_id),
                    defaults={'username': f'mini_{debug_id}'[:30]},
                )
                return user, None
        return None, JsonResponse({'ok': False, 'error': payload.get('error') or 'unauthorized'}, status=401)

    uid = str((payload.get('user') or {}).get('id') or '')
    if not uid:
        return None, JsonResponse({'ok': False, 'error': 'no_user'}, status=401)

    user = User.objects.filter(bale_user_id=uid).first()
    if not user:
        uname = (payload.get('user') or {}).get('username') or f'bale_{uid}'
        user = User(username=str(uname)[:30], bale_user_id=uid)
        user.set_unusable_password()
        user.bale_username = (payload.get('user') or {}).get('username')
        user.save()
    return user, None


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_me(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    br = ws.balance_breakdown(user)
    ch_count = Channel.objects.filter(manager=user).count()
    is_op = ws.is_operator(user.bale_user_id or '')
    return JsonResponse({
        'ok': True,
        'user': {
            'id': user.id,
            'bale_user_id': user.bale_user_id,
            'handle': user.bale_handle,
            'username': user.bale_username,
        },
        'wallet': br,
        'is_operator': is_op,
        'channel_count': ch_count,
        'can_be_manager': True,
        'roles': {
            'manager': True,
            'customer': True,
            'operator': is_op,
        },
        'pending_orders': OrderItem.objects.filter(manager=user, manager_status='pending').count(),
    })
