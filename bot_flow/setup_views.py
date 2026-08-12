"""راه‌اندازی یک‌باره روی هاست بدون ترمینال."""
from __future__ import annotations

import os
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# کلید موقت؛ بعد از migrate می‌توانید SETUP_SECRET را عوض کنید یا این view را حذف کنید
DEFAULT_SETUP_KEY = 'linkbank-setup-once'


def _load_dotenv_files() -> None:
    base = Path(getattr(settings, 'BASE_DIR', Path.cwd()))
    for rel in ('.env', 'config/.env'):
        path = base / rel
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        except OSError:
            pass


def _token_ok(request: HttpRequest) -> bool:
    _load_dotenv_files()
    got = (request.GET.get('token') or request.GET.get('key') or '').strip()
    if not got:
        return False

    candidates = [
        os.environ.get('SETUP_SECRET', '').strip(),
        os.environ.get('WEBHOOK_SECRET', '').strip(),
        os.environ.get('BALE_BOT_TOKEN', '').strip(),
        (os.environ.get('BALE_BOT_TOKEN') or '').strip()[:16],
        getattr(settings, 'BALE_BOT_TOKEN', '') or '',
        DEFAULT_SETUP_KEY,
    ]
    return got in {c for c in candidates if c}


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def run_migrate(request: HttpRequest) -> HttpResponse:
    if not _token_ok(request):
        return JsonResponse({
            'ok': False,
            'error': 'forbidden',
            'hint': f'use ?token={DEFAULT_SETUP_KEY} or full BALE_BOT_TOKEN from .env',
        }, status=403)

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
    if not _token_ok(request):
        return JsonResponse({
            'ok': False,
            'error': 'forbidden',
            'hint': f'use ?token={DEFAULT_SETUP_KEY}',
        }, status=403)

    _load_dotenv_files()

    def _mask(v: str) -> str:
        if not v:
            return '(empty)'
        if len(v) <= 8:
            return '***'
        return v[:4] + '…' + v[-4:] + f' (len={len(v)})'

    bot = os.environ.get('BALE_BOT_TOKEN', '') or getattr(settings, 'BALE_BOT_TOKEN', '')
    return JsonResponse({
        'ok': True,
        'BALE_BOT_TOKEN': _mask(bot),
        'BALE_TOKEN': _mask(os.environ.get('BALE_TOKEN', '') or getattr(settings, 'BALE_TOKEN', '')),
        'MINIAPP_BASE_URL': getattr(settings, 'MINIAPP_BASE_URL', '') or os.environ.get('MINIAPP_BASE_URL', ''),
        'ALLOWED_HOSTS': list(getattr(settings, 'ALLOWED_HOSTS', [])),
        'USE_SQLITE': os.environ.get('USE_SQLITE', ''),
        'cwd_has_env_file': (Path(settings.BASE_DIR) / '.env').is_file(),
        'base_dir': str(settings.BASE_DIR),
    })
