"""Mini-app shop APIs: banners, cart, calendar, tariff edit, operator banners."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from datetime import datetime

from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bot_flow.jalali import format_jalali
from bot_flow.messages import fa_num
from channels_app.models import Channel, Tariff
from miniapp.api import _auth_user, _json_body
from orders import cart as cart_svc
from orders.availability import (
    clear_manual_busy_slot,
    day_status_for_viewer,
    day_status_map,
    has_slot_conflict,
    list_manual_busy_slots,
    mark_tariff_day_busy,
    unavailable_why,
    viewer_has_ready_banner,
)
from orders.banner_publish import operator_decide
from orders.models import BannerPublishRequest, CustomerBanner, Order, OrderItem
from wallet import services as ws


ERR_FA = {
    'not_found': 'این مورد را پیدا نکردم. یک بار دیگر از فهرست انتخاب کنید.',
    'forbidden': 'این کار برای شما نیست.',
    'bad_fields': 'نام، ساعت، مدت و قیمت را کامل بنویسید.',
    'bad_date': 'این تاریخ درست نیست. یک روز دیگر را انتخاب کنید.',
    'empty_cart': 'هنوز روزی انتخاب نکرده‌اید.',
    'no_banner': 'اول یک بنر تأییدشده از لینک‌بانک لازم است. بدون بنر آماده نمی‌توانید روز بگیرید یا سفارش ثبت کنید.',
    'slot_conflict': 'این روز پر است. روز دیگری را انتخاب کنید.',
    'no_channel': 'برای این تعرفه کانالی وصل نیست. اول کانال را اضافه کنید.',
    'already_pending': 'یک درخواست تسویه باز دارید. بعد از واریز همان، دوباره درخواست بدهید.',
    'weekly_limit': 'از تسویهٔ قبلی هنوز یک هفته نگذشته. بعد از آن دوباره درخواست بدهید.',
    'below_minimum': 'حداقل تسویه صد هزار تومان است. وقتی اعتبارتان رسید، دوباره درخواست بدهید.',
    'no_bank': 'اول شماره شبا را ثبت کنید.',
    'invalid_iban': 'شماره شبا درست نیست. با IR و ۲۴ رقم دوباره بفرستید.',
    'need_holder_name': 'نام صاحب حساب را بنویسید.',
    'not_pending': 'این سفارش دیگر منتظر پاسخ شما نیست.',
    'inactive': 'این تعرفه خاموش است. یک تعرفهٔ روشن را انتخاب کنید.',
    'not_cancellable': 'این سفارش الان بسته نمی‌شود. اگر منتشر شده، اعتراض ثبت کنید.',
    'too_late': 'از ۲ ساعت پیش از انتشار دیگر لغو نمی‌شود. اگر مشکلی هست، اعتراض ثبت کنید.',
    'past': 'این ساعت گذشته است. روز دیگری را انتخاب کنید.',
    'not_paid': 'این سفارش هنوز پرداخت نشده. فقط سفارش پرداخت‌شده به اعتبار برمی‌گردد.',
    'already_refunded': 'مبلغ این سفارش قبلاً به اعتبار برگشته.',
    'inactive_tariff': 'این تعرفه خاموش است و روزش فروخته نمی‌شود.',
}

_NOT_YOUR_TARIFF = 'این تعرفه برای کانال شما نیست. روز کانال خودتان را انتخاب کنید.'


def _err(code: str, status: int = 200, message: str = '') -> JsonResponse:
    """خطاهای مینی‌اپ با status=200 تا کلاینت بدنه JSON را بخواند (نه HTML)."""
    from bot_flow.messages import user_error

    text = message or ERR_FA.get(code) or user_error(code) or code
    return JsonResponse(
        {'ok': False, 'error': code, 'message': text},
        status=status if status else 200,
    )


def _parse_day(body) -> object | None:
    raw = str(body.get('date') or '')[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _align_submitted_order(order: Order) -> None:
    """مبلغ ذخیره‌شده را با قلم‌ها یکی می‌کند. بنر آماده از انتظار بنر خارج می‌شود."""
    from orders.banner_publish import banner_stage

    if order.status in ('draft', 'cancelled', 'rejected'):
        return
    total = sum(
        int(price or 0)
        for price in order.items.exclude(
            manager_status__in=('rejected', 'expired', 'customer_declined')
        ).values_list('price', flat=True)
    )
    if total and int(order.total_amount or 0) != total:
        order.total_amount = total
        order.save(update_fields=['total_amount'])
    banner = order.customer_banner
    if order.status == 'waiting_banner' and banner is not None and banner_stage(banner) == 'ready':
        from orders.cart import release_orders_waiting_on_banner

        release_orders_waiting_on_banner(banner)
        order.refresh_from_db()



def _bot_deep_link() -> str:
    """لینک باز کردن گفتگوی بازو در بله."""
    import os
    raw = (
        os.environ.get('BALE_BOT_USERNAME')
        or os.environ.get('BOT_USERNAME')
        or os.environ.get('LINKBANK_BOT_USERNAME')
        or ''
    ).strip()
    if not raw:
        return ''
    if raw.startswith('https://') or raw.startswith('ble://'):
        return raw
    user = raw.lstrip('@')
    return f'https://ble.ir/{user}'


def _order_deadline_hint(order: Order) -> str:
    """مهلت مرحلهٔ جاری، از همان managers_deadline، بدون ستون تازه."""
    if order.status not in ('waiting_payment', 'waiting_managers', 'waiting_customer_confirm'):
        return ''
    if not order.managers_deadline:
        return ''
    remaining = int((order.managers_deadline - timezone.now()).total_seconds())
    if order.status == 'waiting_payment':
        label = 'برای پرداخت'
    elif order.status == 'waiting_customer_confirm':
        label = 'برای تأیید زمان'
    else:
        label = 'برای پاسخ کانال‌ها'
    if remaining <= 0:
        return 'مهلت این مرحله تمام شده'
    hours = remaining // 3600
    minutes = (remaining % 3600) // 60
    if hours >= 48:
        return f'تا {fa_num(hours // 24)} روز {label}'
    if hours >= 1:
        return f'تا {fa_num(hours)} ساعت {label}'
    return f'تا {fa_num(max(minutes, 1))} دقیقه {label}'


def _own_tariff(user, tariff_id):
    try:
        tid = int(tariff_id)
    except (TypeError, ValueError):
        return None
    t = Tariff.objects.select_related('channel', 'group').filter(id=tid).first()
    if not t:
        return None
    ok = (t.channel_id and t.channel and t.channel.manager_id == user.id) or (
        t.group_id and t.group and t.group.manager_id == user.id
    )
    return t if ok else False


@csrf_exempt
@require_http_methods(['POST'])
def api_set_publish_mode(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request) or {}
    try:
        cid = int(body.get('channel_id'))
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'شناسه کانال نامعتبر است.'}, status=200)
    ch = Channel.objects.filter(id=cid, manager=user).first()
    if not ch:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'کانال پیدا نشد.'}, status=200)
    mode = body.get('publish_mode')
    if mode not in (Channel.PUBLISH_BOT, Channel.PUBLISH_LINKYAR, Channel.PUBLISH_MANUAL):
        return JsonResponse({'ok': False, 'error': 'bad_mode', 'message': 'این روش انتشار را نمی‌شناسم.'}, status=200)
    ch.publish_mode = mode
    fields = ['publish_mode']
    hours = body.get('remind_hours')
    if hours is not None and str(hours) != '':
        try:
            ch.manual_remind_hours = max(1, min(48, int(hours)))
            fields.append('manual_remind_hours')
        except (TypeError, ValueError):
            pass
    ch.save(update_fields=fields)
    return JsonResponse({
        'ok': True,
        'channel_id': ch.id,
        'publish_mode': ch.publish_mode,
        'manual_remind_hours': ch.manual_remind_hours,
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_calendar(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = {}
    try:
        if request.method == 'POST':
            body = _json_body(request) or {}
    except Exception:
        body = {}
    tid_raw = request.GET.get('tariff_id') or body.get('tariff_id')
    customer = (request.GET.get('for') or body.get('for') or '') == 'customer'
    t = _own_tariff(user, tid_raw)
    if customer:
        t = Tariff.objects.select_related('channel', 'group').filter(
            id=tid_raw, is_active=True
        ).first()
        if not t:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد.'}, status=200)
    elif t is None:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد.'}, status=200)
    elif t is False:
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': _NOT_YOUR_TARIFF}, status=200)
    ready_banner = True if not customer else viewer_has_ready_banner(user)
    try:
        span = int(request.GET.get('days') or body.get('days') or 42)
    except (TypeError, ValueError):
        span = 42
    span = max(14, min(span, 62))
    days = []
    for d, raw in day_status_map(t, span):
        status = raw if not customer else day_status_for_viewer(t, d, ready_banner=ready_banner)
        days.append({
            'date': d.isoformat(),
            'jalali': format_jalali(d),
            'free': status == 'free',
            'status': status,
            'why': unavailable_why(status),
        })
    busy_slots = []
    if not customer:
        for s in list_manual_busy_slots(t):
            day = timezone.localtime(s.start).date() if timezone.is_aware(s.start) else s.start.date()
            busy_slots.append({
                'id': s.id,
                'date': day.isoformat(),
                'jalali': format_jalali(day),
            })
    channel_count = 0
    if t.group_id:
        channel_count = t.group.channels.count()
    elif t.channel_id:
        channel_count = 1
    return JsonResponse({
        'ok': True,
        'tariff_id': t.id,
        'name': t.name,
        'owner': t.group.name if t.group_id else (t.channel.name if t.channel_id else ''),
        'is_package': bool(t.group_id),
        'channel_count': channel_count,
        'days': days,
        'manual_busy': busy_slots,
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_busy_day(request: HttpRequest) -> JsonResponse:
    """علامت‌زدن روز پر — مقاوم در برابر خطای دیتابیس/منطقه‌زمانی."""
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            tid = int(body.get('tariff_id'))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'شناسه تعرفه نامعتبر است.'}, status=200)
        t = _own_tariff(user, tid)
        if t is None:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد.'}, status=200)
        if t is False:
            return JsonResponse({'ok': False, 'error': 'forbidden', 'message': _NOT_YOUR_TARIFF}, status=200)
        day = _parse_day(body)
        if not day:
            return JsonResponse({'ok': False, 'error': 'bad_date', 'message': 'تاریخ نامعتبر است.'}, status=200)

        from channels_app.models import AvailabilitySlot
        from datetime import time as dtime, timedelta, datetime as dt
        from django.db import OperationalError, ProgrammingError
        from orders.availability import MANUAL_BUSY_NOTE

        hour = 0
        try:
            if t.start_hour is not None:
                hour = max(0, min(23, int(t.start_hour)))
        except (TypeError, ValueError):
            hour = 0
        try:
            duration = max(1, int(t.duration_hours or 1))
        except (TypeError, ValueError):
            duration = 1

        naive_start = dt.combine(day, dtime(hour=hour, minute=0, second=0))
        # Django USE_TZ: aware in current TZ؛ در MySQL گاهی aware مستقیم خطا می‌دهد
        try:
            start = timezone.make_aware(naive_start, timezone.get_current_timezone())
            end = start + timedelta(hours=duration)
        except Exception:
            start = naive_start
            end = naive_start + timedelta(hours=duration)

        day_start_naive = dt.combine(day, dtime.min)
        day_end_naive = day_start_naive + timedelta(days=1)
        try:
            day_start = timezone.make_aware(day_start_naive, timezone.get_current_timezone())
            day_end = timezone.make_aware(day_end_naive, timezone.get_current_timezone())
        except Exception:
            day_start, day_end = day_start_naive, day_end_naive

        def _find_existing():
            qs = AvailabilitySlot.objects.filter(is_available=False)
            try:
                qs = qs.filter(tariff_id=t.id)
            except Exception:
                pass
            try:
                return qs.filter(start__gte=day_start, start__lt=day_end).order_by('-id').first()
            except Exception:
                # fallback without range (SQLite/MySQL quirks)
                for slot in qs.order_by('-id')[:50]:
                    try:
                        sd = timezone.localtime(slot.start).date() if timezone.is_aware(slot.start) else slot.start.date()
                    except Exception:
                        try:
                            sd = slot.start.date()
                        except Exception:
                            continue
                    if sd == day:
                        return slot
                return None

        existing = _find_existing()
        if existing:
            return JsonResponse({'ok': True, 'slot_id': existing.id, 'jalali': format_jalali(day)})

        def _create(use_aware=True):
            s = start if use_aware else naive_start
            e = end if use_aware else (naive_start + timedelta(hours=duration))
            kwargs = {
                'start': s,
                'end': e,
                'is_available': False,
                'note': (MANUAL_BUSY_NOTE or 'manual-busy')[:255],
            }
            # FKها را جدا اضافه کن تا اگر ستون نبود، بدون آن‌ها تست شود
            try:
                kwargs['tariff_id'] = t.id
            except Exception:
                pass
            if t.group_id:
                kwargs['group_id'] = t.group_id
            elif t.channel_id:
                kwargs['channel_id'] = t.channel_id
            return AvailabilitySlot.objects.create(**kwargs)

        slot = None
        last_err = None
        for aware in (True, False):
            try:
                slot = _create(use_aware=aware)
                break
            except (OperationalError, ProgrammingError) as exc:
                last_err = exc
                logger.exception('AvailabilitySlot.create aware=%s', aware)
                continue
            except Exception as exc:
                last_err = exc
                logger.exception('AvailabilitySlot.create')
                break
        if slot is None:
            # حداقل در state کلاینت بماند — شناسه موقت منفی
            msg = 'ثبت روز پر در دیتابیس نشد'
            if last_err is not None:
                msg += ': ' + type(last_err).__name__
                detail = str(last_err)
                # پیام‌های رایج MySQL
                if 'datetime' in detail.lower() or 'Incorrect' in detail:
                    msg = 'خطای تاریخ/ساعت دیتابیس. منطقه زمانی سرور را چک کنید.'
                elif 'Unknown column' in detail or 'no such column' in detail.lower():
                    msg = 'ستون جدول نوبت در دیتابیس قدیمی است. migrate لازم است.'
                elif 'no such table' in detail.lower() or "doesn't exist" in detail.lower():
                    msg = 'جدول نوبت وجود ندارد. روی سرور: python manage.py migrate'
            return JsonResponse({
                'ok': False, 'error': 'db', 'message': msg,
                'detail': (str(last_err)[:200] if last_err else ''),
            }, status=200)

        return JsonResponse({'ok': True, 'slot_id': slot.id, 'jalali': format_jalali(day)})
    except Exception as exc:
        try:
            logger.exception('api_busy_day')
        except Exception:
            pass
        return JsonResponse({
            'ok': False, 'error': 'server',
            'message': 'ثبت روز پر نشد: ' + type(exc).__name__,
            'detail': str(exc)[:200],
        }, status=200)



@csrf_exempt
@require_http_methods(['POST'])
def api_clear_busy(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            tid = int(body.get('tariff_id'))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'شناسه تعرفه نامعتبر است.'}, status=200)
        t = _own_tariff(user, tid)
        if t is None:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد.'}, status=200)
        if t is False:
            return JsonResponse({'ok': False, 'error': 'forbidden', 'message': _NOT_YOUR_TARIFF}, status=200)
        slot_id = 0
        try:
            slot_id = int(body.get('slot_id') or 0)
        except (TypeError, ValueError):
            slot_id = 0
        ok = False
        if slot_id:
            ok = clear_manual_busy_slot(slot_id, t)
        if not ok:
            day = _parse_day(body)
            if day:
                from channels_app.models import AvailabilitySlot
                from datetime import time as dtime, datetime as dt, timedelta
                day_start = timezone.make_aware(dt.combine(day, dtime.min), timezone.get_current_timezone())
                day_end = day_start + timedelta(days=1)
                deleted, _ = AvailabilitySlot.objects.filter(
                    tariff_id=t.id, is_available=False, start__gte=day_start, start__lt=day_end
                ).delete()
                ok = deleted > 0
        return JsonResponse({'ok': True, 'cleared': bool(ok)})
    except Exception as exc:
        try:
            logger.exception('api_clear_busy')
        except Exception:
            pass
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'خالی کردن روز نشد: ' + type(exc).__name__}, status=200)



@csrf_exempt
@require_http_methods(['POST'])
def api_tariff_update(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        t = _own_tariff(user, body.get('tariff_id'))
        if t is None:
            return _err('not_found', message='تعرفه پیدا نشد.')
        if t is False:
            return _err('forbidden', message=_NOT_YOUR_TARIFF)
        fields = []
        if 'name' in body and str(body['name']).strip():
            t.name = str(body['name']).strip()[:100]
            fields.append('name')
        try:
            if 'price' in body and str(body['price']) != '':
                t.price = max(0, int(body['price']))
                fields.append('price')
            if 'duration_hours' in body and str(body['duration_hours']) != '':
                t.duration_hours = max(1, int(body['duration_hours']))
                fields.append('duration_hours')
            if 'start_hour' in body and str(body['start_hour']) != '':
                t.start_hour = max(0, min(23, int(body['start_hour'])))
                fields.append('start_hour')
        except (TypeError, ValueError):
            return _err('bad_fields', message='قیمت، مدت یا ساعت نامعتبر است.')
        if 'is_active' in body:
            t.is_active = bool(body['is_active'])
            fields.append('is_active')
        if not fields:
            return _err('bad_fields', message='چیزی برای ذخیره نبود.')
        t.save(update_fields=fields)
        return JsonResponse({'ok': True, 'tariff_id': t.id})
    except Exception as exc:
        logger.exception('api_tariff_update')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'ویرایش تعرفه نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_tariff_delete(request: HttpRequest) -> JsonResponse:
    """حذف تعرفه. اگر سفارش/رزرو داشته باشد فقط غیرفعال می‌شود."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request) or {}
    t = _own_tariff(user, body.get('tariff_id'))
    if t is None:
        return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد.'}, status=200)
    if t is False:
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': _NOT_YOUR_TARIFF}, status=200)
    has_items = OrderItem.objects.filter(tariff_id=t.id).exists()
    from orders.models import SlotReservation
    has_slots = SlotReservation.objects.filter(tariff_id=t.id).exists()
    if has_items or has_slots:
        if t.is_active:
            t.is_active = False
            t.save(update_fields=['is_active'])
        return JsonResponse({
            'ok': True,
            'tariff_id': t.id,
            'deleted': False,
            'deactivated': True,
            'message': 'این تعرفه سفارش یا رزرو دارد؛ فقط غیرفعال شد.',
        })
    tid = t.id
    t.delete()
    return JsonResponse({'ok': True, 'tariff_id': tid, 'deleted': True, 'deactivated': False})


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_banners(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    from orders.banner_publish import banner_stage

    from orders.banner_media import public_media_url

    rows = []
    for b in CustomerBanner.objects.filter(customer=user, is_active=True)[:40]:
        stage = banner_stage(b)
        media_url = public_media_url(b)
        rows.append({
            'id': b.id,
            'title': b.display_title(),
            'caption': b.caption or '',
            'from_linkbank': stage == 'ready',
            'stage': stage,
            'reject_reason': (
                'متن یا محتوای بنر تأیید نشد. متن را اصلاح کنید و دوباره بفرستید.'
                if stage == 'rejected'
                else ''
            ),
            'media_kind': b.media_kind,
            'media_url': media_url,
            'poster_url': '' if b.media_kind in ('video', 'animation') else media_url,
        })
    return JsonResponse({'ok': True, 'banners': rows})


@csrf_exempt
@require_http_methods(['GET'])
def api_banner_media(request: HttpRequest, banner_id: int) -> HttpResponse:
    """فایل بنر برای تگ img. احراز هویت در هدر تصویر نمی‌آید."""
    from orders.banner_media import file_for_request

    found = file_for_request(banner_id)
    if not found:
        return HttpResponse(status=404)
    path, content_type = found
    resp = FileResponse(path.open('rb'), content_type=content_type)
    resp['Cache-Control'] = 'private, max-age=86400'
    return resp


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_rename(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            bid = int(body.get('banner_id'))
        except (TypeError, ValueError):
            return _err('bad_fields', message='شناسه بنر نامعتبر است.')
        b = CustomerBanner.objects.filter(id=bid, customer=user).first()
        if not b:
            return _err('not_found', message='بنر پیدا نشد.')
        title = str(body.get('title') or '').strip()[:120]
        if not title:
            return _err('bad_fields', message='عنوان بنر را بنویسید.')
        b.title = title
        b.save(update_fields=['title'])
        return JsonResponse({'ok': True, 'banner_id': b.id, 'title': b.title})
    except Exception as exc:
        logger.exception('api_banner_rename')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'تغییر عنوان بنر نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_hide(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            bid = int(body.get('banner_id'))
        except (TypeError, ValueError):
            return _err('bad_fields', message='شناسه بنر نامعتبر است.')
        b = CustomerBanner.objects.filter(id=bid, customer=user, is_active=True).first()
        if not b:
            return _err('not_found', message='بنر پیدا نشد.')
        b.is_active = False
        b.save(update_fields=['is_active'])
        return JsonResponse({'ok': True, 'banner_id': b.id})
    except Exception as exc:
        logger.exception('api_banner_hide')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'مخفی کردن بنر نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_revise(request: HttpRequest) -> JsonResponse:
    """ویرایش عنوان/کپشن بنر خود کاربر."""
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            bid = int(body.get('banner_id'))
        except (TypeError, ValueError):
            return _err('bad_fields', message='شناسه بنر نامعتبر است.')
        b = CustomerBanner.objects.filter(id=bid, customer=user, is_active=True).first()
        if not b:
            return _err('not_found', message='بنر پیدا نشد.')
        from bot_flow.banned_words import is_allowed
        from orders.banner_publish import banner_stage

        title = body.get('title')
        caption = body.get('caption')
        fields = []
        if title is not None:
            title_s = str(title).strip()[:120]
            if len(title_s) < 2:
                return _err('bad_fields', message='عنوان کوتاه است.')
            ok, _ = is_allowed(title_s)
            if not ok:
                return _err('banned', message='عنوان شامل عبارت غیرمجاز است.')
            b.title = title_s
            fields.append('title')
        if caption is not None:
            cap = str(caption).strip()
            if len(cap) < 12:
                return _err('bad_fields', message='کپشن کوتاه است.')
            ok, _ = is_allowed(cap)
            if not ok:
                return _err('banned', message='کپشن شامل عبارت غیرمجاز است.')
            b.caption = cap[:2000]
            fields.append('caption')
        if not fields:
            return _err('bad_fields', message='چیزی برای ذخیره نبود.')
        b.save(update_fields=fields)
        return JsonResponse({'ok': True, 'banner_id': b.id, 'stage': banner_stage(b)})
    except Exception as exc:
        logger.exception('api_banner_revise')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'ویرایش بنر نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_banner_resubmit(request: HttpRequest) -> JsonResponse:
    """ارسال دوباره بنر ردشده برای بررسی پشتیبانی."""
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            bid = int(body.get('banner_id'))
        except (TypeError, ValueError):
            return _err('bad_fields', message='شناسه بنر نامعتبر است.')
        b = CustomerBanner.objects.filter(id=bid, customer=user, is_active=True).first()
        if not b:
            return _err('not_found', message='بنر پیدا نشد.')
        from bot_flow.banned_words import is_allowed
        from orders.banner_publish import banner_stage, create_publish_request

        if banner_stage(b) != 'rejected':
            return _err('bad_fields', message='فقط بنر ردشده را می‌توان دوباره فرستاد.')
        caption = str(body.get('caption') if body.get('caption') is not None else b.caption or '').strip()
        if len(caption) < 12:
            return _err('bad_fields', message='کپشن کوتاه است.')
        ok, _ = is_allowed(caption)
        if not ok:
            return _err('banned', message='کپشن شامل عبارت غیرمجاز است.')
        if body.get('title') is not None:
            title_s = str(body.get('title') or '').strip()[:120]
            if title_s:
                ok, _ = is_allowed(title_s)
                if not ok:
                    return _err('banned', message='عنوان شامل عبارت غیرمجاز است.')
                b.title = title_s
        b.caption = caption[:2000]
        b.save(update_fields=['title', 'caption'] if body.get('title') is not None else ['caption'])
        if not b.storage_chat_id or not b.storage_message_id:
            return _err('bad_fields', message='فایل بنر ناقص است؛ از بازو دوباره بفرستید.')
        result = create_publish_request(
            user,
            storage_chat_id=b.storage_chat_id,
            storage_message_id=b.storage_message_id,
            caption=b.caption,
            media_kind=b.media_kind or '',
            banner=b,
        )
        if not result.get('ok'):
            return _err(result.get('error') or 'error', message=str(result.get('message') or 'ثبت درخواست نشد.'))
        return JsonResponse({
            'ok': True,
            'banner_id': b.id,
            'request_id': result['request'].id,
            'stage': 'pending',
            'fee': result.get('fee', 0),
        })
    except Exception as exc:
        logger.exception('api_banner_resubmit')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'ارسال دوباره بنر نشد: ' + type(exc).__name__}, status=200)



