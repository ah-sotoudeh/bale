"""بررسی ماندن بنر در کانال بعد از ارسال (الگوی Baboon post checker)."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def verify_bot_message_exists(chat_id: str, message_id: str) -> Tuple[bool, str]:
    """با Bot API؛ اگر پیام نباشد False برمی‌گردد."""
    try:
        from integrations.bale_client import bot_request
        # Bale/Telegram: copyMessage یا forward به خودی برای تست وجود - ساده‌تر getChat
        # بسیاری از APIها getMessage ندارند؛ از forward به کانال storage استفاده می‌کنیم
        r = bot_request("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": chat_id,
            "message_id": int(message_id),
        })
        if r and r.get("ok"):
            # حذف کپی تستی اگر ممکن بود
            try:
                mid = (r.get("result") or {}).get("message_id")
                if mid:
                    bot_request("deleteMessage", {"chat_id": chat_id, "message_id": mid})
            except Exception:
                pass
            return True, "ok"
        return False, str((r or {}).get("description") or "not_found")
    except Exception as e:
        logger.warning("verify_bot_message_exists failed: %s", e)
        return False, str(e)


def flag_item_if_missing(order_item_id: int) -> Optional[str]:
    """اگر پیام انتشار رفته و دیگر نیست، execution_status را published_missing کن."""
    from orders.models import OrderItem

    it = OrderItem.objects.filter(id=order_item_id).first()
    if not it:
        return "not_found"
    if it.execution_status not in ("published", "sent", "done"):
        return "skip_status"
    chat = getattr(it, "published_chat_id", None) or (it.channel.link if it.channel_id else "")
    mid = getattr(it, "published_message_id", None) or ""
    if not chat or not mid:
        return "no_ref"
    ok, reason = verify_bot_message_exists(str(chat), str(mid))
    if ok:
        return "still_there"
    # فقط لاگ — فیلد اختیاری
    logger.warning("post missing item=%s reason=%s", order_item_id, reason)
    try:
        if hasattr(it, "execution_status"):
            it.execution_status = "awaiting_operator"
            it.save(update_fields=["execution_status"])
    except Exception:
        pass
    return "missing:" + reason
