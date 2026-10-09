"""API endpoints for manager mini-app."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional

from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot_flow.jalali import format_jalali, format_slot
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



def _norm_username(raw: str) -> str:
    return str(raw or '').strip().lstrip('@').lower()


def _channel_ref_key(ref: str) -> str:
    """Normalize @name or ble.ir/name to bare username key."""
    s = str(ref or '').strip()
    if not s:
        return ''
    s = s.replace('https://', '').replace('http://', '')
    for prefix in ('ble.ir/', 'bale.ai/', 'ble.ir', 'bale.ai'):
        if s.lower().startswith(prefix):
            s = s[len(prefix):].lstrip('/')
            break
    return _norm_username(s)


def claim_pending_channels(user: User) -> int:
    """Connect operator-assigned channels when manager first appears."""
    handle = _norm_username(getattr(user, 'bale_username', None) or '')
    if not handle:
        return 0
    from django.db.models import Q
    # تطبیق انعطاف‌پذیر: link_yar / linkyar / با و بدون زیرخط
    variants = {handle, handle.replace('_', ''), handle.replace('-', '')}
    q = Q()
    for v in variants:
        if not v:
            continue
        q |= Q(pending_manager_username__iexact=v)
        q |= Q(pending_manager_username__iexact='@' + v)
    qs = Channel.objects.filter(q).filter(Q(manager__isnull=True) | Q(manager=user))
    n = 0
    for ch in qs:
        ch.manager = user
        ch.ownership_verified = True
        ch.pending_manager_username = ''
        ch.save(update_fields=['manager', 'ownership_verified', 'pending_manager_username'])
        n += 1
    return n

def _can_switch_roles(bale_user_id: str) -> bool:
    """سوییچ مشتری/مدیر برای همه؛ پشتیبانی فقط برای اپراتور/دیباگ/لیست."""
    uid = str(bale_user_id or '').strip()
    if not uid:
        return False
    # مشتری ↔ کانال‌دار در مینی‌اپ برای همهٔ کاربران واردشده
    return True


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
        'is_listed': bool(getattr(ch, 'is_listed', True)),
        'ownership_verified': bool(getattr(ch, 'ownership_verified', False)),
        'pending_manager_username': (getattr(ch, 'pending_manager_username', None) or ''),
        'members_count': getattr(ch, 'members_count', 0) or 0,
        'avg_views': getattr(ch, 'avg_views', 0) or 0,
        'daily_reach': getattr(ch, 'daily_reach', 0) or 0,
        'err_percent': str(getattr(ch, 'err_percent', '') or ''),
        'language': getattr(ch, 'language', '') or '',
        'about': getattr(ch, 'about', '') or '',
        'description': (getattr(ch, 'description', '') or '')[:500],
        'stats_updated_at': ch.stats_updated_at.isoformat() if getattr(ch, 'stats_updated_at', None) else '',
        'avatar_url': f'/miniapp/api/channels/{ch.id}/avatar',
        'created_at': ch.created_at.isoformat() if getattr(ch, 'created_at', None) else '',
        'is_new': bool(
            getattr(ch, 'created_at', None)
            and (timezone.now() - ch.created_at).total_seconds() < 86400
        ),
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
    claim_pending_channels(user)
    from bot_flow.access import is_debug_user

    br = ws.balance_breakdown(user)
    ch_count = Channel.objects.filter(manager=user).count()
    is_op = ws.is_operator(user.bale_user_id or '')
    debug_user = is_debug_user(user.bale_user_id or '')
    can_switch = _can_switch_roles(user.bale_user_id or '')
    # هر کاربر می‌تواند پنل مدیر را باز کند (برای ثبت کانال). سوییچ نقش فقط مالک/پشتیبانی.
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
        'can_switch_roles': can_switch,
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
        return _fail('no_user')
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
                return _fail('bad_theme')
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
    claim_pending_channels(user)
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
        missing_link = 'پیوند کانال را بنویسید.'
        return JsonResponse({'ok': False, 'error': missing_link, 'message': missing_link}, status=400)

    info: Dict[str, Any] = {}
    try:
        from integrations.bale_client import get_channel_info

        info = get_channel_info(link)
    except Exception:
        logger.exception('channel lookup failed')
        info = {'error': 'lookup_failed'}

    title = str(info.get('title') or '').strip()
    if title and title != '(no title)':
        name = title  # همیشه نام واقعی کانال از بله/دستیار
    elif not name:
        name = link.lstrip('@') or link

    bio = str(info.get('bio') or info.get('description') or '')
    owner = _can_switch_roles(user.bale_user_id or '')
    from bot_flow.handlers import bio_matches_owner, ownership_prompt

    existing = Channel.objects.filter(link__iexact=link).first()
    # مالکیت از قبل توسط پشتیبان یا خود کاربر
    pre_verified = bool(
        existing
        and (
            getattr(existing, 'ownership_verified', False)
            or (existing.manager_id == user.id)
            or (
                _norm_username(getattr(existing, 'pending_manager_username', '') or '')
                == _norm_username(getattr(user, 'bale_username', None) or '')
            )
        )
    )
    proved = bio_matches_owner(bio, user) or pre_verified or owner
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

    if existing and existing.manager_id and existing.manager_id != user.id and not owner:
        taken = 'این کانال برای کانال‌دار دیگری ثبت شده. اگر مال شماست، به پشتیبانی بگویید.'
        return JsonResponse({'ok': False, 'error': taken, 'message': taken}, status=403)
    if existing:
        existing.manager = user
        existing.name = name
        existing.pending_manager_username = ''
        if pre_verified:
            existing.ownership_verified = True
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
def api_channel_update(request: HttpRequest) -> JsonResponse:
    """ویرایش نام کانال توسط مالک."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کانال پیدا نشد.'}, status=404)
    name = str(body.get('name') or '').strip()
    if not name:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'نام کانال را بنویسید.'}, status=400)
    ch.name = name[:200]
    ch.save(update_fields=['name'])
    return JsonResponse({'ok': True, 'channel': _channel_payload(ch)})


