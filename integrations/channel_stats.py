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

_FRESH = timedelta(hours=20)


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
    """آمار کانال از پست‌های اصلی (نه بازارسال).

    بازدید ۲۴ساعته:
      تا ۳ پستی که سن‌شان به ۲۴ ساعت نزدیک‌تر است انتخاب می‌شوند.
      بازدید هر کدام با (views / age_hours) * 24 به معادل ۲۴ساعت نرمال می‌شود
      و میانگین گرفته می‌شود.

    نرخ تعامل (‰):
      برای همان پست‌ها: (مجموع واکنش‌ها / مجموع بازدید) * 1000
      اگر واکنش نبود، از forwards به‌عنوان تقریب استفاده می‌شود.
    """
    now_ms = int(timezone.now().timestamp() * 1000)
    target_age = _DAY_MS  # 24h
    real = [p for p in posts if p.get('message_id')]
    base = real or list(posts)

    candidates = []
    for post in base:
        if not isinstance(post.get('views'), int) or int(post['views']) < 0:
            continue
        # بازارسال‌ها را کنار بگذار
        if post.get('is_forward') or post.get('forwarded'):
            continue
        stamp = _to_ms(post.get('date'))
        if not stamp:
            continue
        age = now_ms - stamp
        if age < _HOUR_MS:
            # هنوز بازدید جمع نشده
            continue
        # پنجره معقول: بین ۶ ساعت تا ۵ روز
        if age > 5 * _DAY_MS:
            continue
        views = int(post['views'])
        reactions = post.get('reactions')
        if not isinstance(reactions, int) or reactions < 0:
            reactions = int(post.get('forwards') or 0)
        candidates.append({
            'views': views,
            'age': age,
            'reactions': max(0, int(reactions)),
            'post': post,
            'dist': abs(age - target_age),
        })

    candidates.sort(key=lambda x: x['dist'])
    sample = candidates[:3]

    daily_reach = None
    if sample:
        norms = []
        for c in sample:
            age_h = c['age'] / _HOUR_MS
            if age_h <= 0:
                continue
            norms.append(c['views'] / age_h * 24.0)
        if norms:
            daily_reach = int(round(sum(norms) / len(norms)))

    # میانگین بازدید (پست‌های بالغ) برای فیلد avg_views
    mature_views = [c['views'] for c in candidates]
    avg_views = int(round(sum(mature_views) / len(mature_views))) if mature_views else None
    if avg_views is None and daily_reach is not None:
        avg_views = daily_reach

    total_reactions = sum(c['reactions'] for c in sample) if sample else 0
    total_views = sum(c['views'] for c in sample) if sample else 0
    # نرخ تعامل: واکنش به ازای هر هزار بازدید
    err = None
    if total_views > 0:
        err = round(total_reactions / total_views * 1000, 2)

    forwards = sum(int(p.get('forwards') or 0) for p in base)
    dates = [d for d in (_to_ms(p.get('date')) for p in base) if d]
    span_days = 1.0
    if len(dates) >= 2:
        span_days = max((max(dates) - min(dates)) / _DAY_MS, 1.0)
    posts_per_day = round(len(base) / span_days, 2) if base else 0.0
    citation = round(forwards / len(base), 3) if base else 0.0

    return {
        'members': members,
        'avg_views': avg_views,
        'daily_reach': daily_reach,
        'posts': len(base),
        'forwards': forwards,
        'posts_per_day': posts_per_day,
        'citation_index': citation,
        'err_percent': err,
        'sample_size': len(sample),
    }


def public_stats_error(raw: str) -> str:
    text = (raw or '').strip()
    known = {
        'link missing': 'پیوند کانال ثبت نشده.',
        'BALE_TOKEN missing': 'حساب دستیار لینک‌بان هنوز آماده نیست. کمی بعد دوباره آمار را بخوانید.',
        'empty': 'از این کانال عددی خوانده نشد.',
        'channel_not_found': 'این کانال در بله پیدا نشد.',
        'resolve_failed': 'این کانال در بله پیدا نشد.',
        'no_stats': 'از این کانال عددی خوانده نشد.',
    }
    if text in known:
        return known[text]
    if text.startswith('token_inject'):
        return 'حساب دستیار لینک‌بان وصل نشد. کمی بعد دوباره آمار را بخوانید.'
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
    link = (channel.link or '').strip().lower()
    bare = link.replace('https://', '').replace('http://', '')
    for prefix in ('ble.ir/', 'bale.ai/'):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    bare = bare.split('/')[0].lstrip('@').strip()
    name_looks_like_id = (
        not channel.name
        or channel.name == '(no title)'
        or (bare and channel.name.lstrip('@').lower() == bare)
    )
    if title and name_looks_like_id:
        channel.name = title[:200]
    lang_src = f"{about} {title}"
    channel.language = _guess_lang(lang_src)
    channel.members_count = int(members or 0)
    channel.avg_views = int(avg_views or 0)
    channel.daily_reach = int(daily or 0)
    channel.posts_per_day = Decimal(str(summary['posts_per_day']))
    channel.citation_index = Decimal(str(summary['citation_index']))
    err = summary.get('err_percent')
    if err is None:
        err = 0
    channel.err_percent = Decimal(str(err or 0))
    channel.stats_updated_at = now
    channel.stats_error = str(reading.get('views_error') or '')[:255] if views_failed else ''
    _remember_linkyar_admin(channel, reading)
    _check_bot_admin_if_configured(channel)
    channel.save()
    channel.save()
    try:
        ChannelStatSnapshot.objects.create(
            channel=channel,
            taken_at=now,
            members=channel.members_count,
            avg_views=channel.avg_views,
            daily_reach=channel.daily_reach,
            posts=int(summary.get('posts') or 0),
            forwards=int(summary.get('forwards') or 0),
            engagement=channel.err_percent or 0,
            source='linkyar',
        )
    except TypeError:
        ChannelStatSnapshot.objects.create(
            channel=channel,
            taken_at=now,
            members=channel.members_count,
            avg_views=channel.avg_views,
            daily_reach=channel.daily_reach,
            posts=int(summary.get('posts') or 0),
            forwards=int(summary.get('forwards') or 0),
            source='linkyar',
        )


def recent_snapshots(channel_ids: List[int], limit: int = 60) -> Dict[int, List[Dict[str, Any]]]:
    """آخرین برداشت‌های هر کانال، از قدیم به جدید، برای نمودار مینی‌اپ."""
    if not channel_ids:
        return {}
    from channels_app.models import ChannelStatSnapshot

    since = timezone.now() - timedelta(days=45)
    buckets: Dict[int, List[Any]] = {}
    try:
        rows = (
            ChannelStatSnapshot.objects.filter(channel_id__in=channel_ids, taken_at__gte=since)
            .order_by('channel_id', '-taken_at')
            .values('channel_id', 'taken_at', 'members', 'avg_views', 'daily_reach', 'posts', 'forwards', 'engagement')
        )
    except Exception:
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
                'engagement': float(item.get('engagement') or 0),
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
