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


_HOUR_MS = 3_600_000
_DAY_MS = 86_400_000


def summarize_reading(members: Optional[int], posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """بازدید میانگین، جمع بازدید ۲۴ ساعت، و نرخ پست را از خواندن لینک‌یار می‌سازد.

    پست تازه‌تر از یک ساعت در میانگین نمی‌آید، چون بازدیدش هنوز جمع نشده.
    اگر پست تاریخ‌دار هست ولی هیچ‌کدام مال امروز نیست، بازدید روز صفر است.
    """
    now_ms = int(timezone.now().timestamp() * 1000)
    real = [p for p in posts if p.get('message_id')]
    base = real or list(posts)
    scored = []
    for post in base:
        if not isinstance(post.get('views'), int) or int(post['views']) < 0:
            continue
        stamp = _to_ms(post.get('date'))
        age = now_ms - stamp if stamp else None
        scored.append((int(post['views']), age, post))
    mature = [views for views, age, _post in scored if age is None or age >= _HOUR_MS]
    view_vals = mature or [views for views, _age, _post in scored]
    avg_views = int(sum(view_vals) / len(view_vals)) if view_vals else None
    dates = [d for d in (_to_ms(p.get('date')) for p in base) if d]
    span_days = 1.0
    if len(dates) >= 2:
        span_days = max((max(dates) - min(dates)) / _DAY_MS, 1.0)
    forwards = sum(int(p.get('forwards') or 0) for p in base)
    posts_per_day = round(len(base) / span_days, 2) if base else 0.0
    citation = round(forwards / len(base), 3) if base else 0.0
    day_views = [views for views, age, _post in scored if age is not None and 0 <= age <= _DAY_MS]
    dated = any(age is not None for _views, age, _post in scored)
    if day_views:
        daily_reach = int(sum(day_views))
    elif dated:
        daily_reach = 0
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
        'posts': len(base),
        'forwards': forwards,
        'posts_per_day': posts_per_day,
        'citation_index': citation,
        'err_percent': err,
    }


def public_stats_error(raw: str) -> str:
    text = (raw or '').strip()
    known = {
        'link missing': 'پیوند کانال ثبت نشده.',
        'BALE_TOKEN missing': 'حساب دستیار لینک‌بان روی سرور تنظیم نشده.',
        'empty': 'از این کانال عددی خوانده نشد.',
        'channel_not_found': 'این کانال در بله پیدا نشد.',
        'resolve_failed': 'این کانال در بله پیدا نشد.',
        'no_stats': 'از این کانال عددی خوانده نشد.',
    }
    if text in known:
        return known[text]
    if text.startswith('token_inject'):
        return 'ورود حساب دستیار لینک‌بان ناموفق بود.'
    return 'خواندن آمار این کانال ممکن نشد.'


def _guess_lang(text: str) -> str:
    if re.search(r'[\u0600-\u06FF]', text or ''):
        return 'fa'
    if re.search(r'[A-Za-z]', text or ''):
        return 'en'
    return ''


def _remember_linkyar_admin(channel, reading: Dict[str, Any]) -> None:
    flag = reading.get('linkyar_is_admin')
    if flag is True or flag is False:
        channel.linkyar_is_admin = bool(flag)
        channel.linkyar_checked_at = timezone.now()


def _check_bot_admin_if_configured(channel) -> None:
    """پرچم لینک‌ساز فقط وقتی توکن بازو هست نوشته می‌شود. نبودن توکن یعنی «بررسی نشده»."""
    try:
        from integrations.bale_client import _token

        token = _token()
    except Exception:
        return
    if not token or token == 'your_bot_token_here':
        return
    try:
        from orders.publish import check_bot_admin

        check_bot_admin(channel)
    except Exception:
        logger.exception('bot admin during stats')


def refresh_channel(channel) -> Dict[str, Any]:
    from integrations import linkyar_client as ly

    ref = (channel.link or '').strip()
    if not ref:
        channel.stats_error = 'link missing'
        channel.stats_updated_at = timezone.now()
        channel.save(update_fields=['stats_error', 'stats_updated_at'])
        return {'ok': False, 'error': 'link missing'}

    reading = ly.collect_channel_stats(ref)
    if not reading.get('ok'):
        channel.stats_error = str(reading.get('error') or 'collect_failed')[:255]
        channel.stats_updated_at = timezone.now()
        _remember_linkyar_admin(channel, reading)
        channel.save(update_fields=['stats_error', 'stats_updated_at', 'linkyar_is_admin', 'linkyar_checked_at'])
        return reading

    summary = summarize_reading(reading.get('members'), reading.get('posts') or [])
    members = summary['members'] if summary['members'] is not None else channel.members_count
    views_failed = bool(reading.get('views_error')) and summary['avg_views'] is None
    if views_failed:
        avg_views = channel.avg_views
        daily = channel.daily_reach
    else:
        avg_views = summary['avg_views'] if summary['avg_views'] is not None else channel.avg_views
        daily = summary['daily_reach'] if summary['daily_reach'] is not None else channel.daily_reach
    if not members and avg_views is None:
        channel.stats_error = str(reading.get('views_error') or reading.get('group_error') or 'empty')[:255]
        channel.stats_updated_at = timezone.now()
        _remember_linkyar_admin(channel, reading)
        channel.save(update_fields=['stats_error', 'stats_updated_at', 'linkyar_is_admin', 'linkyar_checked_at'])
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
    if err is None:
        err = channel.err_percent
    channel.err_percent = Decimal(str(err or 0))
    channel.stats_updated_at = now
    channel.stats_error = str(reading.get('views_error') or '')[:255] if views_failed else ''
    _remember_linkyar_admin(channel, reading)
    _check_bot_admin_if_configured(channel)
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


def recent_snapshots(channel_ids: List[int], limit: int = 6) -> Dict[int, List[Dict[str, Any]]]:
    """آخرین برداشت‌های هر کانال، از قدیم به جدید، برای نمودار مینی‌اپ."""
    if not channel_ids:
        return {}
    from channels_app.models import ChannelStatSnapshot

    since = timezone.now() - timedelta(days=21)
    buckets: Dict[int, List[Any]] = {}
    rows = (
        ChannelStatSnapshot.objects.filter(channel_id__in=channel_ids, taken_at__gte=since)
        .order_by('channel_id', '-taken_at')
        .values('channel_id', 'taken_at', 'members', 'avg_views', 'daily_reach', 'posts', 'forwards')
    )
    for row in rows:
        bucket = buckets.setdefault(row['channel_id'], [])
        if len(bucket) >= limit:
            continue
        bucket.append(row)
    out: Dict[int, List[Dict[str, Any]]] = {}
    for cid, items in buckets.items():
        items.reverse()
        out[cid] = [
            {
                'at': item['taken_at'].isoformat(),
                'members': item['members'],
                'views': item['avg_views'],
                'daily_reach': item['daily_reach'],
                'posts': item['posts'],
                'forwards': item['forwards'],
            }
            for item in items
        ]
    return out


def refresh_due_channels(max_age: timedelta = _FRESH, limit: int = 25) -> Dict[str, int]:
    from django.db.models import F

    from channels_app.models import Channel

    cutoff = timezone.now() - max_age
    due = (
        Channel.objects.exclude(link='')
        .filter(models_q_due(cutoff))
        .order_by(F('stats_updated_at').asc(nulls_first=True), 'id')[: max(int(limit), 1)]
    )
    done = 0
    failed = 0
    for channel in due:
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
