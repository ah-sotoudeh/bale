"""تیکت پشتیبانی واقعی."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from miniapp.api import _auth_user, _json_body
from orders.models import SupportTicket, SupportTicketMessage
from users import access as ws


def _ticket_payload(t: SupportTicket, *, with_messages: bool = False) -> dict:
    row = {
        'id': t.id,
        'subject': t.subject,
        'category': t.category,
        'status': t.status,
        'order_id': t.order_id_ref,
        'created_at': t.created_at.isoformat() if t.created_at else '',
        'updated_at': t.updated_at.isoformat() if t.updated_at else '',
    }
    if with_messages:
        row['messages'] = [
            {
                'id': m.id,
                'body': m.body,
                'is_staff': m.is_staff,
                'created_at': m.created_at.isoformat() if m.created_at else '',
            }
            for m in t.messages.all()[:100]
        ]
    return row


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_tickets(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    is_op = ws.is_operator(user.bale_user_id or '')

    if request.method == 'GET':
        if is_op:
            qs = SupportTicket.objects.all()[:50]
        else:
            qs = SupportTicket.objects.filter(customer=user)[:40]
        return JsonResponse({
            'ok': True,
            'tickets': [_ticket_payload(t) for t in qs],
        })

    body = _json_body(request) or {}
    subject = str(body.get('subject') or body.get('topic') or '').strip()[:160]
    message = str(body.get('message') or body.get('body') or '').strip()
    category = str(body.get('category') or 'other').strip()[:32] or 'other'
    if len(subject) < 2:
        subject = {
            'order': 'سفارش و انتشار',
            'wallet': 'کیف پول و پرداخت',
            'banner': 'بنر',
            'business': 'کسب‌وکار',
        }.get(category, 'درخواست پشتیبانی')
    if len(message) < 5:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'متن تیکت کوتاه است.'}, status=200)
    order_id = None
    try:
        if body.get('order_id'):
            order_id = int(body.get('order_id'))
    except (TypeError, ValueError):
        order_id = None
    t = SupportTicket.objects.create(
        customer=user,
        subject=subject,
        category=category,
        status='open',
        order_id_ref=order_id,
    )
    SupportTicketMessage.objects.create(
        ticket=t, author=user, body=message[:4000], is_staff=False,
    )
    return JsonResponse({'ok': True, 'ticket': _ticket_payload(t, with_messages=True)})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_ticket_detail(request: HttpRequest, ticket_id: int) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    is_op = ws.is_operator(user.bale_user_id or '')
    t = SupportTicket.objects.filter(id=ticket_id).first()
    if not t:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    if not is_op and t.customer_id != user.id:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    if request.method == 'GET':
        return JsonResponse({'ok': True, 'ticket': _ticket_payload(t, with_messages=True)})

    body = _json_body(request) or {}
    message = str(body.get('message') or body.get('body') or '').strip()
    if len(message) < 1:
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'پیام خالی است.'}, status=200)
    SupportTicketMessage.objects.create(
        ticket=t,
        author=user,
        body=message[:4000],
        is_staff=bool(is_op),
    )
    if is_op:
        t.status = 'answered'
    else:
        t.status = 'customer_replied' if t.status != 'open' else 'open'
    t.updated_at = timezone.now()
    t.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'ok': True, 'ticket': _ticket_payload(t, with_messages=True)})


@csrf_exempt
@require_http_methods(['POST'])
def api_ticket_close(request: HttpRequest, ticket_id: int) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    is_op = ws.is_operator(user.bale_user_id or '')
    t = SupportTicket.objects.filter(id=ticket_id).first()
    if not t:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    if not is_op and t.customer_id != user.id:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    t.status = 'closed'
    t.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'ok': True, 'ticket_id': t.id, 'status': 'closed'})
