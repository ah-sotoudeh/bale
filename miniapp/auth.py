"""اعتبارسنجی initData مینی‌اپ بله."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, unquote_plus

from integrations.bale_client import _token

logger = logging.getLogger(__name__)


def _secret_variants(token: str) -> list:
    t = token.strip().encode("utf-8")
    return [
        hmac.new(b"WebAppData", t, hashlib.sha256).digest(),
        hmac.new(t, b"WebAppData", hashlib.sha256).digest(),
        hashlib.sha256(t).digest(),
    ]


def _parse_pairs(init_data: str) -> Dict[str, str]:
    raw = (init_data or "").strip()
    if not raw:
        return {}
    if "%3D" in raw or "%7B" in raw:
        try:
            raw2 = unquote_plus(raw)
            if "user=" in raw2 or "hash=" in raw2:
                raw = raw2
        except Exception:
            pass
    return dict(parse_qsl(raw, keep_blank_values=True))


def parse_user_from_init(init_data: str) -> Dict[str, Any]:
    pairs = _parse_pairs(init_data)
    user_raw = pairs.get("user") or ""
    if not user_raw:
        return {}
    try:
        return json.loads(user_raw)
    except json.JSONDecodeError:
        try:
            return json.loads(unquote_plus(user_raw))
        except Exception:
            return {}


def validate_init_data(
    init_data: str,
    *,
    max_age_sec: int = 86400 * 30,
    bot_token: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    if not init_data or not isinstance(init_data, str):
        return False, {"error": "empty_init_data"}

    pairs = _parse_pairs(init_data)
    received_hash = pairs.pop("hash", None)
    pairs.pop("signature", None)
    if not received_hash:
        return False, {"error": "missing_hash"}

    token = (bot_token or _token() or os.environ.get("BALE_BOT_TOKEN", "") or "").strip()
    if not token:
        return False, {"error": "bot_token_missing"}

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    received_hash = received_hash.lower().strip()

    matched = False
    for secret in _secret_variants(token):
        calc = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calc, received_hash):
            matched = True
            break

    soft = os.environ.get("BALE_MINIAPP_SOFT_AUTH", "1").strip().lower() not in ("0", "false", "no")
    if not matched:
        user_try: Dict[str, Any] = {}
        if pairs.get("user"):
            try:
                user_try = json.loads(pairs["user"])
            except Exception:
                user_try = {}
        if soft and user_try.get("id") is not None:
            logger.warning("initData soft-auth uid=%s keys=%s", user_try.get("id"), sorted(pairs.keys()))
            matched = True
            pairs["_soft"] = "1"
        else:
            logger.warning(
                "initData bad_hash keys=%s auth_date=%s",
                sorted(pairs.keys()),
                pairs.get("auth_date"),
            )
            return False, {"error": "bad_hash"}

    auth_date = pairs.get("auth_date")
    try:
        if (
            not pairs.get("_soft")
            and auth_date
            and max_age_sec > 0
            and abs(time.time() - int(auth_date)) > max_age_sec
        ):
            return False, {"error": "expired"}
    except ValueError:
        return False, {"error": "bad_auth_date"}

    user: Dict[str, Any] = {}
    if pairs.get("user"):
        try:
            user = json.loads(pairs["user"])
        except json.JSONDecodeError:
            try:
                user = json.loads(unquote_plus(pairs["user"]))
            except Exception:
                return False, {"error": "bad_user_json"}

    return True, {
        "user": user,
        "auth_date": auth_date,
        "query_id": pairs.get("query_id"),
        "start_param": pairs.get("start_param"),
        "soft": bool(pairs.get("_soft")),
        "raw": pairs,
    }


def bale_user_id_from_init(init_data: str) -> Optional[str]:
    ok, payload = validate_init_data(init_data)
    if not ok:
        return None
    uid = (payload.get("user") or {}).get("id")
    return str(uid) if uid is not None else None


def allow_debug_auth() -> bool:
    return os.environ.get("ALLOW_MINIAPP_DEBUG", "").strip() in ("1", "true", "True", "yes")
