"""لاگ درخواست‌های مینی‌اپ API برای دیباگ (مسیر اصلی auth را تغییر نمی‌دهد)."""
from __future__ import annotations

import logging
import time

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger('miniapp.api_access')


class MiniappApiAccessLogMiddleware(MiddlewareMixin):
    """برای هر /miniapp/api/* یک خط لاگ می‌نویسد."""

    def process_request(self, request):
        path = request.path or ''
        if '/miniapp/api' not in path:
            return None
        request._lb_api_t0 = time.monotonic()
        return None

    def process_response(self, request, response):
        path = request.path or ''
        if '/miniapp/api' not in path:
            return response
        try:
            dt = 0.0
            if hasattr(request, '_lb_api_t0'):
                dt = (time.monotonic() - request._lb_api_t0) * 1000
            uid = (
                request.headers.get('X-Bale-User-Id')
                or request.META.get('HTTP_X_BALE_USER_ID')
                or ''
            )
            status = getattr(response, 'status_code', 0)
            # سعی کن error را از JSON بخوانی بدون خراب کردن body
            err = ''
            try:
                if hasattr(response, 'content') and response.get('Content-Type', '').startswith('application/json'):
                    import json
                    data = json.loads(response.content.decode('utf-8') or '{}')
                    if isinstance(data, dict) and data.get('ok') is False:
                        err = str(data.get('error') or data.get('message') or '')[:120]
            except Exception:
                err = ''
            logger.info(
                'api %s %s status=%s ms=%.0f uid=%s err=%s',
                request.method,
                path,
                status,
                dt,
                str(uid)[:32],
                err or '-',
            )
        except Exception:
            logger.exception('api_access_log')
        return response
