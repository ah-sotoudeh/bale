from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Order, OrderItem, ManagerResponse
from .serializers import OrderCreateSerializer
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import os
import requests
from integrations import bale_client
from django.utils.dateparse import parse_datetime

class OrderCreateView(APIView):
    def post(self, request):
        # Note: assumes user is authenticated via Bale and request.user is set
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            # notify managers: forward banner_message_id to each manager (if present)
            for item in order.items.all():
                if item.banner_message_id and item.manager:
                    # forward banner to manager and include action buttons via bale (placeholder)
                    bale_client.forward_message(item.manager.bale_user_id, item.banner_message_id)
                    bale_client.send_message(item.manager.bale_user_id, f"درخواست تبلیغ جدید برای کانال {item.channel.name}\nزمان پیشنهادی: {item.requested_start} تا {item.requested_end}\nبرای قبول/ویرایش/رد از ربات استفاده کنید.")
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
        # find manager user by bale_user_id
        from users.models import User
        try:
            manager = User.objects.get(bale_user_id=manager_bale_id)
        except User.DoesNotExist:
            return Response({'detail':'manager not found'}, status=status.HTTP_404_NOT_FOUND)
        item.manager_status = 'approved' if action == 'approve' else ('rejected' if action=='reject' else 'edited')
        if action == 'edit' and new_start:
            item.manager_edited_start = parse_datetime(new_start)
        item.save()
        ManagerResponse.objects.create(order_item=item, manager=manager, action=action, payload=payload)
        # after updating, check order aggregation
        order = item.order
        pending = order.items.filter(manager_status='pending').exists()
        if not pending:
            # all managers decided
            rejected_any = order.items.filter(manager_status='rejected').exists()
            if rejected_any:
                order.status = 'rejected'
                order.save()
                # notify customer about rejection
                bale_client.send_message(order.customer.bale_user_id, f"متاسفیم، یکی از کانال‌ها سفارش شما را رد کرد. سفارش #{order.id} رد شد.")
            else:
                order.status = 'waiting_payment'
                order.save()
                # create single payment request to customer
                callback = os.environ.get('WEBHOOK_BASE_URL')
                if callback:
                    callback = callback.rstrip('/') + '/api/webhooks/payment/'
                payment = bale_client.create_payment_request(order.customer.bale_user_id, order.total_amount, callback_url=callback)
                # payment may contain payment_url or id depending on Bale
                if payment.get('payment_url'):
                    bale_client.send_message(order.customer.bale_user_id, f"همه مدیران تایید کردند. لطفاً پرداخت را تکمیل کنید: {payment.get('payment_url')}")
                else:
                    bale_client.send_message(order.customer.bale_user_id, f"همه مدیران تایید کردند. برای پرداخت لطفاً به ربات مراجعه کنید.")
        return Response({'ok': True})

@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhook(APIView):
    def post(self, request):
        payload = request.data
        order_id = payload.get('order_id')
        status = payload.get('status')
        order = get_object_or_404(Order, id=order_id)
        if status == 'paid':
            order.status = 'completed'
            order.save()
            # For each item, schedule or forward banner depending on bot permissions and manager status
            for item in order.items.all():
                # determine final send time
                send_time = item.manager_edited_start if item.manager_edited_start else item.requested_start
                send_iso = send_time.isoformat()
                # if bot is channel admin, schedule to channel; otherwise schedule/forward to manager
                channel_target = item.channel.link or item.channel.id
                if bale_client.bot_is_channel_admin(channel_target):
                    # schedule directly to channel
                    # we need payload to forward - using banner_message_id
                    if item.banner_message_id:
                        resp = bale_client.schedule_message(channel_target, {'forward_message_id': item.banner_message_id}, send_iso)
                        if resp.get('error'):
                            # fallback: forward to manager to post later
                            bale_client.schedule_message(item.manager.bale_user_id, {'forward_message_id': item.banner_message_id}, send_iso)
                        else:
                            item.banner_forwarded = True
                            item.save()
                else:
                    # schedule to manager (they will post or bot will forward if later got admin)
                    if item.manager and item.banner_message_id:
                        bale_client.schedule_message(item.manager.bale_user_id, {'forward_message_id': item.banner_message_id}, send_iso)
                        item.banner_forwarded = True
                        item.save()
            # send confirmation to customer
            bale_client.send_message(order.customer.bale_user_id, f"سفارش شما #{order.id} با موفقیت ثبت و پرداخت شد. تبلیغات در زمان‌های مشخص منتشر خواهد شد.")
        return Response({'ok': True})
