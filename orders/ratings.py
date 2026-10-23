"""میانگین و امتیاز وزنی کانال و تعرفه."""
from __future__ import annotations

from django.db.models import Avg, Count, Q

from orders.models import ChannelReview, OrderItem


def tariff_rating_stats(tariff_id: int) -> dict:
    qs = ChannelReview.objects.filter(
        is_hidden=False, order_item__tariff_id=tariff_id,
    )
    agg = qs.aggregate(avg=Avg('rating'), n=Count('id'))
    n = int(agg['n'] or 0)
    avg = float(agg['avg'] or 0) if n else None
    return {
        'avg': round(avg, 2) if avg is not None else None,
        'count': n,
        'label': None if n == 0 else f'{avg:.1f}',
        'weighted': (avg * n) if avg is not None else 0.0,
    }


def channel_rating_stats(channel_id: int) -> dict:
    """میانگین ساده نظرات + امتیاز وزنی برای محبوبیت."""
    qs = ChannelReview.objects.filter(is_hidden=False, channel_id=channel_id)
    agg = qs.aggregate(avg=Avg('rating'), n=Count('id'))
    n = int(agg['n'] or 0)
    avg = float(agg['avg'] or 0) if n else None
    # وزنی: sum(rating)/n == avg؛ برای مقایسه بین کانال‌ها از sum(rating) استفاده می‌کنیم
    # محبوبیت = avg * log-ish count → ساده: avg * n / (n+1) تا تک‌نظر ۵ ستاره کمتر از چند نظر ۴.۸ وزن بگیرد
    popularity = 0.0
    if n and avg is not None:
        popularity = avg * (n / (n + 1.0))
    return {
        'avg': round(avg, 2) if avg is not None else None,
        'count': n,
        'popularity': round(popularity, 4),
        'show_in_list': n > 0,  # فهرست اولیه: بدون نظر نشان نده
    }


def sort_key_popularity(stats: dict) -> tuple:
    """مرتب‌سازی محبوب‌ترین: موارد با نظر اول، بدون نظر آخر."""
    if not stats or not stats.get('count'):
        return (1, 0.0)
    return (0, -float(stats.get('popularity') or 0))
