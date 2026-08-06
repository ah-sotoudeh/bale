from django.urls import path
from .views import OrderCreateView, ManagerResponseWebhook, PaymentWebhook

urlpatterns = [
    path('orders/', OrderCreateView.as_view(), name='orders-create'),
    path('webhooks/manager-response/', ManagerResponseWebhook.as_view(), name='webhook-manager-response'),
    path('webhooks/payment/', PaymentWebhook.as_view(), name='webhook-payment'),
]