@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_cart(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    cart_svc.release_abandoned_carts(user)
    order = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
    ready_banner = viewer_has_ready_banner(user)
    items = []
    total = 0
    cart_status = 'free'
    if order:
        for it in order.items.filter(manager_status='cart').select_related('tariff', 'channel', 'tariff__group'):
            start = timezone.localtime(it.requested_start)
            line_status = day_status_for_viewer(it.tariff, start.date(), ready_banner=True)
            if line_status == 'full' and not has_slot_conflict(
                it.tariff,
                it.requested_start,
                it.requested_end,
                channel=it.channel,
                exclude_item_id=it.id,
            ):
                line_status = 'free'
            if line_status == 'free' and not ready_banner:
                line_status = 'banner-hold'
            items.append({
                'id': it.id,
                'tariff_id': it.tariff_id,
                'owner': it.tariff.group.name if it.tariff.group_id else (it.channel.name if it.channel else ''),
                'name': it.tariff.name,
                'date': start.date().isoformat(),
                'jalali': format_jalali(start.date()),
                'price': it.price,
                'status': line_status,
                'why': unavailable_why(line_status),
                'is_package': bool(it.tariff.group_id),
                'channel_count': len(it.booked_channel_ids or []) or (
                    it.tariff.group.channels.count() if it.tariff.group_id else (1 if it.channel_id else 0)
                ),
                'group_id': it.tariff.group_id,
            })
        total = order.total_amount
        rank = {'past': 3, 'full': 2, 'banner-hold': 1, 'free': 0}
        cart_status = 'free'
        for row in items:
            if rank.get(row['status'], 0) > rank.get(cart_status, 0):
                cart_status = row['status']
    banner = None
    if order and order.customer_banner_id:
        cb = order.customer_banner
        banner = {'id': cb.id, 'title': cb.display_title()}
    hold_until = None
    if order and order.managers_deadline:
        hold_until = timezone.localtime(order.managers_deadline).isoformat()
    return JsonResponse({
        'ok': True,
        'order_id': order.id if order else None,
        'items': items,
        'total': total,
        'banner': banner,
        'has_banner': bool(order and order.banner_message_id),
        'hold_until': hold_until,
        'status': cart_status if items else 'free',
        'why': unavailable_why(cart_status) if items else '',
    })


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_add(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            tid = int(body.get('tariff_id'))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'تعرفه نامعتبر است.'}, status=200)
        t = Tariff.objects.select_related('channel', 'group').filter(id=tid, is_active=True).first()
        if not t:
            return JsonResponse({'ok': False, 'error': 'not_found', 'message': 'تعرفه پیدا نشد یا غیرفعال است.'}, status=200)
        day = _parse_day(body)
        if not day:
            return JsonResponse({'ok': False, 'error': 'bad_date', 'message': 'تاریخ نامعتبر است.'}, status=200)
        r = cart_svc.add_to_cart(user, t, day)
        if not r.get('ok'):
            code = r.get('error') or 'slot_conflict'
            return JsonResponse({'ok': False, 'error': code, 'message': ERR_FA.get(code) or 'این روز قابل رزرو نیست.'}, status=200)
        return JsonResponse({'ok': True, 'item_id': r['item'].id, 'order_id': r['order'].id})
    except Exception as exc:
        logger.exception('api_cart_add')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'افزودن به سبد نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_remove(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request)
    it = OrderItem.objects.filter(
        id=body.get('item_id'), order__customer=user, manager_status='cart'
    ).first()
    if not it:
        return _err('not_found', 404)
    order = it.order
    it.delete()
    order.recompute_total()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(['POST'])
