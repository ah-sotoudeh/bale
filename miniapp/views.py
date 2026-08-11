from pathlib import Path

from django.http import HttpRequest, HttpResponse


def manager_app(request: HttpRequest) -> HttpResponse:
    path = Path(__file__).resolve().parent / 'static' / 'manager' / 'index.html'
    html = path.read_text(encoding='utf-8')
    resp = HttpResponse(html, content_type='text/html; charset=utf-8')
    # allow embed in Bale web iframe
    resp['Content-Security-Policy'] = "frame-ancestors https://*.bale.ai https://web.bale.ai 'self'"
    if 'X-Frame-Options' in resp:
        del resp['X-Frame-Options']
    return resp
