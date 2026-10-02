"""Extra mini-app endpoints (catalog, order actions, operator payouts)."""
from __future__ import annotations

from datetime import timedelta

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from channels_app.models import Tariff
from miniapp.api import _auth_user, _json_body
from orders.models import OrderItem
from wallet import services as ws
from wallet.models import PayoutRequest


def _ready_publish(ch) -> bool:
    """Bot or linkyar mode, and the admin flag that matches that mode."""
    if ch.publish_mode == 'bot':
        return bool(ch.bot_is_admin)
    if ch.publish_mode == 'linkyar':
        return bool(ch.linkyar_is_admin)
    return False


def _weekly_member_changes(channel_ids):
    """Member change versus a snapshot about seven days earlier.

    None when that history does not exist, so the catalog can hide the line.
    """
    from channels_app.models import ChannelStatSnapshot

    out = {cid: None for cid in channel_ids}
    if not channel_ids:
        return out
    now = timezone.now()
    rows = (
        ChannelStatSnapshot.objects.filter(
            channel_id__in=list(channel_ids),
            taken_at__gte=now - timedelta(days=21),
        )
        .order_by('taken_at')
        .values_list('channel_id', 'taken_at', 'members')
    )
    buckets: dict = {}
    for cid, taken, members in rows:
        buckets.setdefault(cid, []).append((taken, int(members or 0)))
    week = timedelta(days=7)
    min_span = timedelta(days=6)
    max_span = timedelta(days=10)
    for cid, points in buckets.items():
        if len(points) < 2:
            continue
        latest_at, latest_members = points[-1]
        best = None
        best_dist = None
        for taken, members in points[:-1]:
            delta = latest_at - taken
            if delta < min_span or delta > max_span or members <= 0:
                continue
            dist = abs((delta - week).total_seconds())
            if best_dist is None or dist < best_dist:
                best = members
                best_dist = dist
        if best is None:
            continue
        out[cid] = round((latest_members - best) / best * 100, 1)
    return out


@csrf_exempt
@require_http_methods(['GET'])
def api_catalog(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    needle = (request.GET.get('q') or '').strip().casefold()
    ready_only = (request.GET.get('ready') or '').strip() in ('1', 'true', 'yes')

    def _text_match(ch) -> bool:
        if not needle:
            return True
        hay = f'{ch.name or ""}\n{ch.about or ""}\n{ch.description or ""}'.casefold()
        return needle in hay

    def _tariff_ok(t) -> bool:
        if t.channel_id:
            chans = [t.channel]
        elif t.group_id:
            chans = list(t.group.channels.all())
        else:
            chans = []
        if needle and not any(_text_match(ch) for ch in chans):
            return False
        if ready_only and (not chans or any(not _ready_publish(ch) for ch in chans)):
            return False
        return True

    qs = list(
        Tariff.objects.filter(is_active=True)
        .select_related('channel', 'group')
        .prefetch_related('group__channels')
        .order_by('-channel__members_count', 'price', 'id')[:400]
    )
    items = []
    channels: dict = {}
    groups: dict = {}

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
            'description': (ch.description or '')[:500],
            'citation_index': float(ch.citation_index or 0),
            'ready_publish': _ready_publish(ch),
            'stats_updated_at': ch.stats_updated_at.isoformat() if ch.stats_updated_at else '',
            'avatar_url': f'/miniapp/api/channels/{ch.id}/avatar',
        }

    visible = [t for t in qs if _tariff_ok(t)]
    for t in visible:
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
    from orders.availability import day_status_map, has_slot_conflict, slot_bounds, unavailable_why

    own_by_tariff: dict = {}
    for item_id, tariff_id in OrderItem.objects.filter(
        order__customer=user,
        order__status='draft',
        manager_status='cart',
    ).values_list('id', 'tariff_id'):
        own_by_tariff.setdefault(tariff_id, set()).add(item_id)
    busy = []
    seq = 0
    for t in visible:
        for day, status in day_status_map(t, 14):
            if status != 'full':
                continue
            # روز خود سبد «انتخاب» می‌ماند. هم‌پوشانی تعرفهٔ دیگر همان کانال «پر» است.
            same_tariff_cart = own_by_tariff.get(t.id) or set()
            if same_tariff_cart:
                start, end = slot_bounds(t, day)
                if not has_slot_conflict(
                    t, start, end, channel=t.channel, exclude_item_ids=same_tariff_cart
                ):
                    continue
            seq += 1
            busy.append({
                'id': -(t.id * 100 + seq),
                'tariff_id': t.id,
                'date': day.isoformat(),
                'manual': False,
                'status': 'full',
                'why': unavailable_why('full'),
            })
    from integrations.channel_stats import recent_snapshots

    history = recent_snapshots(list(channels.keys()))
    growth = _weekly_member_changes(list(channels.keys()))
    for cid, payload in channels.items():
        payload['history'] = history.get(cid) or []
        payload['week_growth'] = growth.get(cid)
    languages: dict = {}
    for payload in channels.values():
        lang = (payload.get('language') or '').strip()
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
    language_rows = [
        {'language': lang, 'count': count}
        for lang, count in sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return JsonResponse({
        'ok': True,
        'tariffs': items,
        'busy': busy,
        'channels': list(channels.values()),
        'groups': list(groups.values()),
        'languages': language_rows,
    })


def _set_item_status(request: HttpRequest, action: str) -> JsonResponse:
    """تأیید و رد از همان مسیر سبد بازو می‌گذرد تا فاکتور و وضعیت سفارش یکی بماند."""
    from orders.cart import process_manager_item

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not user.bale_user_id:
        from miniapp.api import _fail

        return _fail('no_user')
    body = _json_body(request)
    try:
        item_id = int(body.get('item_id') or 0)
    except (TypeError, ValueError):
        from miniapp.api import _fail

        return _fail('not_found', 404)
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
        from miniapp.api import _fail

        return _fail('forbidden', 403)
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
        from miniapp.api import _fail

        return _fail('forbidden', 403)
    from bot_flow.messages import user_error

    return JsonResponse(
        {'ok': False, 'error': 'use_bot', 'message': user_error('use_bot')},
        status=400,
    )