def api_cart_banner(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        from orders.banner_publish import banner_stage
        try:
            bid = int(body.get('banner_id'))
        except (TypeError, ValueError):
            return _err('no_banner', message='بنر را انتخاب کنید.')
        b = CustomerBanner.objects.filter(
            id=bid, customer=user, is_active=True
        ).first()
        if not b or banner_stage(b) == 'rejected':
            return _err('no_banner')
        order = cart_svc.get_or_create_draft(user)
        order.customer_banner = b
        order.banner_from_chat_id = b.storage_chat_id
        order.banner_message_id = b.storage_message_id
        order.banner_caption = b.caption or ''
        order.save()
        return JsonResponse({'ok': True, 'banner_id': b.id})
    except Exception as exc:
        logger.exception('api_cart_banner')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'انتخاب بنر سبد نشد: ' + type(exc).__name__}, status=200)



@csrf_exempt
@require_http_methods(['POST'])
def api_checkout(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        cart_svc.release_abandoned_carts(user)
        order = Order.objects.filter(customer=user, status='draft').order_by('-id').first()
        if not order:
            return JsonResponse({'ok': False, 'error': 'empty_cart', 'message': 'سبد خالی است.'}, status=200)
        r = cart_svc.checkout(order)
        if not r.get('ok'):
            code = r.get('error') or 'empty_cart'
            return JsonResponse({'ok': False, 'error': code, 'message': ERR_FA.get(code) or 'ثبت سفارش ممکن نشد.'}, status=200)
        return JsonResponse({'ok': True, 'order_id': order.id, 'count': r.get('count')})
    except Exception as exc:
        logger.exception('api_checkout')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'تسویه سبد نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_suggest_time(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        if not user.bale_user_id:
            return _err('no_user', message='شناسه بله مشخص نیست.')
        body = _json_body(request) or {}
        day = _parse_day(body)
        if not day:
            return _err('bad_date')
        try:
            iid = int(body.get('item_id'))
        except (TypeError, ValueError):
            return _err('not_found', message='آیتم سفارش پیدا نشد.')
        item = OrderItem.objects.select_related('tariff').filter(id=iid, manager=user).first()
        if not item:
            return _err('not_found', message='آیتم سفارش پیدا نشد.')
        start, _end = cart_svc.slot_for_day(item.tariff, day)
        result = cart_svc.process_manager_item(item.id, str(user.bale_user_id), 'edit', new_start=start)
        if not result.get('ok'):
            return _err(result.get('error') or 'slot_conflict')
        return JsonResponse({'ok': True, 'item_id': item.id, 'date': day.isoformat()})
    except Exception as exc:
        logger.exception('api_suggest_time')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'پیشنهاد زمان نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_answer_time(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        if not user.bale_user_id:
            return _err('no_user', message='شناسه بله مشخص نیست.')
        body = _json_body(request) or {}
        try:
            item_id = int(body.get('item_id') or 0)
        except (TypeError, ValueError):
            return _err('not_found', message='آیتم سفارش پیدا نشد.')
        result = cart_svc.customer_confirm_edit(item_id, str(user.bale_user_id), bool(body.get('accept')))
        if not result.get('ok'):
            return _err(result.get('error') or 'not_pending')
        return JsonResponse({'ok': True, 'order_status': result.get('order_status')})
    except Exception as exc:
        logger.exception('api_answer_time')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'پاسخ به زمان پیشنهادی نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_my_orders(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    rows = []
    for o in (
        Order.objects.filter(customer=user)
        .exclude(status='draft')
        .select_related('customer_banner')
        .order_by('-id')[:40]
    ):
        _align_submitted_order(o)
        can_pay = o.status == 'waiting_payment'
        can_cancel = o.status in (
            'waiting_banner',
            'waiting_managers',
            'waiting_customer_confirm',
            'waiting_payment',
        ) or (o.status == 'paid' and cart_svc.refund_window_open(o))
        deadline_iso = ''
        if o.managers_deadline and o.status in (
            'waiting_payment',
            'waiting_managers',
            'waiting_customer_confirm',
        ):
            deadline_iso = timezone.localtime(o.managers_deadline).isoformat()
        pay_parts = 0
        pay_parts_paid = 0
        if o.status == 'waiting_payment':
            from orders.bale_pay import paid_part_amounts, payment_parts

            parts = payment_parts(o.total_amount)
            got = paid_part_amounts(o)
            pay_parts = len(parts)
            pay_parts_paid = sum(
                1 for i, amount in enumerate(parts, start=1) if got.get(i) == amount
            )
        item_rows = []
        for it in o.items.exclude(manager_status='cart').select_related(
            'channel', 'tariff', 'tariff__group'
        )[:20]:
            start = it.effective_start
            item_rows.append({
                'id': it.id,
                'owner': (
                    it.tariff.group.name
                    if it.tariff_id and it.tariff.group_id
                    else (it.channel.name if it.channel_id else '?')
                ),
                'tariff_name': it.tariff.name if it.tariff_id else '',
                'date': timezone.localtime(start).date().isoformat() if start else '',
                'price': int(it.price or 0),
                'manager_status': it.manager_status,
                'execution_status': it.execution_status,
                'proposed_date': (
                    timezone.localtime(it.manager_edited_start).date().isoformat()
                    if it.manager_status == 'edited' and it.manager_edited_start
                    else ''
                ),
                'published_link': it.published_link or '',
            })
        rows.append({
            'id': o.id,
            'status': o.status,
            'total': o.total_amount,
            'created': timezone.localtime(o.created_at).date().isoformat() if o.created_at else '',
            'banner_title': o.customer_banner.display_title() if o.customer_banner_id else '',
            'pay_hint': _order_deadline_hint(o),
            'managers_deadline': deadline_iso,
            'payment_deadline': deadline_iso if can_pay else '',
            'pay_parts': pay_parts,
            'pay_parts_paid': pay_parts_paid,
            'can_pay': can_pay,
            'can_cancel': can_cancel,
            'can_dispute': o.status == 'paid' and not can_cancel,
            'items': item_rows,
        })
    bot = _bot_deep_link()
    return JsonResponse({'ok': True, 'orders': rows, 'bot_url': bot})


@csrf_exempt
@require_http_methods(['POST'])
def api_order_cancel(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            order_id = int(body.get('order_id') or 0)
        except (TypeError, ValueError):
            return _err('not_found', message='سفارش پیدا نشد.')
        order = Order.objects.filter(id=order_id, customer=user).first()
        if not order:
            return _err('not_found', message='سفارش پیدا نشد.')
        result = cart_svc.cancel_customer_order(order)
        if not result.get('ok'):
            return _err(
                result.get('error') or 'not_cancellable',
                message=str(result.get('message') or 'این سفارش قابل لغو نیست.'),
            )
        return JsonResponse(result if isinstance(result, dict) else {'ok': True})
    except Exception as exc:
        logger.exception('api_order_cancel')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'لغو سفارش نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def api_operator_banners(request: HttpRequest) -> JsonResponse:
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبانی.'}, status=200)
    rows = []
    for r in BannerPublishRequest.objects.filter(status='pending').select_related('customer').order_by('id')[:50]:
        rows.append({
            'id': r.id,
            'customer': r.customer.bale_user_id,
            'fee_toman': r.fee_toman,
            'caption': (r.caption or '')[:80],
        })
    return JsonResponse({'ok': True, 'requests': rows})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_banner_decide(request: HttpRequest) -> JsonResponse:
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        if not ws.is_operator(user.bale_user_id or ''):
            return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'فقط پشتیبانی.'}, status=200)
        body = _json_body(request) or {}
        try:
            rid = int(body.get('request_id') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'bad_fields', 'message': 'شناسه درخواست نامعتبر است.'}, status=200)
        r = operator_decide(rid, str(user.bale_user_id), bool(body.get('approve')))
        if not r.get('ok'):
            from bot_flow.messages import user_error
            return JsonResponse(
                {
                    'ok': False,
                    'error': r.get('error'),
                    'message': r.get('message') or ERR_FA.get(r.get('error') or '') or user_error(r.get('error')),
                },
                status=200,
            )
        return JsonResponse({'ok': True, 'message': r.get('message') or 'ثبت شد'})
    except Exception as exc:
        logger.exception('operator_banner_decide')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'تصمیم بنر ثبت نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_paid(request: HttpRequest) -> JsonResponse:
    """Build batch from pending payouts then mark paid (notifies managers)."""
    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        if not ws.is_operator(user.bale_user_id or ''):
            return _err('forbidden', message='فقط پشتیبانی.')
        body = _json_body(request) or {}
        if not body.get('confirm'):
            built = ws.build_payout_batch(user)
            if not built.get('ok'):
                return _err(
                    str(built.get('error') or 'no_pending'),
                    message='درخواست تسویه‌ای برای واریز نیست. وقتی درخواستی باز شد، دوباره بزنید.',
                )
            return JsonResponse({
                'ok': True,
                'file_text': built.get('file_text') or '',
                'count': built.get('count') or 0,
                'batch_id': built['batch'].id,
                'marked_paid': False,
            })
        try:
            batch_id = int(body.get('batch_id') or 0)
        except (TypeError, ValueError):
            return _err('bad_fields', message='شناسه دسته نامعتبر است.')
        marked = ws.mark_batch_paid(batch_id)
        if not marked.get('ok'):
            code = str(marked.get('error') or 'batch_not_found')
            if code == 'already_paid':
                return _err(code, message='این واریز قبلاً ثبت شده. نیازی به تأیید دوباره نیست.')
            return _err(code)
        return JsonResponse({
            'ok': True,
            'marked_paid': True,
            'notified': len(marked.get('notified') or []),
        })
    except Exception as exc:
        logger.exception('api_operator_paid')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'ثبت واریز نشد: ' + type(exc).__name__}, status=200)



