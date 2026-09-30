from mimetypes import guess_type
from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt

PANEL = Path(__file__).resolve().parent / 'static' / 'panel'
MEDIA = Path(__file__).resolve().parent / 'static' / 'media'


def _framed(resp: HttpResponse) -> HttpResponse:
    resp['Content-Security-Policy'] = (
        "frame-ancestors https://*.bale.ai https://web.bale.ai https://ble.ir 'self'"
    )
    resp['Cache-Control'] = 'no-cache'
    resp.xframe_options_exempt = True
    if 'X-Frame-Options' in resp:
        del resp['X-Frame-Options']
    return resp


def _safe(root: Path, name: str) -> Path:
    base = root.resolve()
    file = (base / name).resolve()
    if base not in file.parents or not file.is_file():
        raise Http404
    return file


@xframe_options_exempt
def mini_app(_request: HttpRequest) -> HttpResponse:
    html = (PANEL / 'index.html').read_text(encoding='utf-8')
    resp = HttpResponse(html, content_type='text/html; charset=utf-8')
    return _framed(resp)


@xframe_options_exempt
def manager_app(request: HttpRequest) -> HttpResponse:
    return mini_app(request)


@xframe_options_exempt
def rules_page(_request: HttpRequest) -> HttpResponse:
    html = (PANEL / 'rules.html').read_text(encoding='utf-8')
    return _framed(HttpResponse(html, content_type='text/html; charset=utf-8'))


def panel_asset(_request: HttpRequest, name: str) -> FileResponse:
    file = _safe(PANEL / 'assets', name)
    content_type = guess_type(file.name)[0] or 'application/octet-stream'
    if file.suffix == '.js':
        content_type = 'text/javascript; charset=utf-8'
    elif file.suffix == '.css':
        content_type = 'text/css; charset=utf-8'
    resp = FileResponse(file.open('rb'), content_type=content_type)
    resp['Cache-Control'] = 'no-cache'
    return resp


def media_file(_request: HttpRequest, name: str) -> FileResponse:
    file = _safe(MEDIA, name)
    content_type = guess_type(file.name)[0] or 'application/octet-stream'
    return FileResponse(file.open('rb'), content_type=content_type)