@csrf_exempt
@require_http_methods(['POST'])
def api_channel_delete(request: HttpRequest) -> JsonResponse:
    """حذف کانال اگر سفارش باز نداشته باشد (سفارش‌های بسته‌شده مانع نیستند)."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کانال پیدا نشد.'}, status=404)
    from django.db.models import Q
    from orders.models import OrderItem

    related = OrderItem.objects.filter(Q(channel=ch) | Q(tariff__channel=ch))
    open_q = Q(manager_status__in=('pending', 'approved', 'edited')) | Q(
        execution_status__in=(
            'paid',
            'remind_sent',
            'awaiting_manager_publish',
            'awaiting_customer_confirm',
            'awaiting_operator',
        )
    )
    if related.filter(open_q).exists():
        return JsonResponse({
            'ok': False,
            'error': 'has_orders',
            'message': 'این کانال سفارش باز دارد؛ بعد از اتمام یا لغو سفارش می‌توانید حذف کنید.',
        }, status=400)
    cid = ch.id
    from channels_app.models import Tariff
    # قلم‌های بسته‌شده را از کانال جدا کن تا CASCADE مانع نشود
    related.update(channel=None)
    Tariff.objects.filter(channel=ch).delete()
    ch.delete()
    return JsonResponse({'ok': True, 'channel_id': cid, 'deleted': True})


@csrf_exempt
@require_http_methods(['POST'])
def api_channel_archive(request: HttpRequest) -> JsonResponse:
    """آرشیو: از کاتالوگ مخفی می‌شود؛ سفارش‌ها و کانال می‌مانند."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کانال پیدا نشد.'}, status=404)
    listed = body.get('is_listed')
    if listed is None:
        # toggle: archive if currently listed
        ch.is_listed = not bool(ch.is_listed)
    else:
        ch.is_listed = bool(listed)
    ch.save(update_fields=['is_listed'])
    # غیرفعال کردن تعرفه‌ها هنگام آرشیو تا در کاتالوگ نیایند
    if not ch.is_listed:
        Tariff.objects.filter(channel=ch, is_active=True).update(is_active=False)
    return JsonResponse({
        'ok': True,
        'channel_id': ch.id,
        'is_listed': ch.is_listed,
        'archived': not ch.is_listed,
    })


def _group_payload(g: ChannelGroup) -> dict:
    return {
        'id': g.id,
        'name': g.name,
        'channel_ids': list(g.channels.values_list('id', flat=True)),
    }


@csrf_exempt
@require_http_methods(['POST'])
def api_group_add(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    name = str(body.get('name') or '').strip()[:200]
    if not name:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'نام مجموعه را بنویسید.'}, status=400)
    raw_ids = body.get('channel_ids') or body.get('channels') or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'حداقل یک کانال انتخاب کنید.'}, status=400)
    chans = list(Channel.objects.filter(id__in=raw_ids, manager=user))
    if len(chans) != len(set(int(x) for x in raw_ids)):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'همه کانال‌ها باید مال شما باشند.'}, status=403)
    g = ChannelGroup.objects.create(name=name, manager=user)
    g.channels.set(chans)
    return JsonResponse({'ok': True, 'group': _group_payload(g)})