@csrf_exempt
@require_http_methods(['POST'])
def api_order_confirm(request: HttpRequest) -> JsonResponse:
    """تأیید یا اعتراض مشتری به انتشار. وضعیت فقط از همین مسیر عوض می‌شود."""
    from integrations import bale_client as bc
    from orders.banner_publish import operator_chat_id
    from orders.execution import customer_confirm_execution

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    body = _json_body(request) or {}
    try:
        item_id = int(body.get('item_id') or 0)
    except (TypeError, ValueError):
        return _err('not_found', message='آیتم سفارش پیدا نشد.')
    accept = bool(body.get('accept'))
    result = customer_confirm_execution(item_id, str(user.bale_user_id or ''), accept)
    if not result.get('ok'):
        from miniapp.api import _with_message

        return JsonResponse(_with_message(result), status=400)
    note = str(body.get('note') or '').strip()[:240]
    if not accept and note:
        op = operator_chat_id()
        if op:
            try:
                bc.send_message(op, f'یادداشت مشتری برای نوبت {item_id}:\n{note}')
            except Exception:
                pass
    return JsonResponse({'ok': True, 'status': result.get('status') or ''})


@csrf_exempt
@require_http_methods(['POST'])
def api_order_published(request: HttpRequest) -> JsonResponse:
    """Manager marks item as published; verifies via channel history when possible."""
    from orders.publish import verify_manager_published

    try:
        user, err = _auth_user(request)
        if err:
            return err
        assert user is not None
        body = _json_body(request) or {}
        try:
            item_id = int(body.get('item_id') or 0)
        except (TypeError, ValueError):
            return _err('not_found', message='آیتم سفارش پیدا نشد.')
        result = verify_manager_published(item_id, str(user.bale_user_id or ''))
        if not result.get('ok'):
            from miniapp.api import _with_message
            payload = _with_message(result)
            if not isinstance(payload, dict):
                payload = {'ok': False, 'error': 'error', 'message': 'تأیید انتشار نشد.'}
            payload.setdefault('message', str(payload.get('error') or 'تأیید انتشار نشد.'))
            return JsonResponse(payload, status=200)
        return JsonResponse(result if isinstance(result, dict) else {'ok': True})
    except Exception as exc:
        logger.exception('api_order_published')
        return JsonResponse({'ok': False, 'error': 'server', 'message': 'تأیید انتشار نشد: ' + type(exc).__name__}, status=200)


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_resolve(request: HttpRequest) -> JsonResponse:
    from orders.execution import operator_resolve

    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return _err('forbidden', message='فقط پشتیبانی.')
    body = _json_body(request)
    try:
        item_id = int(body.get('item_id') or 0)
    except (TypeError, ValueError):
        return _err('not_found', 404)
    result = operator_resolve(item_id, str(user.bale_user_id or ''), bool(body.get('executed')))
    if not result.get('ok'):
        from miniapp.api import _with_message

        return JsonResponse(_with_message(result), status=400)
    return JsonResponse({'ok': True, 'status': result.get('status') or ''})


