from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import OrderCreateSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from orders.services import (
    notify_managers_for_order,
    process_manager_response,
    process_payment_paid,
)
import logging

logger = logging.getLogger(__name__)


class OrderCreateView(APIView):
    def post(self, request):
        # Note: assumes user is authenticated via Bale and request.user is set
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            notify_managers_for_order(order)
            return Response({'order_id': order.id, 'status': order.status})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ManagerResponseWebhook(APIView):
    def post(self, request):
        payload = request.data
        result = process_manager_response(
            order_item_id=payload.get('order_item_id'),
            manager_bale_id=str(payload.get('manager_bale_id') or ''),
            action=payload.get('action') or '',
            new_start=payload.get('new_start'),
            extra_payload=dict(payload),
        )
        if not result.get('ok'):
            code = status.HTTP_404_NOT_FOUND if result.get('error') in (
                'item_not_found', 'manager_not_found'
            ) else status.HTTP_400_BAD_REQUEST
            return Response(result, status=code)
        return Response(result)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhook(APIView):
    def post(self, request):
        payload = request.data
        order_id = payload.get('order_id')
        pay_status = payload.get('status')
        if pay_status != 'paid':
            return Response({'ok': True, 'ignored': True, 'status': pay_status})
        result = process_payment_paid(int(order_id))
        if not result.get('ok'):
            return Response(result, status=status.HTTP_404_NOT_FOUND)
        return Response(result)