@csrf_exempt
@require_http_methods(['POST'])
def api_group_update(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    g = ChannelGroup.objects.filter(id=body.get('group_id'), manager=user).first()
    if not g:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'مجموعه پیدا نشد.'}, status=404)
    if 'name' in body and str(body.get('name') or '').strip():
        g.name = str(body.get('name')).strip()[:200]
        g.save(update_fields=['name'])
    if 'channel_ids' in body or 'channels' in body:
        raw_ids = body.get('channel_ids') or body.get('channels') or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'حداقل یک کانال لازم است.'}, status=400)
        chans = list(Channel.objects.filter(id__in=raw_ids, manager=user))
        if len(chans) != len(set(int(x) for x in raw_ids)):
            return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'همه کانال‌ها باید مال شما باشند.'}, status=403)
        g.channels.set(chans)
    return JsonResponse({'ok': True, 'group': _group_payload(g)})


@csrf_exempt
@require_http_methods(['POST'])
def api_group_delete(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    g = ChannelGroup.objects.filter(id=body.get('group_id'), manager=user).first()
    if not g:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'مجموعه پیدا نشد.'}, status=404)
    from orders.models import OrderItem
    if OrderItem.objects.filter(tariff__group=g).exists():
        return JsonResponse({
            'ok': False,
            'error': 'has_orders',
            'message': 'این مجموعه سفارش دارد؛ حذف ممکن نیست.',
        }, status=400)
    gid = g.id
    Tariff.objects.filter(group=g).delete()
    g.delete()
    return JsonResponse({'ok': True, 'group_id': gid, 'deleted': True})


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
            'is_package': bool(t.group_id),
            'channel_count': t.group.channels.count() if t.group_id else (1 if t.channel_id else 0),
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
    ch = Channel.objects.filter(id=body.get('channel_id'), manager=user).first() if body.get('channel_id') not in (None, '', 0, '0') else None
    group = ChannelGroup.objects.filter(id=body.get('group_id'), manager=user).first() if body.get('group_id') not in (None, '', 0, '0') else None
    if bool(ch) == bool(group):
        return JsonResponse({
            'ok': False,
            'error': 'bad_fields',
            'message': 'دقیقاً یک کانال یا یک مجموعه را انتخاب کنید.',
        }, status=400)
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
        group=group,
        name=name,
        duration_hours=duration,
        price=price,
        start_hour=start_hour,
        is_active=True,
    )
    return JsonResponse({
        'ok': True,
        'tariff_id': t.id,
        'channel_id': t.channel_id,
        'group_id': t.group_id,
    })


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
        .select_related('channel', 'tariff', 'tariff__group', 'order__customer', 'manager')
        .order_by('id')[:40]
    ):
        owner = ''
        if item.tariff_id and item.tariff.group_id:
            owner = item.tariff.group.name
        elif item.channel_id:
            owner = item.channel.name
        start = item.effective_start
        note = owner or f'نوبت {item.id}'
        if item.published_link:
            note = f'{note} · {item.published_link}'
        reviews.append({
            'item_id': item.id,
            'note': note[:240],
            'owner': owner,
            'order_id': item.order_id,
            'price': int(item.price or 0),
            'when': format_slot(timezone.localtime(start)) if start else '',
            'customer': item.order.customer.bale_user_id or '',
            'manager': (item.manager.bale_user_id or '') if item.manager_id else '',
            'link': item.published_link or '',
        })
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

def _item_publish_due(it: OrderItem) -> bool:
    """نوبت انتشار دستی نزدیک یا رسیده است."""
    if not it.channel_id:
        return False
    mode = getattr(it.channel, 'publish_mode', '') or ''
    if mode != 'manual':
        return False
    if it.execution_status not in (
        'paid',
        'remind_sent',
        'awaiting_manager_publish',
    ):
        return False
    start = it.effective_start
    if not start:
        return False
    from datetime import timedelta
    hours = int(getattr(it.channel, 'manual_remind_hours', None) or 2)
    now = timezone.now()
    return start - timedelta(hours=hours) <= now <= start + timedelta(hours=6)


