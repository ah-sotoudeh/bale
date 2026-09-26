"""برداشت آمار کانال با حساب لینک‌یار و ذخیرهٔ تاریخچه.

اعضا از get_full_group و بازدید پست‌ها از get_messages_views (کتابخانهٔ aiobale).
مدیر این عددها را وارد نمی‌کند. هر برداشت یک ChannelStatSnapshot است تا
بعداً نمودار تغییر اعضا و بازدید ساخته شود.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

_FRESH = timedelta(hours=6)


def _to_ms(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    n = int(value)
    if n < 10_000_000_000:
        return n * 1000
    return n


def summarize_reading(members: Optional[int], posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """از فهرست پست‌های خوانده‌شده، بازدید میانگین، نرخ روزانه و استناد را می‌سازد."""
    view_vals = [int(p['views']) for p in posts if isinstance(p.get('views'), int) and int(p['views']) >= 0]
    avg_views = int(sum(view_vals) / len(view_vals)) if view_vals else None
    dates = [d for d in (_to_ms(p.get('date')) for p in posts) if d]
    span_days = 1.0
    if len(dates) >= 2:
        span_days = max((max(dates) - min(dates)) / 86_400_000, 1.0)
    forwards = sum(int(p.get('forwards') or 0) for p in posts)
    posts_per_day = round(len(posts) / span_days, 2) if posts else 0.0
    citation = round(forwards / len(posts), 3) if posts else 0.0
    now_ms = int(timezone.now().timestamp() * 1000)
    day_views = [
        int(p['views'])
        for p in posts
        if isinstance(p.get('views'), int) and _to_ms(p.get('date')) and now_ms - _to_ms(p.get('date')) <= 86_400_000
    ]
    if day_views:
        daily_reach = int(sum(day_views))
    elif avg_views is not None:
        daily_reach = avg_views
    else:
        daily_reach = None
    err = None
    if members and avg_views is not None and members > 0:
        err = round(avg_views / members * 100, 2)
    return {
        'members': members,
        'avg_views': avg_views,
        'daily_reach': daily_reach,
        'posts': len(posts),
        'forwards': forwards,
        'posts_per_day': posts_per_day,
        'citation_index': citation,
        'err_percent': err,
    }


def _guess_lang(text: str) -> str:
    if re.search(r'[\u0600-\u06FF]', text or ''):
        return 'fa'
    if re.search(r'[A-Za-z]', text or ''):
        return 'en'
    return ''


def refresh_channel(channel) -> Dict[str, Any]:
    from integrations import linkyar_client as ly

    ref = (channel.link or '').strip()
    if not ref:
        channel.stats_error = 'link missing'
        channel.save(update_fields=['stats_error'])
        return {'ok': False, 'error': 'link missing'}

    reading = ly.collect_channel_stats(ref)
    if not reading.get('ok'):
        channel.stats_error = str(reading.get('error') or 'collect_failed')[:255]
        channel.save(update_fields=['stats_error'])
        return reading

    summary = summarize_reading(reading.get('members'), reading.get('posts') or [])
    members = summary['members'] if summary['members'] is not None else channel.members_count
    avg_views = summary['avg_views'] if summary['avg_views'] is not None else channel.avg_views
    daily = summary['daily_reach'] if summary['daily_reach'] is not None else channel.daily_reach
    if not members and avg_views is None:
        channel.stats_error = str(reading.get('views_error') or reading.get('group_error') or 'empty')[:255]
        channel.save(update_fields=['stats_error'])
        return {'ok': False, 'error': channel.stats_error}

    from channels_app.models import ChannelStatSnapshot

    now = timezone.now()
    if reading.get('peer_id'):
        channel.bale_peer_id = int(reading['peer_id'])
    about = (reading.get('about') or '').strip()
    if about:
        channel.about = about[:4000]
        if not channel.description:
            channel.description = channel.about
    title = (reading.get('title') or '').strip()
    if title and (not channel.name or channel.name == '(no title)'):
        channel.name = title[:200]
    lang_src = f"{about} {title}"
    channel.language = _guess_lang(lang_src)
    channel.members_count = int(members or 0)
    channel.avg_views = int(avg_views or 0)
    channel.daily_reach = int(daily or 0)
    channel.posts_per_day = Decimal(str(summary['posts_per_day']))
    channel.citation_index = Decimal(str(summary['citation_index']))
    err = summary['err_percent']
    if err is None and channel.members_count and channel.avg_views:
        err = round(channel.avg_views / channel.members_count * 100, 2)
    channel.err_percent = Decimal(str(err or 0))
    channel.stats_updated_at = now
    channel.stats_error = ''
    channel.save()
    ChannelStatSnapshot.objects.create(
        channel=channel,
        taken_at=now,
        members=channel.members_count,
        avg_views=channel.avg_views,
        daily_reach=channel.daily_reach,
        posts=int(summary['posts'] or 0),
        forwards=int(summary['forwards'] or 0),
        source='linkyar',
    )
    return {'ok': True, 'channel_id': channel.id, 'members': channel.members_count, 'avg_views': channel.avg_views}


def refresh_due_channels(max_age: timedelta = _FRESH) -> Dict[str, int]:
    from channels_app.models import Channel

    cutoff = timezone.now() - max_age
    due = Channel.objects.exclude(link='').filter(
        models_q_due(cutoff),
    )
    done = 0
    failed = 0
    for channel in due.iterator():
        try:
            result = refresh_channel(channel)
        except Exception:
            logger.exception('channel stats failed id=%s', channel.id)
            failed += 1
            continue
        if result.get('ok'):
            done += 1
        else:
            failed += 1
    return {'done': done, 'failed': failed}


def models_q_due(cutoff):
    from django.db.models import Q

    return Q(stats_updated_at__isnull=True) | Q(stats_updated_at__lt=cutoff)
