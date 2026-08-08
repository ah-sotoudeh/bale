from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderItem, ManagerResponse
from .serializers import OrderCreateSerializer
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import os
from integrations import bale_client
from django.utils.dateparse import parse_datetime
import logging

logger = logging.getLogger(__name__)


class OrderCreateView(APIView):
    def post(self, request):
        # Note: assumes user is authenticated via Bale and request.user is set
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            # notify managers: try forward banner, always send text + instructions
            for item in order.items.all():
                if not item.manager or not item.manager.bale_user_id:
                    continue
                manager_id = item.manager.bale_user_id
                # forward_message needs (to_chat_id, from_chat_id, message_id)
                if item.banner_message_id and order.customer.bale_user_id:
                    try:
                        msg_id = int(item.banner_message_id)
                        bale_client.forward_message(
                            to_chat_id=manager_id,
                            from_chat_id=order.customer.bale_user_id,
                            message_id=msg_id,
                        )
                    except (TypeError, ValueError):
                        logger.warning(
                            'banner_message_id not an int, skip forward: %s',
                            item.banner_message_id,
                        )
                bale_client.send_message(
                    manager_id,
                    f"درخواست تبلیغ جدید برای کانال {item.channel.name}\n"
                    f"زمان پیشنهادی: {item.requested_start} تا {item.requested_end}\n"
                    f"آیتم سفارش: #{item.id}\n"
                    f"برای قبول/ویرایش/رد از ربات استفاده کنید.",
                )
            return Response({'order_id': order.id, 'status': order.status})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ManagerResponseWebhook(APIView):
    def post(self, request):
        # webhook from bale manager action
        payload = request.data
        # expected: {"order_item_id": X, "manager_bale_id": "...", "action": "approve|reject|edit", "new_start": ...}
        item_id = payload.get('order_item_id')
        action = payload.get('action')
        manager_bale_id = payload.get('manager_bale_id')
        new_start = payload.get('new_start')
        item = get_object_or_404(OrderItem, id=item_id)
        from users.models import User
        try:
            manager = User.objects.get(bale_user_id=manager_bale_id)
        except User.DoesNotExist:
            return Response({'detail': 'manager not found'}, status=status.HTTP_404_NOT_FOUND)

        item.manager_status = (
            'approved' if action == 'approve'
            else ('rejected' if action == 'reject' else 'edited')
        )
        if action == 'edit' and new_start:
            item.manager_edited_start = parse_datetime(new_start)
        item.save()
        ManagerResponse.objects.create(
            order_item=item, manager=manager, action=action, payload=payload
        )

        order = item.order
        pending = order.items.filter(manager_status='pending').exists()
        if not pending:
            rejected_any = order.items.filter(manager_status='rejected').exists()
            if rejected_any:
                order.status = 'rejected'
                order.save()
                if order.customer.bale_user_id:
                    bale_client.send_message(
                        order.customer.bale_user_id,
                        f"متاسفیم، یکی از کانال‌ها سفارش شما را رد کرد. سفارش #{order.id} رد شد.",
                    )
            else:
                order.status = 'waiting_payment'
                order.save()
                callback = os.environ.get('WEBHOOK_BASE_URL')
                if callback:
                    callback = callback.rstrip('/') + '/api/webhooks/payment/'
                payment = bale_client.create_payment_request(
                    chat_id=order.customer.bale_user_id,
                    amount=order.total_amount,
                    callback_url=callback,
                    payload=f'order-{order.id}',
                    title=f'پرداخت سفارش #{order.id}',
                    description=f'هزینه تبلیغ — سفارش #{order.id}',
                )
                if payment.get('payment_url'):
                    bale_client.send_message(
                        order.customer.bale_user_id,
                        f"همه مدیران تایید کردند. لطفاً پرداخت را تکمیل کنید: {payment.get('payment_url')}",
                    )
                elif payment.get('ok'):
                    # invoice message already sent by create_payment_request / sendInvoice
                    bale_client.send_message(
                        order.customer.bale_user_id,
                        f"همه مدیران تایید کردند. فاکتور پرداخت برای سفارش #{order.id} ارسال شد.",
                    )
                else:
                    bale_client.send_message(
                        order.customer.bale_user_id,
                        f"همه مدیران تایید کردند. برای پرداخت سفارش #{order.id} لطفاً به ربات مراجعه کنید.",
                    )
        return Response({'ok': True})


@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhook(APIView):
    def post(self, request):
        payload = request.data
        order_id = payload.get('order_id')
        pay_status = payload.get('status')  # do not shadow rest_framework.status
        order = get_object_or_404(Order, id=order_id)
        if pay_status == 'paid':
            order.status = 'completed'
            order.save()
            for item in order.items.all():
                send_time = item.manager_edited_start if item.manager_edited_start else item.requested_start
                send_iso = send_time.isoformat() if send_time else ''
                channel_target = item.channel.link or str(item.channel.id)
                if bale_client.bot_is_channel_admin(channel_target):
                    if item.banner_message_id:
                        resp = bale_client.schedule_message(
                            channel_target,
                            {'forward_message_id': item.banner_message_id},
                            send_iso,
                        )
                        if resp.get('error') and item.manager and item.manager.bale_user_id:
                            bale_client.schedule_message(
                                item.manager.bale_user_id,
                                {'forward_message_id': item.banner_message_id},
                                send_iso,
                            )
                        else:
                            item.banner_forwarded = True
                            item.save()
                else:
                    if item.manager and item.manager.bale_user_id and item.banner_message_id:
                        bale_client.schedule_message(
                            item.manager.bale_user_id,
                            {'forward_message_id': item.banner_message_id},
                            send_iso,
                        )
                        item.banner_forwarded = True
                        item.save()
            if order.customer.bale_user_id:
                bale_client.send_message(
                    order.customer.bale_user_id,
                    f"سفارش شما #{order.id} با موفقیت ثبت و پرداخت شد. "
                    f"تبلیغات در زمان‌های مشخص منتشر خواهد شد.",
                )
        return Response({'ok': True})
