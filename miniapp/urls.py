from django.urls import path

from miniapp import api
from miniapp.views import manager_app

urlpatterns = [
    path('manager/', manager_app, name='miniapp_manager'),
    path('api/me', api.api_me),
    path('api/channels', api.api_channels),
    path('api/publish-mode', api.api_set_publish_mode),
    path('api/tariffs', api.api_tariffs),
    path('api/tariffs/add', api.api_add_tariff),
    path('api/orders', api.api_orders),
    path('api/free-days', api.api_free_days),
    path('api/busy', api.api_mark_busy),
    path('api/wallet', api.api_wallet),
    path('api/bank', api.api_add_bank),
    path('api/payout', api.api_request_payout),
]
