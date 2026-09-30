"""API endpoints for manager mini-app."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional

from django.db.models import Q
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


def _channel_payload(ch: Channel, history: Optional[list] = None) -> Dict[str, Any]:
    return {
        'id': ch.id,
        'name': ch.name,
        'link': ch.link,
        'publish_mode': ch.publish_mode,
        'publish_mode_label': ch.publish_mode_label,
        'bot_is_admin': ch.bot_is_admin,
        'linkyar_is_admin': ch.linkyar_is_admin,
        'bot_checked_at': ch.bot_checked_at.isoformat() if ch.bot_checked_at else '',
        'linkyar_checked_at': ch.linkyar_checked_at.isoformat() if ch.linkyar_checked_at else '',
        'manual_remind_hours': ch.manual_remind_hours,
        'tariff_count': ch.tariffs.count(),
        'members_count': getattr(ch, 'members_count', 0) or 0,
        'avg_views': getattr(ch, 'avg_views', 0) or 0,
        'daily_reach': getattr(ch, 'daily_reach', 0) or 0,
        'err_percent': str(getattr(ch, 'err_percent', '') or ''),
        'language': getattr(ch, 'language', '') or '',
        'about': getattr(ch, 'about', '') or '',
        'stats_updated_at': ch.stats_updated_at.isoformat() if getattr(ch, 'stats_updated_at', None) else '',
        'history': history or [],
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
        code = payload.get('error') or 'unauthorized'
        return None, _fail(code, 401)

    uid = str((payload.get('user') or {}).get('id') or '')
    if not uid:
        return None, _fail('no_user', 401)

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
        'can_switch_roles': True,
        'debug': debug_user,
        'channel_count': ch_count,
        'can_be_manager': True,
        'roles': {
            'manager': True,
            'customer': True,
            'operator': is_op,
        },
        'pending_orders': OrderItem.objects.filter(manager=user, manager_status='pending').count(),
        'prefs': _read_prefs(user),
        **_operator_queues(is_op),
    })


def _read_prefs(user: User) -> Dict[str, Any]:
    from users.models import get_bot_session

    empty = {'theme': None, 'onboarded': {}}
    if not user.bale_user_id:
        return empty
    sess = get_bot_session(str(user.bale_user_id))
    raw = (sess.data or {}).get('prefs') or {}
    theme = raw.get('theme')
    if theme not in ('light', 'dark'):
        theme = None
    onboarded = raw.get('onboarded') if isinstance(raw.get('onboarded'), dict) else {}
    clean = {
        role: True
        for role in ('customer', 'manager', 'operator')
        if onboarded.get(role) is True
    }
    return {'theme': theme, 'onboarded': clean}


@csrf_exempt
@require_http_methods(['GET', 'POST', 'PATCH'])
def api_me_prefs(request: HttpRequest) -> JsonResponse:
    """تم و دیده شدن معرفی نقش. ستون تازه نمی‌سازد."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    from users.models import get_bot_session

    if not user.bale_user_id:
        return JsonResponse({'ok': False, 'error': 'no_user'}, status=400)
    sess = get_bot_session(str(user.bale_user_id))
    data = dict(sess.data or {})
    prefs = dict(data.get('prefs') or {})
    if request.method != 'GET':
        body = _json_body(request)
        if 'theme' in body:
            theme = body.get('theme')
            if theme in ('light', 'dark'):
                prefs['theme'] = theme
            elif theme in ('', None, 'bale'):
                prefs.pop('theme', None)
            else:
                return JsonResponse({'ok': False, 'error': 'bad_theme'}, status=400)
        onboarded_in = body.get('onboarded')
        if isinstance(onboarded_in, dict):
            onboarded = dict(prefs.get('onboarded') or {})
            for role in ('customer', 'manager', 'operator'):
                if onboarded_in.get(role) is True:
                    onboarded[role] = True
            prefs['onboarded'] = onboarded
        data['prefs'] = prefs
        sess.data = data
        sess.save(update_fields=['data', 'updated_at'])
    return JsonResponse({'ok': True, 'prefs': _read_prefs(user)})


