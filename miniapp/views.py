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
    # پیش‌فرض: پنل اصلی (React/legacy) که داخل قاب بله تست شده.
    # ?v2=1 → مینی‌اپ جدید SPA | ?demo=hub → هاب دمو | ?demo=linkban-pro → دموی طراحی
    demo = (request.GET.get('demo') or '').strip()
    use_v2 = request.GET.get('v2') == '1' or request.GET.get('app') == 'v2'
    if use_v2:
        html = (PANEL / 'v2' / 'index.html').read_text(encoding='utf-8')
    elif demo == 'hub':
        html = (PANEL / 'demos' / 'index.html').read_text(encoding='utf-8')
    elif demo in ('linkban-pro', 'baboon', 'marketplace', 'nova-store'):
        path = PANEL / 'demos' / demo / 'index.html'
        if not path.is_file():
            raise Http404
        html = path.read_text(encoding='utf-8')
    else:
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



@xframe_options_exempt
def ui_debug(request: HttpRequest) -> HttpResponse:
    """مسیر جدا برای دیباگ UI در /miniapp/ui-debug/

    لاگین و /miniapp/ اصلی را تغییر نمی‌دهد.
    پیش‌فرض: دموی فرانت بدون API.
    اگر MINIAPP_UI_OPEN_DEBUG=1 و DEBUG_BALE_ID و ALLOW_MINIAPP_DEBUG=1:
    فقط این صفحه با debug_bale_id به API واقعی وصل می‌شود.
    """
    import os

    html = (PANEL / 'index.html').read_text(encoding='utf-8')
    open_debug = os.environ.get('MINIAPP_UI_OPEN_DEBUG', '').strip().lower() in (
        '1', 'true', 'yes',
    )
    debug_id = (
        os.environ.get('DEBUG_BALE_ID')
        or os.environ.get('OPERATOR_BALE_ID')
        or ''
    ).strip()

    if open_debug and debug_id:
        inject = (
            '<script>(function(){window.__LB_UI_DEBUG=1;'
            + ('window.__LB_DEBUG_BALE_ID=%r;' % debug_id)
            + 'try{var u=new URL(location.href);'
            + 'u.searchParams.set("debug_bale_id",window.__LB_DEBUG_BALE_ID);'
            + 'if(!location.search.includes("debug_bale_id"))'
            + 'history.replaceState(null,"",u);}catch(e){}'
            + 'console.info("[lb ui-debug] live API + debug_bale_id");'
            + '})();</script>'
        )
    else:
        html = html.replace(
            'window.__LIVE_API = "/miniapp/api";',
            'window.__LIVE_API = ""; /* ui-debug demo */',
            1,
        )
        inject = (
            '<script>(function(){window.__LB_UI_DEBUG=1;'
            'try{window.__LB_DEMO_ROLE=localStorage.getItem("lb_role")||"customer"}catch(e){}'
            'console.info("[lb ui-debug] demo mode — main /miniapp/ auth unchanged");'
            '})();</script>'
        )

    if '<head>' in html:
        html = html.replace('<head>', '<head>\n' + inject, 1)
    else:
        html = inject + html

    resp = HttpResponse(html, content_type='text/html; charset=utf-8')
    return _framed(resp)


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
