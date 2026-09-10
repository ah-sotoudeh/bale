"""Mini-app shop APIs: banners, cart, calendar, tariff edit, operator banners."""
from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot_flow.jalali import format_jalali
from channels_app.models import Channel, Tariff
from miniapp.api import _auth_user, _json_body
from orders import cart as cart_svc
from orders.availability import (
    clear_manual_busy_slot,
    day_status_map,
    list_manual_busy_slots,
    mark_tariff_day_busy,
)
from orders.banner_publish import operator_decide
from orders.models import BannerPublishRequest, CustomerBanner, Order, OrderItem
from wallet import services as ws


ERR_FA = {
    'not_found': 'پیدا نشد.',
    'forbidden': 'اجازه این کار را ندارید.',
    'bad_fields': 'اطلاعات ناقص است.',
    'bad_date': 'تاریخ نامعتبر است.',
    'empty_cart': 'سبد خرید خالی است.',
    'no_banner': 'ابتدا یک بنر از کانال مرجع انتخاب کنید.',
    'slot_conflict': 'این نوبت پر است. روز دیگری انتخاب کنید.',
    'no_channel': 'کانالی برای این تعرفه نیست.',
    'already_pending': 'یک درخواست تسویه باز دارید.',
    'weekly_limit': 'هر هفته فقط یک بار می‌توانید تسویه بزنید.',
    'below_minimum': 'حداقل مبلغ تسویه صدهزار تومان است.',
    'no_bank': 'ابتدا شماره شبا ثبت کنید.',
    'invalid_iban': 'شماره شبا معتبر نیست.',
    'need_holder_name': 'نام صاحب حساب لازم است.',
    'not_pending': 'این سفارش دیگر در انتظار نیست.',
    'inactive': 'این تعرفه فعال نیست.',
}


def _err(code: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'ok': False, 'error': code, 'message': ERR_FA.get(code, 'خطا')}, status=status)


