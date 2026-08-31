"""Extra mini-app endpoints (catalog, order actions, operator payouts)."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from channels_app.models import Tariff
from miniapp.api import _auth_user, _json_body
from orders.models import OrderItem
from wallet import services as ws
from wallet.models import PayoutRequest


@csrf_exempt
@require_http_methods(['GET'])
def api_catalog(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    qs = Tariff.objects.filter(is_active=True).select_related('channel', 'group').order_by('price', 'id')[:80]
    items = []
    for t in qs:
        items.append({
            'id': t.id,
            'name': t.name,
            'price': t.price,
            'duration_hours': t.duration_hours,
            'start_hour': t.start_hour,
            'is_active': t.is_active,
            'owner': t.group.name if t.group_id else (t.channel.name if t.channel_id else ''),
            'channel_id': t.channel_id,
            'group_id': t.group_id,
        })
    return JsonResponse({'ok': True, 'tariffs': items})


def _set_item_status(request: HttpRequest, status: str) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    it = OrderItem.objects.filter(id=body.get('item_id'), manager=user).first()
    if not it:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    if it.manager_status != 'pending':
        return JsonResponse({'ok': False, 'error': 'not_pending'}, status=400)
    it.manager_status = status
    it.save(update_fields=['manager_status'])
    return JsonResponse({'ok': True, 'item_id': it.id, 'manager_status': it.manager_status})


@csrf_exempt
@require_http_methods(['POST'])
def api_order_approve(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'approved')


@csrf_exempt
@require_http_methods(['POST'])
def api_order_reject(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'rejected')


@csrf_exempt
@require_http_methods(['GET'])
def api_operator_payouts(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    rows = []
    for p in PayoutRequest.objects.filter(status='pending').order_by('id')[:100]:
        rows.append({
            'id': p.id,
            'amount_toman': p.amount_toman,
            'iban': p.iban,
            'holder_name': getattr(p, 'holder_name', '') or '',
            'status': p.status,
        })
    return JsonResponse({'ok': True, 'payouts': rows})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_mark_paid(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    n = 0
    for p in PayoutRequest.objects.filter(status='pending'):
        p.status = 'paid'
        p.save(update_fields=['status'])
        n += 1
    return JsonResponse({'ok': True, 'marked': n})
