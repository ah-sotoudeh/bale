"""Ensure miniapp API always returns JSON on uncaught errors."""
from __future__ import annotations

import logging

from django.http import JsonResponse

logger = logging.getLogger(__name__)


class MiniappJsonErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        path = request.path or ""
        if "/miniapp/api" not in path and not path.startswith("/api/"):
            return None
        logger.exception("miniapp api uncaught: %s", path)
        return JsonResponse(
            {
                "ok": False,
                "error": "server",
                "message": "خطای سرور: " + type(exception).__name__,
            },
            status=200,
        )
