"""APIهای لغو، تغییر زمان، مسدودسازی، تخفیف، نظر."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from orders import cart as cart_svc
from orders.models import (
    ChannelReview,
    ManagerCustomerBlock,
    Order,
    OrderItem,
    TariffDiscount,
)
from orders.policy import (
    CANCEL_POLICY_TEXT,
    can_change_time,
    new_time_allowed,
)
from users import access as ws


@csrf_exempt
@require_http_methods(['GET'])
def api_cancel_policy(request: HttpRequest) -> JsonResponse:
    return JsonResponse({'ok': True, 'text': CANCEL_POLICY_TEXT, 'fee_percent': 14, 'min_hours': 48})


@csrf_exempt
@require_http_methods(['POST'])
def api_cancel_order(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    body = _json_body(request) or {}
    try:
        oid = int(body.get('order_id'))
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad_fields'}, status=200)
    order = Order.objects.filter(id=oid, customer=user).first()
    if not order:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=200)
    r = cart_svc.cancel_customer_order(order)
    return JsonResponse(r, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_request_time_change(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    body = _json_body(request) or {}
    try:
        iid = int(body.get('item_id'))
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad_fields'}, status=200)
    day = body.get('date') or body.get('day')
    item = OrderItem.objects.select_related('order', 'tariff', 'channel', 'manager').filter(
        id=iid, order__customer=user
    ).first()
    if not item:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=200)
    ok, code = can_change_time(item.effective_start, int(item.time_change_count or 0))
    if not ok:
        return JsonResponse({
            'ok': False,
            'error': code,
            'message': 'حداکثر ۲ بار تغییر زمان استفاده شده.' if code == 'max_changes' else 'تغییر زمان ممکن نیست.',
        }, status=200)
    if not day:
        return JsonResponse({'ok': False, 'error': 'bad_date'}, status=200)
    from datetime import date as date_cls
    try:
        parts = str(day).split('-')
        d = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return JsonResponse({'ok': False, 'error': 'bad_date'}, status=200)
    start, end = cart_svc.slot_for_day(item.tariff, d)
    ok2, code2 = new_time_allowed(start)
    if not ok2:
        return JsonResponse({
            'ok': False,
            'error': code2,
            'message': 'زمان جدید باید حداقل ۱۲ ساعت فاصله داشته باشد.',
        }, status=200)
    auto = bool(getattr(item.channel, 'auto_approve_time', False)) if item.channel_id else False
    item.time_change_count = int(item.time_change_count or 0) + 1
    if auto:
        item.requested_start = start
        item.requested_end = end
        item.manager_edited_start = None
        item.save(update_fields=['requested_start', 'requested_end', 'manager_edited_start', 'time_change_count'])
        return JsonResponse({'ok': True, 'item_id': item.id, 'date': d.isoformat(), 'auto': True})
    # نیاز به تأیید مدیر
    item.manager_edited_start = start
    item.manager_status = 'edited'
    item.save(update_fields=['manager_edited_start', 'manager_status', 'time_change_count'])
    mid = item.manager.bale_user_id if item.manager else ''
    if mid:
        from integrations import bale_client as bc
        bc.send_message(
            mid,
            f'مشتری برای آیتم {item.id} زمان جدید {d.isoformat()} پیشنهاد داده. تأیید یا رد کنید.',
        )
    return JsonResponse({'ok': True, 'item_id': item.id, 'date': d.isoformat(), 'auto': False, 'pending_manager': True})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_manager_blocks(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    if request.method == 'GET':
        rows = list(
            ManagerCustomerBlock.objects.filter(manager=user).select_related('customer')[:100]
        )
        return JsonResponse({
            'ok': True,
            'blocks': [
                {'customer_id': b.customer_id, 'bale_user_id': str(b.customer.bale_user_id or ''), 'note': b.note}
                for b in rows
            ],
        })
    body = _json_body(request) or {}
    action = str(body.get('action') or 'block').strip()
    try:
        cid = int(body.get('customer_id') or 0)
    except (TypeError, ValueError):
        cid = 0
    from django.contrib.auth import get_user_model
    User = get_user_model()
    cust = User.objects.filter(id=cid).first() if cid else None
    if not cust and body.get('bale_user_id'):
        cust = User.objects.filter(bale_user_id=str(body.get('bale_user_id'))).first()
    if not cust:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'مشتری پیدا نشد.'}, status=200)
    if action == 'unblock':
        ManagerCustomerBlock.objects.filter(manager=user, customer=cust).delete()
        return JsonResponse({'ok': True, 'unblocked': True})
    ManagerCustomerBlock.objects.get_or_create(
        manager=user, customer=cust, defaults={'note': str(body.get('note') or '')[:255]}
    )
    return JsonResponse({'ok': True, 'blocked': True})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_discounts(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    if request.method == 'GET':
        rows = TariffDiscount.objects.filter(manager=user).prefetch_related('tariffs').order_by('-id')[:50]
        out = []
        for d in rows:
            paid_sales = 0  # فقط پرداخت‌شده — محاسبه ساده از order items در بازه
            out.append({
                'id': d.id,
                'name': d.name,
                'percent': d.percent,
                'fixed_amount': d.fixed_amount,
                'starts_at': d.starts_at.isoformat(),
                'ends_at': d.ends_at.isoformat(),
                'is_active': d.is_active,
                'live': d.is_live(),
                'tariff_ids': list(d.tariffs.values_list('id', flat=True)),
                'sales_paid': paid_sales,
            })
        return JsonResponse({'ok': True, 'discounts': out})
    body = _json_body(request) or {}
    if body.get('deactivate_id'):
        d = TariffDiscount.objects.filter(id=int(body['deactivate_id']), manager=user).first()
        if not d:
            return JsonResponse({'ok': False, 'error': 'not_found'}, status=200)
        d.is_active = False
        d.save(update_fields=['is_active'])
        return JsonResponse({'ok': True, 'deactivated': True})
    
    from channels_app.models import Tariff
    from django.utils.dateparse import parse_datetime
    tids = body.get('tariff_ids') or []
    own = []
    for t in Tariff.objects.filter(id__in=tids).select_related('channel', 'group'):
        mid = t.channel.manager_id if t.channel_id else (t.group.manager_id if t.group_id else None)
        if mid == user.id:
            own.append(t)
    if not own:
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'تعرفه‌ای از شما انتخاب نشده.'}, status=200)
    now = timezone.now()
    for t in own:
        TariffDiscount.objects.filter(manager=user, is_active=True, tariffs=t).update(is_active=False)
    def _parse(s):
        dt = parse_datetime(str(s).replace('Z', '+00:00')) if s else None
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    starts = _parse(body.get('starts_at')) or now
    ends = _parse(body.get('ends_at'))
    if not ends or ends <= starts:
        return JsonResponse({'ok': False, 'error': 'bad_dates'}, status=200)
    d = TariffDiscount.objects.create(
        manager=user,
        name=str(body.get('name') or 'تخفیف ویژه')[:120],
        percent=int(body.get('percent') or 0),
        fixed_amount=int(body.get('fixed_amount') or 0),
        starts_at=starts,
        ends_at=ends,
        is_active=True,
    )
    d.tariffs.set(own)
    return JsonResponse({'ok': True, 'discount_id': d.id})


def api_reviews(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    if request.method == 'GET':
        channel_id = request.GET.get('channel_id')
        qs = ChannelReview.objects.filter(is_hidden=False)
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        sort = request.GET.get('sort') or 'newest'
        if sort == 'rating':
            qs = qs.order_by('-rating', '-id')
        elif sort == 'oldest':
            qs = qs.order_by('id')
        else:
            qs = qs.order_by('-id')
        rows = []
        for r in qs.select_related('channel')[:50]:
            rows.append({
                'id': r.id,
                'rating': r.rating,
                'body': r.body,
                'views_count': r.views_count,
                'reactions_count': r.reactions_count,
                'banner_link': r.banner_link,
                'tariff_name': r.tariff_name,
                'executed_at': r.executed_at.isoformat() if r.executed_at else '',
                'channel_id': r.channel_id,
                'channel_name': r.channel.name if r.channel_id else '',
            })
        return JsonResponse({'ok': True, 'reviews': rows})
    body = _json_body(request) or {}
    if body.get('delete_id'):
        r = ChannelReview.objects.filter(id=int(body['delete_id']), customer=user).first()
        if not r:
            if ws.is_operator(user.bale_user_id or ''):
                r = ChannelReview.objects.filter(id=int(body['delete_id'])).first()
                if r:
                    r.is_hidden = True
                    r.save(update_fields=['is_hidden'])
                    return JsonResponse({'ok': True, 'hidden': True})
            return JsonResponse({'ok': False, 'error': 'not_found'}, status=200)
        r.delete()
        return JsonResponse({'ok': True, 'deleted': True})
    try:
        iid = int(body.get('item_id'))
        rating = int(body.get('rating') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad_fields'}, status=200)
    if rating < 1 or rating > 5:
        return JsonResponse({'ok': False, 'error': 'bad_rating'}, status=200)
    item = OrderItem.objects.select_related('order', 'channel', 'tariff').filter(
        id=iid, order__customer=user, execution_status='executed'
    ).first()
    if not item or not item.channel_id:
        return JsonResponse({'ok': False, 'error': 'not_eligible', 'message': 'فقط پس از اجرای موفق می‌توانید نظر بدهید.'}, status=200)
    r, _ = ChannelReview.objects.update_or_create(
        order_item=item,
        defaults={
            'customer': user,
            'channel_id': item.channel_id,
            'rating': rating,
            'body': str(body.get('body') or '')[:2000],
            'views_count': int(body.get('views_count') or 0),
            'reactions_count': int(body.get('reactions_count') or 0),
            'banner_link': str(item.published_link or '')[:500],
            'tariff_name': item.tariff.name if item.tariff_id else '',
            'executed_at': item.executed_at or item.published_at,
        },
    )
    return JsonResponse({'ok': True, 'review_id': r.id})
