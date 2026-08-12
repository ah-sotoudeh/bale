from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include


def home(_request):
    return HttpResponse(
        'لینک‌ساز OK — <a href="/miniapp/manager/">پنل مدیر (مینی‌اپ)</a>',
        content_type='text/html; charset=utf-8',
    )


urlpatterns = [
    path('', home, name='home'),
    path('admin/', admin.site.urls),
    path('api/', include('channels_app.urls')),
    path('api/', include('orders.urls')),
    path('miniapp/', include('miniapp.urls')),
]
