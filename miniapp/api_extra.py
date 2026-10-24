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
@require_http_methods(['GET', 'POST'])
def api_catalog(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    body = {}
    try:
        if request.method == 'POST':
            body = _json_body(request) or {}
    except Exception:
        body = {}
    needle = (request.GET.get('q') or body.get('q') or '').strip().casefold()
    ready_only = str(request.GET.get('ready') or body.get('ready') or '').strip().lower() in ('1', 'true', 'yes')

    def _text_match(ch) -> bool:
        if not needle:
            return True
        hay = f'{ch.name or ""}\n{ch.about or ""}\n{ch.description or ""}'.casefold()
        return needle in hay

    # موضوع تبلیغ مشتری برای فیلتر کانال‌های ممنوع
    customer_primary = (request.GET.get('topic') or body.get('topic') or '').strip()
    customer_secondary = body.get('topics') or body.get('secondary_topics') or []
    if isinstance(customer_secondary, str):
        customer_secondary = [x.strip() for x in customer_secondary.split(',') if x.strip()]
    if not customer_primary and user is not None:
        try:
            from orders.models import CustomerBusiness
            biz = CustomerBusiness.objects.filter(customer=user).order_by('-id').first()
            if biz:
                customer_primary = (biz.primary_topic or '').strip()
                customer_secondary = list(biz.secondary_topics or [])
        except Exception:
            pass
    customer_topics_active = bool(customer_primary or customer_secondary)

    # مدیران مسدودکننده این مشتری
    blocked_manager_ids = set()
    try:
        from orders.models import ManagerCustomerBlock
        blocked_manager_ids = set(
            ManagerCustomerBlock.objects.filter(customer=user).values_list('manager_id', flat=True)
        )
    except Exception:
        pass

    def _tariff_ok(t) -> bool:
        if t.channel_id:
            chans = [t.channel]
        elif t.group_id:
            chans = list(t.group.channels.all())
        else:
            chans = []
        # آرشیو: کانال تکی مخفی؛ پکیج فقط اگر حداقل یک کانال لیست‌شده داشته باشد
        if t.channel_id and not getattr(t.channel, 'is_listed', True):
            return False
        if t.group_id and not any(getattr(ch, 'is_listed', True) for ch in chans):
            return False
        if needle and not any(_text_match(ch) for ch in chans):
            return False
        if ready_only and (not chans or any(not _ready_publish(ch) for ch in chans)):
            return False
        if blocked_manager_ids:
            for ch in chans:
                mid = getattr(ch, 'manager_id', None)
                if mid and mid in blocked_manager_ids:
                    return False
            if t.group_id and getattr(t.group, 'manager_id', None) in blocked_manager_ids:
                return False
        # فیلتر موضوع ممنوعه کانال در برابر موضوع کسب‌وکار/بنر مشتری
        if customer_topics_active:
            from config.categories import topics_blocked
            for ch in chans:
                banned = getattr(ch, 'forbidden_topics', None) or []
                if topics_blocked(banned, customer_primary, customer_secondary):
                    return False
        return True

    # اگر همهٔ تعرفه‌های یک کانال لیست‌شده خاموش شده‌اند (مثلاً بعد از audit ادمین)،
    # برای حالت manual دوباره روشن کن تا در کاتالوگ مشتری دیده شوند.
    try:
        from channels_app.models import Channel
        for ch in Channel.objects.filter(is_listed=True).iterator():
            has_active = Tariff.objects.filter(channel=ch, is_active=True).exists()
            if has_active:
                continue
            inactive = Tariff.objects.filter(channel=ch, is_active=False)
            if inactive.exists() and (ch.publish_mode or 'manual') == 'manual':
                inactive.update(is_active=True)
            elif inactive.exists() and ch.publish_mode == 'bot' and ch.bot_is_admin:
                inactive.update(is_active=True)
            elif inactive.exists() and ch.publish_mode == 'linkyar' and ch.linkyar_is_admin:
                inactive.update(is_active=True)
    except Exception:
        pass

    try:
        qs = list(
            Tariff.objects.filter(is_active=True)
            .select_related('channel', 'group')
            .prefetch_related('group__channels')
            .order_by('-channel__members_count', 'price', 'id')[:400]
        )
    except Exception:
        qs = []
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
            'list_price': t.price,
            'discount': None,
            'duration_hours': t.duration_hours,
            'start_hour': t.start_hour,
            'is_active': t.is_active,
            'owner': t.group.name if t.group_id else (t.channel.name if t.channel_id else ''),
            'channel_id': t.channel_id,
            'group_id': t.group_id,
            'is_package': bool(t.group_id),
            'channel_count': (
                t.group.channels.count() if t.group_id else (1 if t.channel_id else 0)
            ),
            'members_count': (
                sum(ch.members_count or 0 for ch in t.group.channels.all())
                if t.group_id
                else ((t.channel.members_count if t.channel_id else 0) or 0)
            ),
            'avg_views': (
                int(
                    sum(ch.avg_views or 0 for ch in t.group.channels.all())
                    / max(1, t.group.channels.count())
                )
                if t.group_id
                else ((t.channel.avg_views if t.channel_id else 0) or 0)
            ),
        })
        disc = active_discount_for(t)
        if disc:
            items[-1]['discount'] = {
                'id': disc.id,
                'percent': disc.percent,
                'fixed_amount': disc.fixed_amount,
                'ends_at': disc.ends_at.isoformat() if disc.ends_at else '',
                'label': 'تخفیف ویژه',
            }
            items[-1]['price'] = disc.discounted_price(t.price)
        try:
            from orders.ratings import tariff_rating_stats, channel_rating_stats
            tr = tariff_rating_stats(t.id)
            items[-1]['rating_avg'] = tr['avg']
            items[-1]['rating_count'] = tr['count']
            items[-1]['rating_label'] = 'بدون نظر' if not tr['count'] else None
            if t.channel_id:
                cr = channel_rating_stats(t.channel_id)
                items[-1]['channel_rating_avg'] = cr['avg'] if cr['show_in_list'] else None
                items[-1]['channel_rating_count'] = cr['count']
                items[-1]['channel_popularity'] = cr['popularity']
            # هشدار موضوع ممنوعه (مخفی نکن)
            try:
                from config.categories import flatten_selected, topic_label
                cust_topics = flatten_selected(customer_primary, customer_secondary)
                forb = set()
                for ch in chans:
                    forb |= set(getattr(ch, 'forbidden_topics', None) or [])
                overlap = sorted(cust_topics & forb)
                if overlap:
                    items[-1]['forbidden_warn'] = {
                        'count': len(overlap),
                        'topics': [{'code': c, 'label': topic_label(c)} for c in overlap],
                        'message': f'{len(overlap)} موضوع از دسته‌بندی‌های شما در این کانال تبلیغ نمی‌شود',
                    }
            except Exception:
                pass

        except Exception:
            pass

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

    try:
        history = recent_snapshots(list(channels.keys()))
    except Exception:
        history = {}
    growth = _weekly_member_changes(list(channels.keys()))
    for cid, payload in channels.items():
        payload['history'] = history.get(cid) or []
        payload['week_growth'] = growth.get(cid)
    languages: dict = {}
    for payload in channels.values():
        lang = (payload.get('language') or '').strip()
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
    try:
        language_rows = [
            {'language': lang, 'count': count}
            for lang, count in sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    except Exception:
        language_rows = []
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
    import logging
    log = logging.getLogger(__name__)
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        if not user.bale_user_id:
            return JsonResponse({'ok': False, 'error': 'no_user', 'message': 'شناسه بله کاربر مشخص نیست.'}, status=200)
        body = _json_body(request) or {}
        try:
            item_id = int(body.get('item_id') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'سفارش پیدا نشد.'}, status=200)
        result = process_manager_item(item_id, str(user.bale_user_id), action)
        if not result.get('ok'):
            from miniapp.api import _with_message
            payload = _with_message(result) if callable(_with_message) else result
            if not isinstance(payload, dict):
                payload = {'ok': False, 'error': result.get('error') or 'error'}
            payload.setdefault('message', result.get('message') or result.get('error') or 'انجام نشد')
            return JsonResponse(payload, status=200)
        return JsonResponse(result if isinstance(result, dict) else {'ok': True})
    except Exception as exc:
        log.exception('_set_item_status %s', action)
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'عملیات سفارش نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_order_approve(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'approve')


@csrf_exempt
@require_http_methods(['POST'])
def api_order_reject(request: HttpRequest) -> JsonResponse:
    return _set_item_status(request, 'reject')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_operator_payouts(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبانی.'}, status=200)
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
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبانی.'}, status=200)
    from bot_flow.messages import user_error

    return JsonResponse(
        {'ok': False, 'error': 'use_bot', 'message': user_error('use_bot') or 'این کار را از بازو انجام دهید.'},
        status=200,
    )


def active_discount_for(tariff, now=None):
    from django.utils import timezone
    from orders.models import TariffDiscount
    now = now or timezone.now()
    qs = TariffDiscount.objects.filter(
        is_active=True, starts_at__lte=now, ends_at__gt=now, tariffs=tariff,
    ).order_by('-id')
    return qs.first()
