from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import OrderCreateSerializer
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from orders.services import notify_managers_for_order
import logging

logger = logging.getLogger(__name__)


class OrderCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            notify_managers_for_order(order)
            return Response({'order_id': order.id, 'status': order.status})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class ManagerResponseWebhook(APIView):
    def post(self, request):
        return Response({'ok': False, 'error': 'polling_only'}, status=status.HTTP_410_GONE)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhook(APIView):
    def post(self, request):
        return Response({'ok': False, 'error': 'polling_only'}, status=status.HTTP_410_GONE)
