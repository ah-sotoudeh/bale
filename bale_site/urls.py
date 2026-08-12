from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

from bot_flow.setup_views import env_check, run_migrate
from bot_flow.webhook import bale_webhook


def home(_request):
    return HttpResponse(
        'لینک‌ساز OK — <a href="/miniapp/manager/">پنل مدیر (مینی‌اپ)</a>',
        content_type='text/html; charset=utf-8',
    )


urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('bot/webhook/', bale_webhook, name='bale_webhook'),
    path('bot/setup-migrate/', run_migrate, name='setup_migrate'),
    path('bot/setup-env/', env_check, name='setup_env'),
    path('api/', include('channels_app.urls')),
    path('api/', include('orders.urls')),
    path('miniapp/', include('miniapp.urls')),
]