def _parse_day(body) -> object | None:
    raw = str(body.get('date') or '')[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _own_tariff(user, tariff_id):
    t = Tariff.objects.select_related('channel', 'group').filter(id=tariff_id).first()
    if not t:
        return None
    ok = (t.channel and t.channel.manager_id == user.id) or (t.group and t.group.manager_id == user.id)
    return t if ok else False


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
        return _err('not_found', 404)
    mode = body.get('publish_mode')
    if mode not in (Channel.PUBLISH_BOT, Channel.PUBLISH_LINKYAR, Channel.PUBLISH_MANUAL):
        return JsonResponse({'ok': False, 'error': 'bad_mode', 'message': 'حالت ارسال نامعتبر است.'}, status=400)
    ch.publish_mode = mode
    fields = ['publish_mode']
    hours = body.get('remind_hours')
    if hours is not None and str(hours) != '':
        try:
            ch.manual_remind_hours = max(1, min(48, int(hours)))
            fields.append('manual_remind_hours')
        except (TypeError, ValueError):
            pass
    ch.save(update_fields=fields)
    return JsonResponse({
        'ok': True,
        'channel_id': ch.id,
        'publish_mode': ch.publish_mode,
        'manual_remind_hours': ch.manual_remind_hours,
    })


@csrf_exempt
@require_http_methods(['GET'])
def api_calendar(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    t = _own_tariff(user, request.GET.get('tariff_id'))
    customer = request.GET.get('for') == 'customer'
    if customer:
        t = Tariff.objects.select_related('channel', 'group').filter(
            id=request.GET.get('tariff_id'), is_active=True
        ).first()
        if not t:
            return _err('not_found', 404)
    elif t is None:
        return _err('not_found', 404)
    elif t is False:
        return _err('forbidden', 403)
    days = []
    for d, free in day_status_map(t, 14):
        days.append({
            'date': d.isoformat(),
            'jalali': format_jalali(d),
            'free': free,
        })
    busy_slots = []
    if not customer:
        for s in list_manual_busy_slots(t):
            day = timezone.localtime(s.start).date() if timezone.is_aware(s.start) else s.start.date()
            busy_slots.append({
                'id': s.id,
                'date': day.isoformat(),
                'jalali': format_jalali(day),
            })
    return JsonResponse({
        'ok': True,
        'tariff_id': t.id,
        'name': t.name,
        'owner': t.group.name if t.group_id else (t.channel.name if t.channel_id else ''),
        'days': days,
        'manual_busy': busy_slots,
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_busy_day(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    t = _own_tariff(user, body.get('tariff_id'))
    if t is None:
        return _err('not_found', 404)
    if t is False:
        return _err('forbidden', 403)
    day = _parse_day(body)
    if not day:
        return _err('bad_date')
    slot = mark_tariff_day_busy(t, day)
    return JsonResponse({'ok': True, 'slot_id': slot.id, 'jalali': format_jalali(day)})


@csrf_exempt
@require_http_methods(['POST'])
def api_clear_busy(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    t = _own_tariff(user, body.get('tariff_id'))
    if t is None:
        return _err('not_found', 404)
    if t is False:
        return _err('forbidden', 403)
    ok = clear_manual_busy_slot(int(body.get('slot_id') or 0), t)
    if not ok:
        return _err('not_found', 404)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(['POST'])
def api_tariff_update(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    t = _own_tariff(user, body.get('tariff_id'))
    if t is None:
        return _err('not_found', 404)
    if t is False:
        return _err('forbidden', 403)
    fields = []
    if 'name' in body and str(body['name']).strip():
        t.name = str(body['name']).strip()[:100]
        fields.append('name')
    if 'price' in body and str(body['price']) != '':
        t.price = int(body['price'])
        fields.append('price')
    if 'duration_hours' in body and str(body['duration_hours']) != '':
        t.duration_hours = int(body['duration_hours'])
        fields.append('duration_hours')
    if 'start_hour' in body and str(body['start_hour']) != '':
        t.start_hour = int(body['start_hour'])
        fields.append('start_hour')
    if 'is_active' in body:
        t.is_active = bool(body['is_active'])
        fields.append('is_active')
    if not fields:
        return _err('bad_fields')
    t.save(update_fields=fields)
    return JsonResponse({'ok': True, 'tariff_id': t.id})


@csrf_exempt
@require_http_methods(['GET'])
def api_banners(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    rows = []
    for b in CustomerBanner.objects.filter(customer=user, is_active=True)[:40]:
        rows.append({
            'id': b.id,
            'title': b.display_title(),
            'caption': b.caption or '',
            'from_linkbank': b.from_linkbank,
            'media_kind': b.media_kind,
        })
    return JsonResponse({'ok': True, 'banners': rows})


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_rename(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    b = CustomerBanner.objects.filter(id=body.get('banner_id'), customer=user).first()
    if not b:
        return _err('not_found', 404)
    title = str(body.get('title') or '').strip()[:120]
    if not title:
        return _err('bad_fields')
    b.title = title
    b.save(update_fields=['title'])
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(['GET'])
def api_cart(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    order = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
    items = []
    total = 0
    if order:
        for it in order.items.filter(manager_status='cart').select_related('tariff', 'channel', 'tariff__group'):
            start = timezone.localtime(it.requested_start)
            items.append({
                'id': it.id,
                'owner': it.tariff.group.name if it.tariff.group_id else (it.channel.name if it.channel else ''),
                'name': it.tariff.name,
                'date': start.date().isoformat(),
                'jalali': format_jalali(start.date()),
                'price': it.price,
            })
        total = order.total_amount
    banner = None
    if order and order.customer_banner_id:
        cb = order.customer_banner
        banner = {'id': cb.id, 'title': cb.display_title()}
    return JsonResponse({
        'ok': True,
        'order_id': order.id if order else None,
        'items': items,
        'total': total,
        'banner': banner,
        'has_banner': bool(order and order.banner_message_id),
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_add(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    t = Tariff.objects.select_related('channel', 'group').filter(id=body.get('tariff_id'), is_active=True).first()
    if not t:
        return _err('not_found', 404)
    day = _parse_day(body)
    if not day:
        return _err('bad_date')
    r = cart_svc.add_to_cart(user, t, day)
    if not r.get('ok'):
        return _err(r.get('error') or 'slot_conflict')
    return JsonResponse({'ok': True, 'item_id': r['item'].id, 'order_id': r['order'].id})


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_remove(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    it = OrderItem.objects.filter(
        id=body.get('item_id'), order__customer=user, manager_status='cart'
    ).first()
    if not it:
        return _err('not_found', 404)
    order = it.order
    it.delete()
    order.recompute_total()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_banner(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    b = CustomerBanner.objects.filter(
        id=body.get('banner_id'), customer=user, is_active=True, from_linkbank=True
    ).first()
    if not b:
        return _err('no_banner')
    order = cart_svc.get_or_create_draft(user)
    order.customer_banner = b
    order.banner_from_chat_id = b.storage_chat_id
    order.banner_message_id = b.storage_message_id
    order.banner_caption = b.caption or ''
    order.save()
    return JsonResponse({'ok': True, 'banner_id': b.id})


@csrf_exempt
@require_http_methods(['POST'])
def api_checkout(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    order = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
    if not order:
        return _err('empty_cart')
    r = cart_svc.checkout(order)
    if not r.get('ok'):
        return _err(r.get('error') or 'empty_cart')
    return JsonResponse({'ok': True, 'order_id': order.id, 'count': r.get('count')})


@csrf_exempt
@require_http_methods(['GET'])
def api_my_orders(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    rows = []
    for o in Order.objects.filter(customer=user).exclude(status='draft').order_by('-id')[:30]:
        rows.append({
            'id': o.id,
            'status': o.status,
            'total': o.total_amount,
            'created': format_jalali(timezone.localtime(o.created_at).date()) if o.created_at else '',
        })
    return JsonResponse({'ok': True, 'orders': rows})


@csrf_exempt
@require_http_methods(['GET'])
def api_operator_banners(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return _err('forbidden', 403)
    rows = []
    for r in BannerPublishRequest.objects.filter(status='pending').select_related('customer').order_by('id')[:50]:
        rows.append({
            'id': r.id,
            'customer': r.customer.bale_user_id,
            'fee_toman': r.fee_toman,
            'caption': (r.caption or '')[:80],
        })
    return JsonResponse({'ok': True, 'requests': rows})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_banner_decide(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return _err('forbidden', 403)
    body = _json_body(request)
    r = operator_decide(int(body.get('request_id') or 0), str(user.bale_user_id), bool(body.get('approve')))
    if not r.get('ok'):
        return JsonResponse(
            {'ok': False, 'error': r.get('error'), 'message': r.get('message') or ERR_FA.get(r.get('error') or '', 'خطا')},
            status=400,
        )
    return JsonResponse({'ok': True, 'message': r.get('message') or 'ثبت شد'})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_paid(request: HttpRequest) -> JsonResponse:
    """Build batch from pending payouts then mark paid (notifies managers)."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return _err('forbidden', 403)
    built = ws.build_payout_batch(user)
    if not built.get('ok'):
        return JsonResponse({'ok': False, 'error': built.get('error'), 'message': 'درخواست بازی نیست.'}, status=400)
    marked = ws.mark_batch_paid(built['batch'].id)
    return JsonResponse({
        'ok': True,
        'file_text': built.get('file_text') or '',
        'count': built.get('count') or 0,
        'notified': len(marked.get('notified') or []),
    })
