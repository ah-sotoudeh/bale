"""حالت دمو مینی‌اپ بدون بله — سه نقش با دادهٔ نمونه."""
from __future__ import annotations

import os
from typing import Optional

from django.contrib.auth import get_user_model

User = get_user_model()

DEMO_USERS = {
    "manager": {"bale_id": "demo_manager_1", "username": "demo_manager", "name": "مدیر دمو"},
    "customer": {"bale_id": "demo_customer_1", "username": "demo_customer", "name": "مشتری دمو"},
    "operator": {"bale_id": "demo_operator_1", "username": "demo_operator", "name": "پشتیبان دمو"},
}

ORDER_PIPELINE = [
    ("waiting_banner", "بنر"),
    ("waiting_managers", "تأیید مدیر"),
    ("waiting_customer_confirm", "تأیید شما"),
    ("waiting_payment", "پرداخت"),
    ("paid", "انتشار"),
    ("completed", "پایان"),
]


def demo_enabled() -> bool:
    """دمو فقط با env صریح — در پروداکشن خاموش بماند مگر DEBUG."""
    return os.environ.get("DEMO_MINIAPP", "").strip().lower() in ("1", "true", "yes") or os.environ.get(
        "ALLOW_MINIAPP_DEBUG", ""
    ).strip().lower() in ("1", "true", "yes")


def normalize_role(role: str) -> str:
    r = (role or "customer").strip().lower()
    if r in ("manager", "owner", "channel"):
        return "manager"
    if r in ("operator", "support", "admin"):
        return "operator"
    return "customer"


def get_or_create_demo_user(role: str):
    role = normalize_role(role)
    meta = DEMO_USERS[role]
    user, _ = User.objects.get_or_create(
        bale_user_id=meta["bale_id"],
        defaults={"username": meta["username"][:30]},
    )
    if not user.bale_username:
        try:
            user.bale_username = meta["username"]
            user.save(update_fields=["bale_username"])
        except Exception:
            pass
    return user, role


def ensure_demo_seed(manager) -> None:
    """دادهٔ نمونه برای مدیر دمو — فقط اگر هنوز کانالی ندارد."""
    from channels_app.models import Channel, ChannelGroup, Tariff

    if Channel.objects.filter(manager=manager).exists():
        return
    ch1 = Channel.objects.create(
        manager=manager,
        name="کانال نمونه یک",
        link="@demo_channel_1",
        members_count=12500,
        publish_mode="bot",
        is_listed=True,
        ownership_verified=True,
    )
    ch2 = Channel.objects.create(
        manager=manager,
        name="کانال نمونه دو",
        link="@demo_channel_2",
        members_count=43000,
        publish_mode="linkyar",
        is_listed=True,
        ownership_verified=True,
    )
    ch3 = Channel.objects.create(
        manager=manager,
        name="کانال نمونه سه",
        link="@demo_channel_3",
        members_count=8200,
        publish_mode="manual",
        is_listed=True,
        ownership_verified=True,
    )
    for ch, plans in (
        (ch1, [(12, 50000), (24, 90000)]),
        (ch2, [(24, 150000), (48, 280000)]),
        (ch3, [(24, 40000)]),
    ):
        for hours, price in plans:
            Tariff.objects.create(
                channel=ch,
                name=f"طرح {hours} ساعته",
                duration_hours=hours,
                price=price,
                start_hour=12,
                is_active=True,
            )
    g = ChannelGroup.objects.create(name="مجموعه نمونه", manager=manager, avatar_channel_id=ch2.id)
    g.channels.set([ch1, ch2])
    Tariff.objects.create(
        group=g,
        name="طرح مشترک ۲۴س",
        duration_hours=24,
        price=200000,
        start_hour=18,
        is_active=True,
    )


def pipeline_for_status(status: str) -> dict:
    keys = [k for k, _ in ORDER_PIPELINE]
    labels = [lab for _, lab in ORDER_PIPELINE]
    try:
        idx = keys.index(status)
    except ValueError:
        if status in ("rejected", "cancelled"):
            return {"steps": labels, "current": -1, "status": status, "terminal": status}
        idx = 0
    return {"steps": labels, "current": idx, "status": status, "terminal": None}
