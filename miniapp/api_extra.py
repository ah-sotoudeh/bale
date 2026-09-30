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
    from datetime import timedelta

    from django.utils import timezone

    from orders.models import SlotReservation

    user, err = _auth_user(request)
    if err:
        return err
    qs = list(
        Tariff.objects.filter(is_active=True)
        .select_related('channel', 'group')
        .prefetch_related('group__channels')
        .order_by('-channel__members_count', 'price', 'id')[:400]
    )
    items = []
    channels: dict = {}
    groups: dict = {}
    owned = set()

    def _public_channel(ch):
        return {
            'id': ch.id,
            'name': ch.name,
            'link': ch.link,
            'publish_mode': ch.publish_mode,
            'bot_is_admin': ch.bot_is_admin,
            'linkyar_is_admin': ch.linkyar_is_admin,
            'bot_checked_at': ch.bot_checked_at.isoformat() if ch.bot_checked_at else '',
            'linkyar_checked_at': ch.linkyar_checked_at.isoformat() if ch.linkyar_checked_at else '',
            'manual_remind_hours': ch.manual_remind_hours,
            'members_count': ch.members_count or 0,
            'avg_views': ch.avg_views or 0,
            'daily_reach': ch.daily_reach or 0,
            'err_percent': str(ch.err_percent or ''),
            'language': ch.language or '',
            'about': ch.about or '',
            'stats_updated_at': ch.stats_updated_at.isoformat() if ch.stats_updated_at else '',
            'avatar_url': f'/miniapp/api/channels/{ch.id}/avatar',
        }

    for t in qs:
        if user and (
            (t.channel_id and t.channel.manager_id == user.id)
            or (t.group_id and t.group.manager_id == user.id)
        ):
            owned.add(t.id)
        if t.channel_id and t.channel_id not in channels:
            channels[t.channel_id] = _public_channel(t.channel)
        if t.group_id and t.group_id not in groups:
            group_channels = list(t.group.channels.all())
            groups[t.group_id] = {
                'id': t.group_id,
                'name': t.group.name,
                'channel_ids': [ch.id for ch in group_channels],
            }
            for ch in group_channels:
                channels.setdefault(ch.id, _public_channel(ch))
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
            'members_count': (t.channel.members_count if t.channel_id else 0) or 0,
            'avg_views': (t.channel.avg_views if t.channel_id else 0) or 0,
        })
    today = timezone.localdate()
    until = today + timedelta(days=13)
    other_ids = [t.id for t in qs if t.id not in owned]
    busy = []
    if other_ids:
        for rid, tid, day in SlotReservation.objects.filter(
            tariff_id__in=other_ids,
            slot_date__gte=today,
            slot_date__lte=until,
        ).values_list('id', 'tariff_id', 'slot_date'):
            busy.append({
                'id': rid,
                'tariff_id': tid,
                'date': day.isoformat(),
                'manual': False,
            })
    from integrations.channel_stats import recent_snapshots

    history = recent_snapshots(list(channels.keys()))
    for cid, payload in channels.items():
        payload['history'] = history.get(cid) or []
    return JsonResponse({
        'ok': True,
        'tariffs': items,
        'busy': busy,
        'channels': list(channels.values()),
        'groups': list(groups.values()),
    })


def _set_item_status(request: HttpRequest, action: str) -> JsonResponse:
    """تأیید و رد از همان مسیر سبد بازو می‌گذرد تا فاکتور و وضعیت سفارش یکی بماند."""
    from orders.cart import process_manager_item

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not user.bale_user_id:
        return JsonResponse({'ok': False, 'error': 'no_user'}, status=400)
    body = _json_body(request)
    try:
        item_id = int(body.get('item_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    result = process_manager_item(item_id, str(user.bale_user_id), action)
    if not result.get('ok'):
        from miniapp.api import _with_message

        code = 404 if result.get('error') in ('item_not_found', 'manager_not_found') else 400
        return JsonResponse(_with_message(result), status=code)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(['POST'])
def api_order_approve(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'approve')


@csrf_exempt
@require_http_methods(['POST'])
def api_order_reject(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'reject')


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
    return JsonResponse(
        {
            'ok': False,
            'error': 'use_bot',
            'message': 'تسویه را از بازو بسازید و فقط بعد از واریز بانک تأیید کنید.',
        },
        status=400,
    )