@csrf_exempt
@require_http_methods(['POST'])
def api_operator_refund(request: HttpRequest) -> JsonResponse:
    """بازگشت کامل یا بخشیِ سفارش پرداخت‌شده به اعتبار مشتری."""
    user, err = _auth_user(request)
    if err:
        return err
    assert user is not None
    if not ws.is_operator(user.bale_user_id or ''):
        return _err('forbidden', message='فقط پشتیبانی.')
    body = _json_body(request)
    try:
        order_id = int(body.get('order_id') or 0)
    except (TypeError, ValueError):
        return _err('not_found', 404)
    order = Order.objects.filter(id=order_id).first()
    if not order:
        return _err('not_found', 404)
    amount = body.get('amount')
    try:
        amount_i = int(amount) if amount not in (None, '') else None
    except (TypeError, ValueError):
        return _err('bad_fields')
    result = cart_svc.refund_paid_order(
        order,
        amount_i,
        reason=f'بازگشت توسط پشتیبانی، سفارش {order.id}',
    )
    if not result.get('ok'):
        return _err(result.get('error') or 'not_paid', message=str(result.get('message') or ''))
    credited = int(result.get('credited') or 0)
    return JsonResponse({
        'ok': True,
        'credited': credited,
        'full': bool(result.get('full')),
        'message': f'{credited} تومان به اعتبار مشتری برگشت.',
    })
