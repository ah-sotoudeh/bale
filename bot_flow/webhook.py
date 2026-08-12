"""دریافت آپدیت‌های بله از طریق webhook (جایگزین polling)."""
from __future__ import annotations

import json
import logging
import os

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _secret_ok(request: HttpRequest) -> bool:
    """اختیاری: ?token= یا هدر X-Bale-Secret برابر WEBHOOK_SECRET."""
    expected = os.environ.get('WEBHOOK_SECRET', '').strip()
    if not expected:
        return True
    got = (
        request.headers.get('X-Bale-Secret')
        or request.GET.get('token')
        or ''
    ).strip()
    return got == expected


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def bale_webhook(request: HttpRequest) -> HttpResponse:
    if request.method == 'GET':
        return HttpResponse('bale webhook ok')

    if not _secret_ok(request):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    try:
        update = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        logger.warning('webhook invalid json')
        return JsonResponse({'ok': False, 'error': 'bad_json'}, status=400)

    if not isinstance(update, dict):
        return JsonResponse({'ok': False, 'error': 'bad_body'}, status=400)

    try:
        # همان منطق poll_bot
        from scripts.poll_bot_logic import handle_update

        handle_update(update)
    except Exception:
        logger.exception('webhook handle_update failed update_id=%s', update.get('update_id'))
        # به بله 200 برمی‌گردانیم تا بی‌وقفه retry نکند؛ خطا در لاگ است

    return JsonResponse({'ok': True})
