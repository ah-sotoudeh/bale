from django.urls import path

from miniapp import api, api_extra, api_shop
from miniapp.views import manager_app, mini_app

urlpatterns = [
    path('', mini_app, name='miniapp_home'),
    path('manager/', manager_app, name='miniapp_manager'),
    path('api/me', api.api_me),
    path('api/channels', api.api_channels),
    path('api/publish-mode', api_shop.api_set_publish_mode),
    path('api/tariffs', api.api_tariffs),
    path('api/tariffs/add', api.api_add_tariff),
    path('api/tariffs/update', api_shop.api_tariff_update),
    path('api/catalog', api_extra.api_catalog),
    path('api/orders', api.api_orders),
    path('api/orders/approve', api_extra.api_order_approve),
    path('api/orders/reject', api_extra.api_order_reject),
    path('api/free-days', api.api_free_days),
    path('api/calendar', api_shop.api_calendar),
    path('api/busy', api.api_mark_busy),
    path('api/busy-day', api_shop.api_busy_day),
    path('api/clear-busy', api_shop.api_clear_busy),
    path('api/wallet', api.api_wallet),
    path('api/bank', api.api_add_bank),
    path('api/payout', api.api_request_payout),
    path('api/banners', api_shop.api_banners),
    path('api/banners/rename', api_shop.api_banner_rename),
    path('api/cart', api_shop.api_cart),
    path('api/cart/add', api_shop.api_cart_add),
    path('api/cart/remove', api_shop.api_cart_remove),
    path('api/cart/banner', api_shop.api_cart_banner),
    path('api/checkout', api_shop.api_checkout),
    path('api/my-orders', api_shop.api_my_orders),
    path('api/operator/payouts', api_extra.api_operator_payouts),
    path('api/operator/mark-paid', api_shop.api_operator_paid),
    path('api/operator/banners', api_shop.api_operator_banners),
    path('api/operator/banner-decide', api_shop.api_operator_banner_decide),
]
