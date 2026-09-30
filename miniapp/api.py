"""API endpoints for manager mini-app."""
from __future__ import annotations

import json
import logging
import os
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


def _can_switch_roles(bale_user_id: str) -> bool:
    """سوییچ مدیر/مشتری/پشتیبانی فقط برای حساب مالک."""
    uid = str(bale_user_id or '').strip()
    if not uid:
        return False
    from bot_flow.access import is_debug_user

    if is_debug_user(uid) or ws.is_operator(uid):
        return True
    extra = os.environ.get('MINIAPP_ROLE_SWITCH_IDS', '')
    allowed = {part.strip() for part in extra.split(',') if part.strip()}
    return uid in allowed


def _channel_payload(ch: Channel) -> Dict[str, Any]:
    return {
        'id': ch.id,
        'name': ch.name,
        'link': ch.link,
        'publish_mode': ch.publish_mode,
        'publish_mode_label': ch.publish_mode_label,
        'bot_is_admin': ch.bot_is_admin,
        'linkyar_is_admin': ch.linkyar_is_admin,
        'manual_remind_hours': ch.manual_remind_hours,
        'tariff_count': ch.tariffs.count(),
        'members_count': getattr(ch, 'members_count', 0) or 0,
        'avg_views': getattr(ch, 'avg_views', 0) or 0,
        'err_percent': str(getattr(ch, 'err_percent', '') or ''),
        'language': getattr(ch, 'language', '') or '',
        'about': getattr(ch, 'about', '') or '',
        'stats_updated_at': ch.stats_updated_at.isoformat() if getattr(ch, 'stats_updated_at', None) else '',
    }


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
    from bot_flow.access import is_debug_user

    br = ws.balance_breakdown(user)
    ch_count = Channel.objects.filter(manager=user).count()
    is_op = ws.is_operator(user.bale_user_id or '')
    debug_user = is_debug_user(user.bale_user_id or '')
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
        'can_switch_roles': _can_switch_roles(user.bale_user_id or ''),
        'debug': debug_user,
        'channel_count': ch_count,
        'can_be_manager': True,
        'roles': {
            'manager': True,
            'customer': True,
            'operator': is_op,
        },
        'pending_orders': OrderItem.objects.filter(manager=user, manager_status='pending').count(),
    })


