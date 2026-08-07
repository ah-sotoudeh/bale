#!/usr/bin/env python3
"""Long-polling listener for Bale Bot (no public domain / webhook needed).

Usage:
    export BALE_BOT_TOKEN="your_token_here"
    python scripts/poll_bot.py

Optional:
    export BALE_API_URL="https://tapi.bale.ai"   # default

What it does:
1. Checks bot identity with getMe
2. Deletes any existing webhook (required for getUpdates)
3. Long-polls getUpdates and handles basic messages
4. Replies to /start and echoes other text (for connectivity test)

Press Ctrl+C to stop.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# Allow importing integrations/ from project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations import bale_client as bc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("poll_bot")


def ensure_token() -> None:
    if not bc.TOKEN:
        log.error("BALE_BOT_TOKEN is not set. Export it and try again.")
        sys.exit(1)
    log.info("Token loaded (length=%d)", len(bc.TOKEN))


def prepare_polling() -> None:
    """Verify bot + remove webhook so getUpdates works."""
    me = bc.get_me()
    if me.get("error") or not me.get("ok", True):
        log.error("getMe failed: %s", me)
        sys.exit(1)

    result = me.get("result") or me
    username = result.get("username") or result.get("first_name") or "?"
    bot_id = result.get("id", "?")
    log.info("Bot OK → id=%s username=@%s", bot_id, username)

    info = bc.get_webhook_info()
    current_url = (info.get("result") or {}).get("url") or info.get("url") or ""
    if current_url:
        log.info("Webhook currently set to: %s — deleting so polling can work...", current_url)
        deleted = bc.delete_webhook()
        log.info("deleteWebhook → %s", deleted)
    else:
        log.info("No webhook set. Ready for polling.")


def handle_update(update: dict) -> None:
    update_id = update.get("update_id")
    log.info("── update_id=%s ──", update_id)
    log.debug("Raw: %s", json.dumps(update, ensure_ascii=False)[:500])

    # Standard message
    msg = update.get("message") or update.get("edited_message")
    if msg:
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        from_user = msg.get("from") or {}
        text = (msg.get("text") or "").strip()
        user_label = from_user.get("username") or from_user.get("first_name") or from_user.get("id")

        log.info("Message from %s (chat_id=%s): %s", user_label, chat_id, text[:120])

        if not chat_id:
            return

        if text.startswith("/start"):
            reply = (
                "سلام 👋\n"
                "ربات تبلیغات بله آماده‌ست.\n"
                f"شناسه شما: {from_user.get('id')}\n\n"
                "فعلاً در حالت تست (polling) هستیم."
            )
            resp = bc.send_message(str(chat_id), reply)
            log.info("Replied to /start → %s", "ok" if not resp.get("error") else resp)
            return

        if text:
            resp = bc.send_message(str(chat_id), f"دریافت شد: {text}")
            log.info("Echo reply → %s", "ok" if not resp.get("error") else resp)
            return

        log.info("Non-text message (photo/sticker/...), ignored for now.")
        return

    # Callback query (inline buttons)
    cq = update.get("callback_query")
    if cq:
        data = cq.get("data")
        from_user = (cq.get("from") or {})
        log.info("Callback from %s: data=%s", from_user.get("id"), data)
        # Acknowledge later when we implement manager approve/reject buttons
        return

    # Payment-related
    if "successful_payment" in (update.get("message") or {}):
        log.info("successful_payment received")
        return

    if update.get("pre_checkout_query"):
        log.info("pre_checkout_query received: %s", update["pre_checkout_query"])
        return

    log.info("Unhandled update keys: %s", list(update.keys()))


def run_polling(timeout: int = 25) -> None:
    offset = None
    log.info("Starting long-polling (timeout=%ss). Send a message to the bot in Bale.", timeout)

    while True:
        try:
            data = bc.get_updates(offset=offset, limit=50, timeout=timeout)

            if data.get("error"):
                log.warning("getUpdates error: %s — retry in 3s", data["error"])
                time.sleep(3)
                continue

            if not data.get("ok", True):
                # Common: webhook still active
                desc = data.get("description") or data
                log.warning("API not ok: %s — retry in 5s", desc)
                time.sleep(5)
                continue

            updates = data.get("result") or []
            for upd in updates:
                handle_update(upd)
                uid = upd.get("update_id")
                if uid is not None:
                    offset = uid + 1

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.exception("Unexpected error: %s — retry in 5s", e)
            time.sleep(5)


def main() -> None:
    ensure_token()
    prepare_polling()
    run_polling()


if __name__ == "__main__":
    main()