def api_orders(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    items = []
    # مدیر فقط درخواست کانال خودش را می‌بیند. مشتری خط سفارش خودش را هم می‌گیرد
    # تا زمان پیشنهادی و لینک انتشار در مینی‌اپ گم نشود.
    # اگر manager روی آیتم خالی باشد ولی کانال مال این کاربر است، باز هم ببیند
    for it in (
        OrderItem.objects.filter(
            Q(manager=user)
            | Q(channel__manager=user)
            | Q(tariff__group__manager=user)
            | Q(order__customer=user)
        )
        .select_related('order', 'channel', 'tariff', 'tariff__group', 'tariff__channel')
        .order_by('-id')[:80]
    ):
        start = it.effective_start
        items.append({
            'id': it.id,
            'order_id': it.order_id,
            'inbox': (
                _item_in_manager_inbox(it, user)
                or (it.channel_id and it.channel and it.channel.manager_id == user.id)
                or (it.tariff_id and it.tariff and it.tariff.group_id and it.tariff.group and it.tariff.group.manager_id == user.id)
            ) and it.order.status not in ('waiting_banner', 'draft', 'cancelled'),
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
            'publish_due': _item_publish_due(it),
            'publish_mode': (
                it.channel.publish_mode if it.channel_id else ''
            ),
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
        from django.db.models import Sum
        from django.utils import timezone as dj_tz
        from wallet.models import WalletLedger

        now = dj_tz.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_earn = int(
            WalletLedger.objects.filter(
                user=user, entry_type='earn', created_at__gte=month_start
            ).aggregate(s=Sum('amount'))['s']
            or 0
        )
        report = {
            'month_earn': month_earn,
            'available': int(balance.get('available') or 0),
            'escrow': int(balance.get('manager_escrow') or balance.get('escrow') or 0),
            'locked_pending': int(balance.get('locked_pending') or 0),
            'paid_out': int(balance.get('paid_out') or 0),
            'can_payout': can,
        }
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
                'report': {
                    'month_earn': 0,
                    'available': 0,
                    'escrow': 0,
                    'locked_pending': 0,
                    'paid_out': 0,
                    'can_payout': False,
                },
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
        'report': report,
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
    """فاکتور را در گفتگوی بازو می‌فرستد تا کاربر در بله پرداخت کند و به مینی‌اپ برگردد.

    درگاه داخل مینی‌اپ در دسترس نیست؛ مسیر اصلی sendInvoice در چت بازو است.
    """
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    from orders.bale_pay import (
        announce_invoices,
        invoice_for_order,
        order_is_fully_paid,
        send_order_invoices,
    )
    from orders.models import Order
    from orders.services import process_payment_paid

    order = Order.objects.filter(id=body.get('order_id'), customer=user).first()
    if not order:
        return _fail('not_found', 404)
    if order.status == 'paid' or order_is_fully_paid(order):
        if order.status == 'waiting_payment' and order_is_fully_paid(order):
            process_payment_paid(order.id)
        return JsonResponse({
            'ok': False,
            'error': 'already_paid',
            'message': 'این سفارش قبلاً پرداخت شده.',
        }, status=400)
    if order.status != 'waiting_payment':
        return JsonResponse({
            'ok': False,
            'error': 'not_waiting_payment',
            'message': 'این سفارش الان قابل پرداخت نیست.',
        }, status=400)

    via = str(body.get('via') or 'auto').strip().lower()
    total = int(order.total_amount or 0)

    # پرداخت از اعتبار مشتری (بدون درگاه داخل مینی‌اپ)
    if via in ('wallet', 'credit', 'auto'):
        from wallet.services import balance_breakdown, spend_customer_credit
        from orders.services import process_payment_paid

        credit = int(balance_breakdown(user).get('credit') or 0)
        if via in ('wallet', 'credit') or (via == 'auto' and credit >= total > 0):
            if credit < total:
                if via in ('wallet', 'credit'):
                    return JsonResponse({
                        'ok': False,
                        'error': 'low_balance',
                        'message': 'اعتبار کافی نیست. از پرداخت در بازو استفاده کنید.',
                        'credit': credit,
                        'total': total,
                    }, status=400)
            else:
                spent = spend_customer_credit(
                    user,
                    total,
                    ref=f'order:{order.id}',
                    note=f'پرداخت سفارش {order.id} از اعتبار',
                    idempotency_key=f'spend:order:{order.id}',
                )
                if not spent.get('ok'):
                    return JsonResponse({
                        'ok': False,
                        'error': spent.get('error') or 'low_balance',
                        'message': 'کسر از اعتبار انجام نشد.',
                    }, status=400)
                result = process_payment_paid(order.id)
                if not result.get('ok'):
                    return JsonResponse({
                        'ok': False,
                        'error': result.get('error') or 'pay_failed',
                        'message': 'پرداخت از اعتبار ثبت نشد. پشتیبانی را خبر کنید.',
                    }, status=400)
                return JsonResponse({
                    'ok': True,
                    'via': 'wallet',
                    'order_id': order.id,
                    'order_status': 'paid',
                    'message': 'از اعتبار شما پرداخت شد. سفارش ثبت است.',
                })

    chat_id = str(user.bale_user_id or '').strip()
    if not chat_id:
        return JsonResponse({
            'ok': False,
            'error': 'no_chat',
            'message': 'شناسه بله شما پیدا نشد. یک‌بار از بازو وارد مینی‌اپ شوید.',
        }, status=400)

    # مسیر اصلی بدون اعتبار کافی: فاکتور در چت بازو
    if via in ('bot', 'chat', 'reopen', 'auto', ''):
        payment = send_order_invoices(order, chat_id)
        announce_invoices(chat_id, payment)
        sent = int(payment.get('sent') or 0)
        failed = int(payment.get('failed') or 0)
        skipped = int(payment.get('skipped') or 0)
        if sent == 0 and failed > 0:
            return JsonResponse({
                'ok': False,
                'error': payment.get('error') or 'invoice_failed',
                'message': 'فاکتور در گفتگوی بازو فرستاده نشد. یک‌بار دیگر تلاش کنید.',
            }, status=400)
        if sent == 0 and skipped == 0:
            return JsonResponse({
                'ok': False,
                'error': 'invoice_failed',
                'message': 'فاکتور ساخته نشد. مبلغ یا وضعیت سفارش را بررسی کنید.',
            }, status=400)
        if sent:
            bc_msg = (
                'فاکتور در گفتگوی بازو (لینک‌بان) فرستاده شد. '
                'به چت بازو بروید، با کیف پول بله پرداخت کنید و بعد به مینی‌اپ برگردید.'
            )
        else:
            bc_msg = (
                'فاکتور همین الان در گفتگوی بازو هست. '
                'همان‌جا پرداخت کنید و بعد به مینی‌اپ برگردید تا وضعیت به‌روز شود.'
            )
        import os
        bot_user = (
            os.environ.get('BALE_BOT_USERNAME')
            or os.environ.get('BOT_USERNAME')
            or os.environ.get('LINKBANK_BOT_USERNAME')
            or ''
        ).strip().lstrip('@')
        bot_url = f'https://ble.ir/{bot_user}' if bot_user else ''
        return JsonResponse({
            'ok': True,
            'via': 'bot',
            'order_id': order.id,
            'sent': sent,
            'skipped': skipped,
            'parts': payment.get('parts') or 0,
            'failed': failed,
            'message': bc_msg,
            'open_bot': True,
            'bot_url': bot_url,
        })

    # مسیر اختیاری: لینک فاکتور (اگر کلاینت openInvoice داشته باشد)
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


def _avatar_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'RIFF') and b'WEBP' in data[:16]:
        return 'image/webp'
    if data.startswith(b'GIF8'):
        return 'image/gif'
    return 'image/jpeg'


@csrf_exempt
@require_http_methods(['GET'])
def api_channel_avatar(request: HttpRequest, channel_id: int) -> HttpResponse:
    """عکس پروفایل کانال برای کارت فهرست. برچسب img هدر احراز هویت نمی‌فرستد."""
    import time
    from pathlib import Path

    from django.http import HttpResponse

    from integrations.bale_client import download_file_bytes, get_channel_info, get_file

    ch = Channel.objects.filter(id=channel_id).first()
    if not ch or not (ch.link or '').strip():
        return HttpResponse(status=404)
    cache = Path('/tmp/lb-avatars')
    cache.mkdir(parents=True, exist_ok=True)
    blob = cache / f'{ch.id}.img'
    kind = cache / f'{ch.id}.type'
    miss = cache / f'{ch.id}.none'
    fresh = 86400
    now = time.time()
    if blob.is_file() and now - blob.stat().st_mtime < fresh:
        ctype = kind.read_text(encoding='utf-8') if kind.is_file() else 'image/jpeg'
        resp = HttpResponse(blob.read_bytes(), content_type=ctype)
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    if miss.is_file() and now - miss.stat().st_mtime < fresh:
        return HttpResponse(status=404)

    def _miss() -> HttpResponse:
        miss.write_bytes(b'')
        return HttpResponse(status=404)

    info = get_channel_info(ch.link)
    photo = (info.get('raw') or {}).get('photo') or {}
    file_id = photo.get('small_file_id') or photo.get('big_file_id') or ''
    if not file_id:
        return _miss()
    meta = get_file(str(file_id))
    file_path = str((meta.get('result') or {}).get('file_path') or '')
    if not file_path:
        return _miss()
    data = download_file_bytes(file_path)
    if not data:
        return _miss()
    ctype = _avatar_type(data)
    blob.write_bytes(data)
    kind.write_text(ctype, encoding='utf-8')
    miss.unlink(missing_ok=True)
    resp = HttpResponse(data, content_type=ctype)
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_assign_manager(request: HttpRequest) -> JsonResponse:
    """پشتیبان: @manager را مالک کانال‌های @1 @2 … می‌کند (بدون چک بیو)."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبان.'}, status=403)
    body = _json_body(request)
    mgr_raw = str(body.get('manager') or body.get('username') or '').strip()
    mgr_key = _norm_username(mgr_raw)
    if not mgr_key:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'نام کاربری مدیر را بنویسید (مثل @test).'}, status=400)
    refs = body.get('channels') or body.get('channel_list') or []
    if isinstance(refs, str):
        refs = re.split(r'[,\s]+', refs)
    refs = [str(x).strip() for x in refs if str(x).strip()]
    if not refs:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'حداقل یک کانال (@name) لازم است.'}, status=400)

    from django.contrib.auth import get_user_model
    UserModel = get_user_model()
    manager = (
        UserModel.objects.filter(bale_username__iexact=mgr_key).first()
        or UserModel.objects.filter(bale_username__iexact='@' + mgr_key).first()
    )

    created, updated, pending = [], [], []
    from integrations.bale_client import get_channel_info

    for ref in refs:
        key = _channel_ref_key(ref)
        if not key:
            continue
        link = f'ble.ir/{key}'
        # نام واقعی از دستیار / API بله
        display_name = key
        peer = None
        about = ''
        try:
            info = get_channel_info(link)
            title = str(info.get('title') or '').strip()
            if title and title not in ('(no title)',):
                display_name = title[:200]
            if info.get('id'):
                try:
                    peer = int(info['id'])
                except (TypeError, ValueError):
                    peer = None
            about = str(info.get('bio') or info.get('description') or '')[:4000]
        except Exception:
            logger.exception('channel info on assign %s', key)

        ch = (
            Channel.objects.filter(link__icontains=key).order_by('-id').first()
            or Channel.objects.filter(name__iexact=key).first()
            or Channel.objects.filter(name__iexact='@' + key).first()
        )
        if ch is None:
            ch = Channel(
                name=display_name,
                link=link,
                publish_mode=Channel.PUBLISH_MANUAL,
                ownership_verified=True,
                bale_peer_id=peer,
                about=about,
            )
            created.append(key)
        else:
            updated.append(key)
            # اگر هنوز فقط شناسه است، با عنوان واقعی عوض کن
            if not ch.name or ch.name.lower() in (key, '@' + key, link):
                ch.name = display_name
            if peer and not ch.bale_peer_id:
                ch.bale_peer_id = peer
            if about and not ch.about:
                ch.about = about
        ch.link = link
        ch.ownership_verified = True
        if manager is not None:
            ch.manager = manager
            ch.pending_manager_username = ''
        else:
            ch.manager = None
            ch.pending_manager_username = mgr_key
            pending.append(key)
        ch.save()
        try:
            from integrations.channel_stats import refresh_channel
            refresh_channel(ch)
            ch.refresh_from_db()
            # بعد از آمار، اگر عنوان بهتری در DB نبود همان display_name بماند
            if ch.name in (key, '@' + key) and display_name != key:
                ch.name = display_name
                ch.save(update_fields=['name'])
        except Exception:
            logger.exception('stats after operator assign')

    return JsonResponse({
        'ok': True,
        'manager': mgr_key,
        'manager_found': manager is not None,
        'manager_id': manager.id if manager else None,
        'created': created,
        'updated': updated,
        'pending_claim': pending,
        'message': (
            f'کانال‌ها برای @{mgr_key} ثبت شد.'
            + (' مدیر هنوز وارد بازو نشده؛ با اولین ورود مالک می‌شود.' if manager is None else '')
        ),
    })


@csrf_exempt
@require_http_methods(['GET'])
def api_operator_assignments(request: HttpRequest) -> JsonResponse:
    """لیست کانال‌های انتساب‌داده‌شده / در انتظار claim."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    rows = []
    qs = Channel.objects.filter(ownership_verified=True).select_related('manager').order_by('-id')[:200]
    for ch in qs:
        uname = (ch.manager.bale_username if ch.manager_id else '') or ch.pending_manager_username
        rows.append({
            'id': ch.id,
            'name': ch.name,
            'link': ch.link,
            'manager_username': uname,
            'manager_label': (f'@{str(uname).lstrip("@")}' if uname else '—'),
            'pending': bool(ch.pending_manager_username and not ch.manager_id),
            'is_listed': bool(ch.is_listed),
        })
    return JsonResponse({'ok': True, 'items': rows})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_unassign(request: HttpRequest) -> JsonResponse:
    """برداشتن مالکیت تأییدشده از یک کانال."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    body = _json_body(request)
    ch = Channel.objects.filter(id=body.get('channel_id')).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    ch.manager = None
    ch.ownership_verified = False
    ch.pending_manager_username = ''
    ch.save(update_fields=['manager', 'ownership_verified', 'pending_manager_username'])
    return JsonResponse({'ok': True})



@csrf_exempt
@require_http_methods(['POST'])
def api_operator_test_publish(request: HttpRequest) -> JsonResponse:
    """پشتیبان: تست فوروارد بنر از لینک‌بانک به کانال — بدون سفارش/پرداخت."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبان.'}, status=403)
    body = _json_body(request)
    ch_raw = body.get('channel') or body.get('channel_id') or body.get('link') or ''
    ch = None
    if str(ch_raw).isdigit():
        ch = Channel.objects.filter(id=int(ch_raw)).first()
    if ch is None:
        key = _channel_ref_key(str(ch_raw))
        if key:
            ch = (
                Channel.objects.filter(link__icontains=key).order_by('-id').first()
                or Channel.objects.filter(name__iexact=key).first()
            )
    if ch is None:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کانال پیدا نشد.'}, status=404)

    from_chat = str(body.get('from_chat_id') or '').strip()
    msg_id = body.get('message_id')
    caption = str(body.get('caption') or '')
    banner_id = body.get('banner_id')

    if banner_id:
        from orders.models import CustomerBanner
        bn = CustomerBanner.objects.filter(id=int(banner_id)).first()
        if not bn:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'بنر پیدا نشد.'}, status=404)
        if bn.from_linkbank and bn.linkbank_message_id:
            from_chat = str(bn.linkbank_chat_id or from_chat)
            msg_id = bn.linkbank_message_id
        elif bn.storage_message_id:
            # هنوز باید از لینک‌بانک باشد؛ اگر لینک‌بانک ندارد خطا
            if not bn.linkbank_message_id:
                return JsonResponse({
                    'ok': False,
                    'error': 'not_on_linkbank',
                    'message': 'این بنر در لینک‌بانک نیست؛ فقط بنر تأییدشده قابل فوروارد است.',
                }, status=400)
            from_chat = str(bn.linkbank_chat_id or from_chat)
            msg_id = bn.linkbank_message_id
        caption = caption or (bn.caption or '')

    if not from_chat or not msg_id:
        from orders.models import CustomerBanner
        bn = (
            CustomerBanner.objects.filter(from_linkbank=True)
            .exclude(linkbank_message_id='')
            .order_by('-id')
            .first()
        )
        if bn:
            from_chat = str(bn.linkbank_chat_id or '')
            msg_id = bn.linkbank_message_id
            caption = caption or (bn.caption or '')
            banner_id = bn.id

    if not from_chat or not msg_id:
        return JsonResponse({
            'ok': False,
            'error': 'bad_fields',
            'message': 'منبع بنر در لینک‌بانک لازم است (banner_id تأییدشده).',
        }, status=400)

    # تست آپلود+فوروارد — قبل از اعتبارسنجی mode
    if body.get('upload_then_forward') or str(body.get('mode') or '').strip().lower() == 'upload_then_forward':
        from orders.publish import test_upload_then_forward_same_channel
        try:
            result = test_upload_then_forward_same_channel(
                ch, int(banner_id) if banner_id else None,
            )
        except Exception as e:
            logger.exception('upload_then_forward test')
            return JsonResponse({'ok': False, 'error': 'exception', 'message': str(e)[:200]}, status=500)
        return JsonResponse(result)

    mode = str(body.get('mode') or '').strip().lower() or 'linkyar'
    if mode not in ('bot', 'linkyar', 'manual'):
        mode = 'linkyar'

    try:
        delete_after = int(body.get('delete_after_minutes') or 0)
    except (TypeError, ValueError):
        delete_after = 0
    try:
        delay_min = int(body.get('delay_minutes') or body.get('send_after_minutes') or 0)
    except (TypeError, ValueError):
        delay_min = 0

    from orders.publish import test_publish_to_channel
    import threading
    import time as _time

    def _run():
        return test_publish_to_channel(
            ch,
            from_chat,
            int(msg_id),
            mode=mode,
            caption=caption,
            delete_after_minutes=delete_after,
            banner_id=int(banner_id) if banner_id else None,
        )

    if delay_min > 0:
        def _delayed():
            try:
                _time.sleep(max(1, delay_min) * 60)
                _run()
            except Exception:
                logger.exception('delayed test publish')

        threading.Thread(target=_delayed, daemon=True, name='test-pub-delay').start()
        return JsonResponse({
            'ok': True,
            'scheduled': True,
            'delay_minutes': delay_min,
            'channel_id': ch.id,
            'channel_name': ch.name,
            'mode': mode or ch.publish_mode,
            'message': f'ارسال تست برای {delay_min} دقیقه دیگر زمان‌بندی شد.',
            'banner_id': banner_id,
        })

    try:
        result = _run()
    except Exception as e:
        logger.exception('test_publish')
        return JsonResponse({'ok': False, 'error': 'exception', 'message': str(e)[:200]}, status=500)
    result['banner_id'] = banner_id
    result['from_chat_id'] = from_chat
    result['message_id'] = int(msg_id)
    result['bot_is_admin'] = bool(ch.bot_is_admin)
    result['linkyar_is_admin'] = bool(ch.linkyar_is_admin)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_test_delete(request: HttpRequest) -> JsonResponse:
    """حذف دستی پست تستی (بازو یا لینک‌یار)."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    body = _json_body(request)
    from orders.publish import delete_test_post, channel_ref
    ch_raw = body.get('channel') or body.get('channel_id') or body.get('ref') or ''
    ref = str(ch_raw)
    if str(ch_raw).isdigit():
        ch = Channel.objects.filter(id=int(ch_raw)).first()
        if ch:
            ref = channel_ref(ch)
    result = delete_test_post(
        ref,
        mode=str(body.get('mode') or 'bot'),
        bot_message_id=int(body['bot_message_id']) if body.get('bot_message_id') else None,
        ly_message_id=int(body['ly_message_id']) if body.get('ly_message_id') else None,
        ly_message_date=int(body.get('ly_message_date') or 0),
    )
    return JsonResponse(result)



@csrf_exempt
@require_http_methods(['GET'])
def api_operator_test_banners(request: HttpRequest) -> JsonResponse:
    """بنرهای تأییدشده و کانال‌ها برای تست ارسال پشتیبان."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    from orders.models import CustomerBanner
    from orders.banner_media import public_media_url
    rows = []
    qs = list(CustomerBanner.objects.filter(is_active=True, from_linkbank=True).order_by('-id')[:50])
    seen = {b.id for b in qs}
    for b in CustomerBanner.objects.filter(is_active=True).exclude(linkbank_message_id='').order_by('-id')[:30]:
        if b.id not in seen:
            qs.append(b)
            seen.add(b.id)
    for bn in qs:
        media = ''
        try:
            media = public_media_url(bn) or ''
        except Exception:
            media = ''
        rows.append({
            'id': bn.id,
            'title': bn.display_title(),
            'caption': (bn.caption or '')[:80],
            'has_source': bool(bn.linkbank_message_id),
            'from_linkbank': bool(bn.from_linkbank),
            'media_url': media,
            'media_kind': bn.media_kind or '',
            'linkbank_message_id': bn.linkbank_message_id or '',
        })
    channels = []
    for ch in Channel.objects.order_by('-id')[:100]:
        channels.append({
            'id': ch.id,
            'name': ch.name or ch.link or f'#{ch.id}',
            'link': ch.link,
            'publish_mode': ch.publish_mode or 'manual',
            'bot_is_admin': bool(ch.bot_is_admin),
            'linkyar_is_admin': bool(ch.linkyar_is_admin),
            'is_listed': bool(getattr(ch, 'is_listed', True)),
        })
    return JsonResponse({
        'ok': True,
        'banners': rows,
        'channels': channels,
        'counts': {'banners': len(rows), 'channels': len(channels)},
    })


