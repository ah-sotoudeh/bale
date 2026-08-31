from django.urls import path

from miniapp import api, api_extra
from miniapp.views import manager_app, mini_app

urlpatterns = [
    path('', mini_app, name='miniapp_home'),
    path('manager/', manager_app, name='miniapp_manager'),
    path('api/me', api.api_me),
    path('api/channels', api.api_channels),
    path('api/publish-mode', api.api_set_publish_mode),
    path('api/tariffs', api.api_tariffs),
    path('api/tariffs/add', api.api_add_tariff),
    path('api/catalog', api_extra.api_catalog),
    path('api/orders', api.api_orders),
    path('api/orders/approve', api_extra.api_order_approve),
    path('api/orders/reject', api_extra.api_order_reject),
    path('api/free-days', api.api_free_days),
    path('api/busy', api.api_mark_busy),
    path('api/wallet', api.api_wallet),
    path('api/bank', api.api_add_bank),
    path('api/payout', api.api_request_payout),
    path('api/operator/payouts', api_extra.api_operator_payouts),
    path('api/operator/mark-paid', api_extra.api_operator_mark_paid),
]
