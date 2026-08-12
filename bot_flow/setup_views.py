"""راه‌اندازی یک‌باره روی هاست بدون ترمینال."""
from __future__ import annotations

import os
from io import StringIO

from django.core.management import call_command
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def _token_ok(request: HttpRequest) -> bool:
    expected = (
        os.environ.get('SETUP_SECRET', '').strip()
        or os.environ.get('WEBHOOK_SECRET', '').strip()
        or os.environ.get('BALE_BOT_TOKEN', '').strip()[:16]
    )
    if not expected:
        return False
    got = (request.GET.get('token') or request.GET.get('key') or '').strip()
    return got == expected or got == os.environ.get('BALE_BOT_TOKEN', '').strip()


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def run_migrate(request: HttpRequest) -> HttpResponse:
    """GET /bot/setup-migrate/?token=... → migrate"""
    if not _token_ok(request):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    out = StringIO()
    err = StringIO()
    try:
        call_command('migrate', interactive=False, verbosity=1, stdout=out, stderr=err)
        return JsonResponse({
            'ok': True,
            'stdout': out.getvalue()[-4000:],
            'stderr': err.getvalue()[-2000:],
        })
    except Exception as e:
        return JsonResponse({
            'ok': False,
            'error': str(e),
            'stdout': out.getvalue()[-2000:],
            'stderr': err.getvalue()[-2000:],
        }, status=500)


@csrf_exempt
@require_http_methods(['GET'])
def env_check(request: HttpRequest) -> HttpResponse:
    """GET /bot/setup-env/?token=... → آیا توکن‌ها از env/.env خوانده می‌شوند"""
    if not _token_ok(request):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    def _mask(v: str) -> str:
        if not v:
            return '(empty)'
        if len(v) <= 8:
            return '***'
        return v[:4] + '…' + v[-4:] + f' (len={len(v)})'

    from django.conf import settings

    return JsonResponse({
        'ok': True,
        'BALE_BOT_TOKEN': _mask(os.environ.get('BALE_BOT_TOKEN', '') or getattr(settings, 'BALE_BOT_TOKEN', '')),
        'BALE_TOKEN': _mask(os.environ.get('BALE_TOKEN', '') or getattr(settings, 'BALE_TOKEN', '')),
        'MINIAPP_BASE_URL': getattr(settings, 'MINIAPP_BASE_URL', '') or os.environ.get('MINIAPP_BASE_URL', ''),
        'ALLOWED_HOSTS': list(getattr(settings, 'ALLOWED_HOSTS', [])),
        'USE_SQLITE': os.environ.get('USE_SQLITE', ''),
        'cwd_has_env_file': os.path.isfile(os.path.join(str(settings.BASE_DIR), '.env')),
    })
