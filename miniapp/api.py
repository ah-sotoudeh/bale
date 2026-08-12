"""API endpoints for manager mini-app."""
from __future__ import annotations

import json
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
        # dev fallback: ?debug_bale_id= when ALLOW_MINIAPP_DEBUG=1 (no DEBUG required)
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
    return JsonResponse({
        'ok': True,
        'user': {
            'id': user.id,
            'bale_user_id': user.bale_user_id,
            'handle': user.bale_handle,
            'username': user.bale_username,
        },
        'wallet': br,
        'is_operator': ws.is_operator(user.bale_user_id or ''),
        'channel_count': Channel.objects.filter(manager=user).count(),
        'pending_orders': OrderItem.objects.filter(manager=user, manager_status='pending').count(),
    })


@csrf_exempt
@require_http_methods(['GET'])
def api_channels(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    channels = []
    for ch in Channel.objects.filter(manager=user).order_by('id'):
        channels.append({
            'id': ch.id,
            'name': ch.name,
            'link': ch.link,
            'publish_mode': ch.publish_mode,
            'publish_mode_label': ch.publish_mode_label,
            'bot_is_admin': ch.bot_is_admin,
            'linkyar_is_admin': ch.linkyar_is_admin,
            'tariff_count': ch.tariffs.count(),
        })
    groups = []
    for g in ChannelGroup.objects.filter(manager=user).order_by('id'):
        groups.append({
            'id': g.id,
            'name': g.name,
            'channel_count': g.channel_count,
            'tariff_count': g.tariffs.count(),
            'channel_ids': list(g.channels.values_list('id', flat=True)),
        })
    return JsonResponse({'ok': True, 'channels': channels, 'groups': groups})


@csrf_exempt
@require_http_methods(['POST'])
def api_set_publish_mode(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    mode = body.get('publish_mode')
    if mode not in (Channel.PUBLISH_BOT, Channel.PUBLISH_LINKYAR, Channel.PUBLISH_MANUAL):
        return JsonResponse({'ok': False, 'error': 'bad_mode'}, status=400)
    ch.publish_mode = mode
    ch.save(update_fields=['publish_mode'])
    return JsonResponse({'ok': True, 'channel_id': ch.id, 'publish_mode': ch.publish_mode})


@csrf_exempt
@require_http_methods(['GET'])
def api_tariffs(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    from django.db.models import Q

    qs = Tariff.objects.filter(Q(channel__manager=user) | Q(group__manager=user)).select_related(
        'channel', 'group'
    ).order_by('-id')[:50]
    items = []
    for t in qs:
        items.append({
            'id': t.id,
            'name': t.name,
            'price': t.price,
            'duration_hours': t.duration_hours,
            'start_hour': t.start_hour,
            'is_active': t.is_active,
            'owner': t.group.name if t.group_id else (t.channel.name if t.channel_id else '?'),
            'channel_id': t.channel_id,
            'group_id': t.group_id,
        })
    return JsonResponse({'ok': True, 'tariffs': items})


@csrf_exempt
@require_http_methods(['POST'])
def api_add_tariff(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'channel_not_found'}, status=404)
    try:
        name = str(body.get('name') or '').strip()[:100]
        duration = int(body.get('duration_hours'))
        price = int(body.get('price'))
        start_hour = body.get('start_hour')
        start_hour = int(start_hour) if start_hour is not None and str(start_hour) != '' else None
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad_fields'}, status=400)
    if not name or duration <= 0 or price < 0:
        return JsonResponse({'ok': False, 'error': 'bad_fields'}, status=400)
    t = Tariff.objects.create(
        channel=ch,
        name=name,
        duration_hours=duration,
        price=price,
        start_hour=start_hour,
        is_active=True,
    )
    return JsonResponse({'ok': True, 'tariff_id': t.id})


@csrf_exempt
@require_http_methods(['GET'])
def api_orders(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    items = []
    for it in (
        OrderItem.objects.filter(manager=user)
        .select_related('order', 'channel', 'tariff', 'tariff__group')
        .order_by('-id')[:40]
    ):
        start = it.effective_start
        items.append({
            'id': it.id,
            'order_id': it.order_id,
            'owner': (
                it.tariff.group.name
                if it.tariff.group_id
                else (it.channel.name if it.channel else '?')
            ),
            'manager_status': it.manager_status,
            'execution_status': it.execution_status,
            'price': it.price,
            'start_jalali': format_jalali(timezone.localtime(start).date()) if start else '',
            'published_link': it.published_link or '',
        })
    return JsonResponse({'ok': True, 'orders': items})


@csrf_exempt
@require_http_methods(['GET'])
def api_free_days(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    tid = request.GET.get('tariff_id')
    t = Tariff.objects.select_related('channel', 'group').filter(id=tid).first()
    if not t:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    owner_ok = (t.channel and t.channel.manager_id == user.id) or (
        t.group and t.group.manager_id == user.id
    )
    if not owner_ok:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    today = timezone.localdate()
    until = today + timedelta(days=13)
    free = [
        {'date': d.isoformat(), 'jalali': format_jalali(d)}
        for d in free_days_for_tariff(t, today, until)
    ]
    return JsonResponse({'ok': True, 'tariff_id': t.id, 'free_days': free})


@csrf_exempt
@require_http_methods(['POST'])
def api_mark_busy(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    day = None
    if body.get('date'):
        try:
            day = datetime.strptime(body['date'][:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    if day is None and body.get('jy'):
        try:
            import jdatetime

            day = jdatetime.date(int(body['jy']), int(body['jm']), int(body['jd'])).togregorian()
        except Exception:
            return JsonResponse({'ok': False, 'error': 'bad_date'}, status=400)
    if day is None:
        return JsonResponse({'ok': False, 'error': 'need_date'}, status=400)

    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    group = ChannelGroup.objects.filter(id=body.get('group_id'), manager=user).first()
    if not ch and not group:
        return JsonResponse({'ok': False, 'error': 'target_required'}, status=400)

    start = timezone.make_aware(datetime.combine(day, dtime(0, 0)))
    end = start + timedelta(days=1)
    slot = mark_external_busy(start, end, channel=ch, group=group, note='miniapp busy')
    return JsonResponse({
        'ok': True,
        'slot_id': slot.id,
        'jalali': format_jalali(day),
    })


@csrf_exempt
@require_http_methods(['GET'])
def api_wallet(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    banks = [
        {
            'id': b.id,
            'iban': b.iban,
            'holder_name': b.holder_name,
            'is_default': b.is_default,
            'iban_tail': b.iban[-6:],
        }
        for b in BankAccount.objects.filter(user=user).order_by('-is_default', '-id')
    ]
    pending = [
        {
            'id': p.id,
            'amount_toman': p.amount_toman,
            'iban_tail': p.iban[-6:],
            'status': p.status,
        }
        for p in PayoutRequest.objects.filter(user=user).order_by('-id')[:10]
    ]
    can, reason = ws.can_request_payout(user)
    return JsonResponse({
        'ok': True,
        'balance': ws.balance_breakdown(user),
        'banks': banks,
        'payouts': pending,
        'can_payout': can,
        'payout_block_reason': reason if not can else '',
        'min_payout': ws.MIN_PAYOUT_TOMAN,
        'fee_percent': ws.PLATFORM_FEE_PERCENT,
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_add_bank(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    try:
        acc = ws.save_bank_account(
            user,
            str(body.get('iban') or ''),
            str(body.get('holder_name') or ''),
            make_default=True,
        )
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    return JsonResponse({'ok': True, 'bank_id': acc.id})


@csrf_exempt
@require_http_methods(['POST'])
def api_request_payout(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    bank = BankAccount.objects.filter(id=body.get('bank_id'), user=user).first()
    if not bank:
        return JsonResponse({'ok': False, 'error': 'bank_not_found'}, status=404)
    r = ws.request_payout(user, bank)
    if not r.get('ok'):
        return JsonResponse(r, status=400)
    pr = r['payout']
    return JsonResponse({'ok': True, 'payout_id': pr.id, 'amount_toman': pr.amount_toman})