@csrf_exempt
@require_http_methods(['GET'])
def api_channels(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    rows = list(Channel.objects.filter(manager=user).order_by('id'))
    from integrations.channel_stats import recent_snapshots

    history = recent_snapshots([ch.id for ch in rows])
    channels = [_channel_payload(ch, history.get(ch.id) or []) for ch in rows]
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
def api_refresh_channel_stats(request: HttpRequest) -> JsonResponse:
    """کانال‌هایی که تعرفهٔ فعال دارند را با لینک‌یار می‌خواند.

    باز شدن مینی‌اپ فقط کانال‌های کهنه یا بدون بازدید را می‌خواند.
    دکمهٔ «خواندن دوباره» با force همان کانال‌های تعرفه‌دار را از نو می‌خواند.
    """
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    from django.db.models import F

    from integrations.channel_stats import public_stats_error, recent_snapshots, refresh_channel

    qs = Channel.objects.exclude(link='')
    if not ws.is_operator(user.bale_user_id or ''):
        qs = qs.filter(manager=user)
    body = _json_body(request)
    explicit = body.get('channel_id')
    if explicit:
        qs = qs.filter(id=explicit)
    else:
        qs = qs.filter(Q(tariffs__is_active=True) | Q(groups__tariffs__is_active=True)).distinct()
        if not body.get('force'):
            cutoff = timezone.now() - timedelta(minutes=30)
            recent_zero = timezone.now() - timedelta(minutes=2)
            qs = qs.filter(
                Q(stats_updated_at__isnull=True)
                | Q(stats_updated_at__lt=cutoff)
                | Q(avg_views=0, stats_updated_at__lt=recent_zero)
            )
    picked = list(qs.order_by(F('stats_updated_at').asc(nulls_first=True), 'id')[:1 if explicit else 4])
    done = 0
    failed = 0
    message = ''
    for ch in picked:
        try:
            result = refresh_channel(ch)
        except Exception:
            logger.exception('miniapp stats refresh')
            failed += 1
            message = 'خواندن آمار این کانال ممکن نشد.'
            continue
        ch.refresh_from_db()
        if result.get('ok'):
            done += 1
        else:
            failed += 1
            message = public_stats_error(str(result.get('error') or ''))
    history = recent_snapshots([ch.id for ch in picked])
    return JsonResponse({
        'ok': True,
        'done': done,
        'failed': failed,
        'message': '' if done else message,
        'channels': [_channel_payload(ch, history.get(ch.id) or []) for ch in picked],
    })


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
    from bot_flow.handlers import bio_matches_owner, ownership_prompt

    proved = bio_matches_owner(bio, user)
    looked_up = not info.get('error')
    if not looked_up:
        missing = 'کانال را از بله نخواندیم. پیوند را یک بار دیگر بررسی کنید.'
        return JsonResponse(
            {'ok': False, 'error': missing, 'message': missing, 'code': 'lookup_failed'},
            status=400,
        )
    if not proved:
        prompt = ownership_prompt(user)
        return JsonResponse(
            {'ok': False, 'error': prompt, 'message': prompt, 'code': 'owner_username'},
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
        return _fail('not_found', 404)
    mode = body.get('publish_mode')
    if mode not in (Channel.PUBLISH_BOT, Channel.PUBLISH_LINKYAR, Channel.PUBLISH_MANUAL):
        return _fail('bad_mode')
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
        return _fail('channel_not_found', 404)
    try:
        name = str(body.get('name') or '').strip()[:100]
        duration = int(body.get('duration_hours'))
        price = int(body.get('price'))
        start_hour = body.get('start_hour')
        start_hour = int(start_hour) if start_hour is not None and str(start_hour) != '' else None
    except (TypeError, ValueError):
        return _fail('bad_fields')
    if not name or duration <= 0 or price < 0:
        return _fail('bad_fields')
    t = Tariff.objects.create(
        channel=ch,
        name=name,
        duration_hours=duration,
        price=price,
        start_hour=start_hour,
        is_active=True,
    )
    return JsonResponse({'ok': True, 'tariff_id': t.id})


def _operator_queues(is_op: bool) -> Dict[str, Any]:
    """صف بنر، تسویه و بررسی انتشار. فقط برای پشتیبانی پر می‌شود."""
    empty = {'operator_banners': [], 'operator_payouts': [], 'operator_reviews': []}
    if not is_op:
        return empty
    from orders.models import BannerPublishRequest

    banners = []
    for req in BannerPublishRequest.objects.filter(status='pending').select_related('customer').order_by('id')[:40]:
        caption = (req.caption or '').strip()
        banners.append({
            'id': req.id,
            'customer': req.customer.bale_user_id or '',
            'fee_toman': req.fee_toman,
            'caption': caption[:800],
            'title': (caption[:40] or f'بنر {req.id}'),
            'media_kind': req.media_kind or 'photo',
        })
    payouts = []
    for payout in PayoutRequest.objects.filter(status='pending').order_by('id')[:80]:
        payouts.append({
            'id': payout.id,
            'amount_toman': payout.amount_toman,
            'iban': payout.iban,
            'holder_name': payout.holder_name,
            'status': payout.status,
        })
    reviews = []
    for item in (
        OrderItem.objects.filter(execution_status='awaiting_operator')
        .select_related('channel', 'tariff', 'tariff__group')
        .order_by('id')[:40]
    ):
        owner = ''
        if item.tariff_id and item.tariff.group_id:
            owner = item.tariff.group.name
        elif item.channel_id:
            owner = item.channel.name
        note = owner or f'نوبت {item.id}'
        if item.published_link:
            note = f'{note} · {item.published_link}'
        reviews.append({'item_id': item.id, 'note': note[:240]})
    return {
        'operator_banners': banners,
        'operator_payouts': payouts,
        'operator_reviews': reviews,
    }


def _fail(error: str, status: int = 400) -> JsonResponse:
    from bot_flow.messages import user_error

    return JsonResponse(
        {'ok': False, 'error': error, 'message': user_error(error)},
        status=status,
    )


def _with_message(result: Dict[str, Any]) -> Dict[str, Any]:
    from bot_flow.messages import user_error

    if result.get('ok') or result.get('message'):
        return result
    return {**result, 'message': user_error(str(result.get('error') or ''))}


def _item_in_manager_inbox(it: OrderItem, user: User) -> bool:
    """درخواست‌هایی که این کاربر باید به عنوان مدیر کانال جواب بدهد."""
    if it.manager_id == user.id:
        return True
    if it.manager_id:
        return False
    if it.channel_id and it.channel and it.channel.manager_id == user.id:
        return True
    group = it.tariff.group if it.tariff_id and it.tariff.group_id else None
    return bool(group and group.manager_id == user.id)


@csrf_exempt
@require_http_methods(['GET'])
def api_orders(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    items = []
    # مدیر فقط درخواست کانال خودش را می‌بیند. مشتری خط سفارش خودش را هم می‌گیرد
    # تا زمان پیشنهادی و لینک انتشار در مینی‌اپ گم نشود.
    for it in (
        OrderItem.objects.filter(Q(manager=user) | Q(order__customer=user))
        .select_related('order', 'channel', 'tariff', 'tariff__group', 'tariff__channel')
        .order_by('-id')[:80]
    ):
        start = it.effective_start
        items.append({
            'id': it.id,
            'order_id': it.order_id,
            'inbox': _item_in_manager_inbox(it, user) and it.order.status != 'waiting_banner',
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
            'group_id': it.tariff.group_id if it.tariff_id else None,
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
        return _fail('not_found', 404)
    owner_ok = (t.channel and t.channel.manager_id == user.id) or (
        t.group and t.group.manager_id == user.id
    )
    if not owner_ok:
        return _fail('forbidden', 403)
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
            return _fail('bad_date')
    if day is None:
        return _fail('need_date')

    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    group = ChannelGroup.objects.filter(id=body.get('group_id'), manager=user).first()
    if not ch and not group:
        return _fail('target_required')

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
                'iban': p.iban,
                'iban_tail': (p.iban or '')[-6:],
                'holder_name': p.holder_name,
                'status': p.status,
                'created_at': p.created_at.isoformat() if p.created_at else '',
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
        return _fail(str(e))
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
        return _fail('not_found', 404)
    result = invoice_for_order(order)
    status = 200 if result.get('ok') else 400
    return JsonResponse(_with_message(result), status=status)


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
        return _fail('bank_not_found', 404)
    r = ws.request_payout(user, bank)
    if not r.get('ok'):
        return JsonResponse(_with_message(r), status=400)
    pr = r['payout']
    return JsonResponse({'ok': True, 'payout_id': pr.id, 'amount_toman': pr.amount_toman})
