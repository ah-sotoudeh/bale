from pathlib import Path

from django.http import HttpRequest, HttpResponse


def _html(name: str) -> HttpResponse:
    path = Path(__file__).resolve().parent / 'static' / name / 'index.html'
    if not path.exists():
        path = Path(__file__).resolve().parent / 'static' / 'app' / 'index.html'
    html = path.read_text(encoding='utf-8')
    resp = HttpResponse(html, content_type='text/html; charset=utf-8')
    resp['Content-Security-Policy'] = "frame-ancestors https://*.bale.ai https://web.bale.ai 'self'"
    if 'X-Frame-Options' in resp:
        del resp['X-Frame-Options']
    return resp


def manager_app(request: HttpRequest) -> HttpResponse:
    return _html('app')


def mini_app(request: HttpRequest) -> HttpResponse:
    return _html('app')
