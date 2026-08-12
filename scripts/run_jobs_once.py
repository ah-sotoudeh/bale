#!/usr/bin/env python3
"""جاب‌های زمان‌بندی — برای Cron سی‌پنل هر ۱ دقیقه."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')

import django

django.setup()

from django.utils import timezone  # noqa: E402

from orders.cart import expire_timed_out_items  # noqa: E402
from orders.execution import escalate_unconfirmed, send_publish_reminders  # noqa: E402
from orders.publish import (  # noqa: E402
    daily_admin_audit,
    delete_expired_posts,
    publish_due_items,
)
from integrations import linkyar_client as ly  # noqa: E402


def main() -> None:
    print('expire', expire_timed_out_items())
    print('remind', send_publish_reminders())
    print('publish', publish_due_items())
    if ly.user_token():
        print('delete', delete_expired_posts())
    print('escalate', escalate_unconfirmed())
    # audit once per calendar day is handled inside if you call often — keep simple:
    print('audit', daily_admin_audit())
    print('done', timezone.now().isoformat())


if __name__ == '__main__':
    main()
