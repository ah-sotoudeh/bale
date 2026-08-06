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

class OrderCreateView(APIView):
    def post(self, request):
        # Note: assumes user is authenticated via Bale and request.user is set
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
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
            from django.utils.dateparse import parse_datetime
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
                # notify customer about rejection (TODO)
            else:
                order.status = 'waiting_payment'
                order.save()
                # create single payment request to customer (TODO: integrate with Bale payment)
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
            # schedule forwarding banners or reminders (TODO)
        return Response({'ok': True})
