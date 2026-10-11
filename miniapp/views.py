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
def demos_hub(_request: HttpRequest) -> HttpResponse:
    """دموی UI پروژه‌های متن‌باز (بدون بک‌اند)."""
    html = (PANEL / 'demos' / 'index.html').read_text(encoding='utf-8')
    return _framed(HttpResponse(html, content_type='text/html; charset=utf-8'))


@xframe_options_exempt
def demo_page(_request: HttpRequest, name: str) -> HttpResponse:
    allowed = {'baboon', 'marketplace', 'nova-store', 'linkban-pro'}
    if name not in allowed:
        raise Http404
    html = (PANEL / 'demos' / name / 'index.html').read_text(encoding='utf-8')
    return _framed(HttpResponse(html, content_type='text/html; charset=utf-8'))


@xframe_options_exempt
def demo_asset(_request: HttpRequest, name: str, path: str) -> HttpResponse:
    """فایل‌های استاتیک دموهای چندصفحه‌ای (مثل Nova Store)."""
    allowed = {'nova-store', 'baboon', 'marketplace'}
    if name not in allowed:
        raise Http404
    root = (PANEL / 'demos' / name).resolve()
    file = (root / path).resolve()
    if root not in file.parents and file != root:
        raise Http404
    if not file.is_file():
        raise Http404
    content_type = guess_type(file.name)[0] or 'application/octet-stream'
    if file.suffix == '.js':
        content_type = 'text/javascript; charset=utf-8'
    elif file.suffix == '.css':
        content_type = 'text/css; charset=utf-8'
    elif file.suffix == '.html':
        content_type = 'text/html; charset=utf-8'
        resp = _framed(HttpResponse(file.read_text(encoding='utf-8'), content_type=content_type))
        return resp
    resp = FileResponse(file.open('rb'), content_type=content_type)
    resp['Cache-Control'] = 'no-cache'
    return _framed(resp)


@xframe_options_exempt
def mini_app(request: HttpRequest) -> HttpResponse:
    # پیش‌فرض: مینی‌اپ مشتری v2 (بازار، بنر متن/تصویر، تقویم، سفارش، کیف‌پول) — متصل به API
    # ?legacy=1 → پنل قدیمی | ?demo=hub → هاب دمو | ?demo=linkban-pro → دموی طراحی
    demo = (request.GET.get('demo') or '').strip()
    if request.GET.get('legacy') == '1' or request.GET.get('app') == '1':
        html = (PANEL / 'index.html').read_text(encoding='utf-8')
    elif demo == 'hub':
        html = (PANEL / 'demos' / 'index.html').read_text(encoding='utf-8')
    elif demo in ('linkban-pro', 'baboon', 'marketplace', 'nova-store'):
        path = PANEL / 'demos' / demo / 'index.html'
        if not path.is_file():
            raise Http404
        html = path.read_text(encoding='utf-8')
    else:
        html = (PANEL / 'v2' / 'index.html').read_text(encoding='utf-8')
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