@csrf_exempt
@require_http_methods(['GET'])
def api_channels(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    channels = [_channel_payload(ch) for ch in Channel.objects.filter(manager=user).order_by('id')]
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
def api_add_channel(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    from bot_flow.links import normalize_channel_ref

    link = normalize_channel_ref(str(body.get('link') or ''))
    name = str(body.get('name') or '').strip()[:200]
    if not link or link == '@':
        return JsonResponse({'ok': False, 'error': 'پیوند کانال را بنویسید.'}, status=400)

    info: Dict[str, Any] = {}
    try:
        from integrations.bale_client import get_channel_info

        info = get_channel_info(link)
    except Exception:
        logger.exception('channel lookup failed')
        info = {'error': 'lookup_failed'}

    title = str(info.get('title') or '').strip()
    if title and title != '(no title)':
        name = name or title
    if not name:
        name = link.lstrip('@') or link

    bio = str(info.get('bio') or info.get('description') or '')
    owner = _can_switch_roles(user.bale_user_id or '')
    from bot_flow.access import id_in_text

    proved = bool(user.bale_user_id) and id_in_text(str(user.bale_user_id), bio)
    if info.get('error') and not owner:
        return JsonResponse({'ok': False, 'error': 'کانال از بله خوانده نشد. پیوند را بررسی کنید.'}, status=400)
    if not proved and not owner:
        return JsonResponse(
            {'ok': False, 'error': 'شناسهٔ عددی حساب بلهٔ شما باید در توضیحات کانال باشد.'},
            status=400,
        )

    existing = Channel.objects.filter(link__iexact=link).first()
    if existing and existing.manager_id and existing.manager_id != user.id and not owner:
        return JsonResponse({'ok': False, 'error': 'این کانال برای مدیر دیگری ثبت شده.'}, status=403)
    if existing:
        existing.manager = user
        existing.name = name
        if info.get('id'):
            try:
                existing.bale_peer_id = int(info['id'])
            except (TypeError, ValueError):
                pass
        existing.save()
        ch = existing
    else:
        peer = None
        if info.get('id'):
            try:
                peer = int(info['id'])
            except (TypeError, ValueError):
                peer = None
        ch = Channel.objects.create(
            name=name,
            link=link,
            manager=user,
            publish_mode=Channel.PUBLISH_MANUAL,
            bale_peer_id=peer,
            about=bio[:4000],
        )
    try:
        from integrations.channel_stats import refresh_channel

        refresh_channel(ch)
        ch.refresh_from_db()
    except Exception:
        logger.exception('stats after miniapp register')
    return JsonResponse({'ok': True, 'channel': _channel_payload(ch)})


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
    from orders.availability import list_manual_busy_slots

    busy = []
    for t in qs:
        for slot in list_manual_busy_slots(t):
            start = slot.start
            day = timezone.localtime(start).date() if timezone.is_aware(start) else start.date()
            busy.append({
                'id': slot.id,
                'tariff_id': t.id,
                'date': day.isoformat(),
                'manual': True,
            })
    return JsonResponse({'ok': True, 'tariffs': items, 'busy': busy})


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
            'tariff_id': it.tariff_id,
            'tariff_name': it.tariff.name if it.tariff_id else '',
            'channel_id': it.channel_id,
            'date': timezone.localtime(start).date().isoformat() if start else '',
            'proposed_date': (
                timezone.localtime(it.manager_edited_start).date().isoformat()
                if it.manager_status == 'edited' and it.manager_edited_start
                else ''
            ),
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
            from bot_flow.jalali import parse_jalali_date

            day = parse_jalali_date(int(body['jy']), int(body['jm']), int(body['jd']))
        except (TypeError, ValueError):
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
    try:
        banks = [
            {
                'id': b.id,
                'iban': b.iban,
                'holder_name': b.holder_name,
                'is_default': b.is_default,
                'iban_tail': (b.iban or '')[-6:],
            }
            for b in BankAccount.objects.filter(user=user).order_by('-is_default', '-id')
        ]
        pending = [
            {
                'id': p.id,
                'amount_toman': p.amount_toman,
                'iban_tail': (p.iban or '')[-6:],
                'status': p.status,
            }
            for p in PayoutRequest.objects.filter(user=user).order_by('-id')[:10]
        ]
        can, reason = ws.can_request_payout(user)
        balance = ws.balance_breakdown(user)
        ledger = ws.recent_ledger(user)
    except Exception:
        logger.exception('wallet api failed')
        return JsonResponse(
            {
                'ok': True,
                'balance': {'available': 0, 'locked_pending': 0, 'paid_out': 0, 'ledger_sum': 0},
                'banks': [],
                'payouts': [],
                'ledger': [],
                'can_payout': False,
                'payout_block_reason': 'wallet_unavailable',
                'min_payout': ws.MIN_PAYOUT_TOMAN,
                'fee_percent': ws.PLATFORM_FEE_PERCENT,
                'degraded': True,
            }
        )
    return JsonResponse({
        'ok': True,
        'balance': balance,
        'banks': banks,
        'payouts': pending,
        'ledger': ledger,
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
def api_invoice(request: HttpRequest) -> JsonResponse:
    """شناسه createInvoiceLink برای openInvoice داخل مینی‌اپ."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    from orders.bale_pay import invoice_for_order
    from orders.models import Order

    order = Order.objects.filter(id=body.get('order_id'), customer=user).first()
    if not order:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    result = invoice_for_order(order)
    status = 200 if result.get('ok') else 400
    return JsonResponse(result, status=status)


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
