"""وب‌هوک عمداً خاموش است. آپدیت‌ها فقط از scripts/poll_bot.py می‌آیند."""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def bale_webhook(_request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {'ok': False, 'error': 'polling_only', 'message': 'بازو با long polling کار می‌کند.'},
        status=410,
    )
