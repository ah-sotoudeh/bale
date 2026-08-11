"""پنل مدیر کانال — منوی اصلی و زیربخش‌ها.

بخش‌ها:
  • کانال‌ها / مجموعه‌ها + حالت انتشار
  • تعرفه‌ها
  • فهرست سفارش‌ها
  • تقویم روزهای خالی
  • اعلام روز پر (خارج از سیستم)
  • مالی: موجودی، شبا، درخواست تسویه
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from bot_flow.jalali import format_jalali, to_jalali
from channels_app.models import Channel, ChannelGroup, Tariff
from integrations import bale_client as bc
from orders.availability import mark_external_busy
from orders.models import OrderItem
from users.models import BotSession, User
from wallet import services as ws
from wallet.models import BankAccount, PayoutRequest

logger = logging.getLogger(__name__)

STATE_MGR_BANK_IBAN = 'mgr_bank_iban'
STATE_MGR_BANK_HOLDER = 'mgr_bank_holder'
STATE_MGR_BUSY_DATE = 'mgr_busy_date'
STATE_MGR_TARIFF = 'mgr_add_tariff'

JALALI_DATE = re.compile(
    r'^\s*(\d{3,4})[\-/](\d{1,2})[\-/](\d{1,2})\s*$'
)


def _sess(bale_user_id: str) -> BotSession:
    s, _ = BotSession.objects.get_or_create(
        bale_user_id=str(bale_user_id), defaults={'state': 'idle', 'data': {}}
    )
    return s


def _save(sess: BotSession, state: Optional[str] = None, **updates) -> None:
    if state is not None:
        sess.state = state
    if updates:
        d = dict(sess.data or {})
        d.update(updates)
        sess.data = d
    sess.save()


def _ensure_user(bale_user_id: str, username: str = '') -> User:
    from bot_flow.handlers import ensure_user

    return ensure_user(bale_user_id, username)


def main_keyboard(is_operator: bool = False) -> Dict[str, Any]:
    rows = [
        [
            {'text': '📢 کانال‌ها', 'callback_data': 'mgr:channels'},
            {'text': '💳 تعرفه‌ها', 'callback_data': 'mgr:tariffs'},
        ],
        [
            {'text': '📋 سفارش‌ها', 'callback_data': 'mgr:orders'},
            {'text': '📅 تقویم', 'callback_data': 'mgr:calendar'},
        ],
        [
            {'text': '🔒 روز پر', 'callback_data': 'mgr:busy'},
            {'text': '💰 مالی', 'callback_data': 'mgr:wallet'},
        ],
        [
            {'text': '⚙️ حالت انتشار', 'callback_data': 'pmode_edit:start'},
            {'text': '➕ ثبت کانال', 'callback_data': 'mgr:add_channel'},
        ],
    ]
    if is_operator:
        rows.append([
            {'text': '📁 فایل تسویه (اپراتور)', 'callback_data': 'mgr:op_payout_file'},
        ])
    rows.append([{'text': '🏠 خانه', 'callback_data': 'mgr:home'}])
    return bc.inline_keyboard(rows)


def open_panel(chat_id: str, bale_user_id: str, username: str = '') -> None:
    user = _ensure_user(bale_user_id, username)
    bal = ws.available_balance(user)
    n_ch = Channel.objects.filter(manager=user).count()
    n_pending = OrderItem.objects.filter(
        manager=user, manager_status='pending'
    ).count()
    text = (
        '🎛️ *پنل مدیر کانال*\n\n'
        f'آیدی: {user.bale_handle or user.bale_user_id}\n'
        f'کانال‌ها: {n_ch}\n'
        f'سفارش در انتظار: {n_pending}\n'
        f'موجودی قابل برداشت: {bal:,} تومان\n\n'
        'یک گزینه را انتخاب کنید:'
    )
    bc.send_message(
        str(chat_id),
        text,
        reply_markup=main_keyboard(is_operator=ws.is_operator(bale_user_id)),
    )


# ── کانال‌ها ──────────────────────────────────────────────

def show_channels(chat_id: str, user: User) -> None:
    channels = list(Channel.objects.filter(manager=user).order_by('id')[:30])
    groups = list(ChannelGroup.objects.filter(manager=user).order_by('id')[:15])
    if not channels and not groups:
        bc.send_message(
            str(chat_id),
            'هنوز کانالی ندارید.\nاز «ثبت کانال» شروع کنید.',
            reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
        )
        return
    lines = ['📢 کانال‌های شما:']
    for ch in channels:
        mode = ch.publish_mode_label
        lines.append(
            f'• {ch.name} ({ch.link or "—"})\n'
            f'  حالت: {mode} | تعرفه: {ch.tariffs.count()}'
        )
    if groups:
        lines.append('\n📦 مجموعه‌ها:')
        for g in groups:
            lines.append(f'• {g.name} ({g.channel_count} کانال) — تعرفه: {g.tariffs.count()}')
    bc.send_message(
        str(chat_id),
        '\n'.join(lines),
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )


# ── تعرفه‌ها ──────────────────────────────────────────────

def show_tariffs(chat_id: str, user: User) -> None:
    tariffs = list(
        Tariff.objects.filter(
            models_q_manager(user)
        ).select_related('channel', 'group').order_by('-id')[:40]
    )
    if not tariffs:
        bc.send_message(str(chat_id), 'تعرفه‌ای ثبت نشده. ابتدا کانال ثبت کنید.')
        return
    lines = ['💳 تعرفه‌ها:']
    rows = []
    for t in tariffs:
        owner = t.group.name if t.group_id else (t.channel.name if t.channel_id else '?')
        hour = f'{t.start_hour:02d}:00' if t.start_hour is not None else '—'
        active = '✅' if t.is_active else '⏸'
        lines.append(
            f'{active} #{t.id} {owner} | {t.name} | {hour} | {t.duration_hours}س | {t.price:,} ت'
        )
    # quick add on first channel
    ch = Channel.objects.filter(manager=user).order_by('id').first()
    if ch:
        rows.append([{'text': f'➕ تعرفه برای {ch.name[:20]}', 'callback_data': f'mgr:addtariff:{ch.id}'}])
    rows.append([{'text': '🏠 خانه', 'callback_data': 'mgr:home'}])
    bc.send_message(str(chat_id), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows))


def models_q_manager(user: User):
    from django.db.models import Q

    return Q(channel__manager=user) | Q(group__manager=user)


def start_add_tariff(chat_id: str, user: User, channel_id: int) -> None:
    ch = Channel.objects.filter(id=channel_id, manager=user).first()
    if not ch:
        bc.send_message(str(chat_id), 'کانال یافت نشد.')
        return
    sess = _sess(user.bale_user_id or '')
    _save(sess, STATE_MGR_TARIFF, tariff_channel_id=ch.id)
    bc.send_message(
        str(chat_id),
        f'تعرفه جدید برای «{ch.name}»:\n'
        f'فرمت: نام | ساعت_شروع | مدت_ساعت | قیمت_تومان\n'
        f'مثال: روزانه | 10 | 24 | 50000\n'
        f'یا بدون ساعت: روزانه | 24 | 50000',
    )


def handle_tariff_line(chat_id: str, user: User, text: str) -> bool:
    sess = _sess(user.bale_user_id or '')
    if sess.state != STATE_MGR_TARIFF:
        return False
    ch_id = (sess.data or {}).get('tariff_channel_id')
    ch = Channel.objects.filter(id=ch_id, manager=user).first()
    if not ch:
        _save(sess, 'idle')
        bc.send_message(str(chat_id), 'کانال نامعتبر.')
        return True

    parts = [p.strip() for p in re.split(r'[|،,]', text) if p.strip()]
    start_hour = None
    try:
        if len(parts) == 4:
            name, sh, dur, price = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
            start_hour = sh
        elif len(parts) == 3:
            name, dur, price = parts[0], int(parts[1]), int(parts[2])
        else:
            bc.send_message(str(chat_id), 'فرمت نامعتبر. مثال: روزانه | 10 | 24 | 50000')
            return True
    except ValueError:
        bc.send_message(str(chat_id), 'اعداد نامعتبر.')
        return True

    t = Tariff.objects.create(
        channel=ch,
        name=name[:100],
        start_hour=start_hour,
        duration_hours=dur,
        price=price,
        is_active=True,
    )
    _save(sess, 'idle')
    bc.send_message(
        str(chat_id),
        f'✅ تعرفه #{t.id} ذخیره شد: {t.name} — {t.price:,} تومان',
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )
    return True


# ── سفارش‌ها ──────────────────────────────────────────────

def show_orders(chat_id: str, user: User) -> None:
    items = list(
        OrderItem.objects.filter(manager=user)
        .select_related('order', 'channel', 'tariff', 'tariff__group', 'order__customer')
        .order_by('-id')[:25]
    )
    if not items:
        bc.send_message(str(chat_id), 'سفارشی نیست.', reply_markup=main_keyboard())
        return
    lines = ['📋 سفارش‌های اخیر:']
    for it in items:
        owner = (
            it.tariff.group.name
            if it.tariff.group_id
            else (it.channel.name if it.channel else '?')
        )
        start = it.effective_start
        start_s = format_jalali(timezone.localtime(start).date()) if start else '—'
        lines.append(
            f'#{it.id} | سفارش {it.order_id} | {owner}\n'
            f'  مدیر:{it.manager_status} | اجرا:{it.execution_status}\n'
            f'  {start_s} | {it.price:,} ت'
        )
    bc.send_message(
        str(chat_id),
        '\n'.join(lines)[:3900],
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )


# ── تقویم ────────────────────────────────────────────────

def show_calendar_entry(chat_id: str, user: User) -> None:
    from bot_flow.calendar_ui import send_manager_channel_picker

    send_manager_channel_picker(chat_id, user)


# ── روز پر ───────────────────────────────────────────────

def start_busy_flow(chat_id: str, user: User) -> None:
    channels = list(Channel.objects.filter(manager=user).order_by('name')[:20])
    groups = list(ChannelGroup.objects.filter(manager=user).order_by('name')[:10])
    rows = []
    for ch in channels:
        rows.append([{'text': f'📢 {ch.name}', 'callback_data': f'mgr:busy_ch:{ch.id}'}])
    for g in groups:
        rows.append([{'text': f'📦 {g.name}', 'callback_data': f'mgr:busy_g:{g.id}'}])
    if not rows:
        bc.send_message(str(chat_id), 'کانالی نیست.')
        return
    rows.append([{'text': '🏠 خانه', 'callback_data': 'mgr:home'}])
    bc.send_message(
        str(chat_id),
        'برای کدام کانال/مجموعه روز پر اعلام می‌کنید؟',
        reply_markup=bc.inline_keyboard(rows),
    )


def ask_busy_date(chat_id: str, user: User, *, channel_id=None, group_id=None) -> None:
    sess = _sess(user.bale_user_id or '')
    _save(
        sess,
        STATE_MGR_BUSY_DATE,
        busy_channel_id=channel_id,
        busy_group_id=group_id,
    )
    bc.send_message(
        str(chat_id),
        'تاریخ شمسی روز پر را بفرستید:\n'
        'مثال: 1405/05/20\n'
        '(کل آن روز برای همه تعرفه‌های این هدف مسدود می‌شود)',
    )


def _jalali_to_gregorian(jy: int, jm: int, jd: int):
    try:
        import jdatetime

        return jdatetime.date(jy, jm, jd).togregorian()
    except Exception:
        # rough fallback via pure python inverse is heavy; require jdatetime
        return None


def handle_busy_date_text(chat_id: str, user: User, text: str) -> bool:
    sess = _sess(user.bale_user_id or '')
    if sess.state != STATE_MGR_BUSY_DATE:
        return False
    m = JALALI_DATE.match(text or '')
    if not m:
        bc.send_message(str(chat_id), 'فرمت: 1405/05/20')
        return True
    jy, jm, jd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    gday = _jalali_to_gregorian(jy, jm, jd)
    if not gday:
        bc.send_message(str(chat_id), 'تاریخ نامعتبر (jdatetime لازم است).')
        return True

    data = sess.data or {}
    ch = None
    group = None
    if data.get('busy_channel_id'):
        ch = Channel.objects.filter(id=data['busy_channel_id'], manager=user).first()
    if data.get('busy_group_id'):
        group = ChannelGroup.objects.filter(id=data['busy_group_id'], manager=user).first()
    if not ch and not group:
        _save(sess, 'idle')
        bc.send_message(str(chat_id), 'هدف نامعتبر.')
        return True

    start = timezone.make_aware(datetime.combine(gday, dtime(0, 0)))
    end = start + timedelta(days=1)
    slot = mark_external_busy(
        start,
        end,
        channel=ch,
        group=group,
        note='رزرو خارج از سیستم (پنل مدیر)',
    )
    _save(sess, 'idle')
    label = ch.name if ch else group.name
    bc.send_message(
        str(chat_id),
        f'🔒 روز {format_jalali(gday)} برای «{label}» پر ثبت شد (#{slot.id}).',
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )
    return True


# ── مالی ─────────────────────────────────────────────────

def show_wallet(chat_id: str, user: User) -> None:
    br = ws.balance_breakdown(user)
    pending = list(
        PayoutRequest.objects.filter(user=user, status='pending').order_by('-id')[:5]
    )
    banks = list(BankAccount.objects.filter(user=user).order_by('-is_default', '-id')[:10])
    lines = [
        '💰 کیف پول مدیر',
        f'قابل برداشت: {br["available"]:,} تومان',
        f'در انتظار تسویه: {br["locked_pending"]:,} تومان',
        f'تسویه‌شده (مجموع): {br["paid_out"]:,} تومان',
        f'حداقل تسویه: {ws.MIN_PAYOUT_TOMAN:,} تومان | سقف هفتگی: یک‌بار',
        f'کارمزد پلتفرم: {ws.PLATFORM_FEE_PERCENT}%',
        '',
        'شباهای ثبت‌شده:' if banks else 'شبا ثبت نشده.',
    ]
    for b in banks:
        star = '⭐' if b.is_default else '•'
        lines.append(f'{star} {b.holder_name} — ...{b.iban[-6:]}')
    if pending:
        lines.append('\nدرخواست‌های باز:')
        for p in pending:
            lines.append(f'• #{p.id} {p.amount_toman:,} ت → ...{p.iban[-6:]}')

    rows = [
        [{'text': '➕ افزودن شبا', 'callback_data': 'mgr:bank_add'}],
        [{'text': '💸 درخواست تسویه', 'callback_data': 'mgr:payout'}],
        [{'text': '🏠 خانه', 'callback_data': 'mgr:home'}],
    ]
    bc.send_message(str(chat_id), '\n'.join(lines), reply_markup=bc.inline_keyboard(rows))


def start_bank_add(chat_id: str, user: User) -> None:
    sess = _sess(user.bale_user_id or '')
    _save(sess, STATE_MGR_BANK_IBAN)
    bc.send_message(
        str(chat_id),
        'شماره شبا را بفرستید (با IR و ۲۴ رقم):\nمثال: IR120170000000123456789001',
    )


def handle_bank_iban(chat_id: str, user: User, text: str) -> bool:
    sess = _sess(user.bale_user_id or '')
    if sess.state != STATE_MGR_BANK_IBAN:
        return False
    iban = (text or '').replace(' ', '').upper()
    if not ws.validate_iban(iban):
        bc.send_message(str(chat_id), 'شبا نامعتبر است. دوباره بفرستید.')
        return True
    _save(sess, STATE_MGR_BANK_HOLDER, pending_iban=iban)
    bc.send_message(str(chat_id), 'نام صاحب حساب را دقیقاً مطابق کارت/شبا بفرستید:')
    return True


def handle_bank_holder(chat_id: str, user: User, text: str) -> bool:
    sess = _sess(user.bale_user_id or '')
    if sess.state != STATE_MGR_BANK_HOLDER:
        return False
    iban = (sess.data or {}).get('pending_iban') or ''
    holder = (text or '').strip()
    try:
        acc = ws.save_bank_account(user, iban, holder, make_default=True)
    except ValueError as e:
        bc.send_message(str(chat_id), f'خطا: {e}')
        return True
    _save(sess, 'idle')
    bc.send_message(
        str(chat_id),
        f'✅ شبا ذخیره شد: {acc.holder_name} — ...{acc.iban[-6:]}',
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )
    return True


def start_payout(chat_id: str, user: User) -> None:
    ok, reason = ws.can_request_payout(user)
    if not ok:
        msg = {
            'already_pending': 'یک درخواست تسویه باز دارید.',
            'weekly_limit': 'سقف هفتگی: بعد از تسویه قبلی حداقل ۷ روز صبر کنید.',
            'below_minimum': f'موجودی کمتر از حداقل ({ws.MIN_PAYOUT_TOMAN:,} تومان) است.',
            'no_bank': 'ابتدا شبا ثبت کنید.',
        }.get(reason, reason)
        bc.send_message(str(chat_id), f'❌ {msg}')
        return
    banks = list(BankAccount.objects.filter(user=user).order_by('-is_default', '-id'))
    avail = ws.available_balance(user)
    rows = [
        [{
            'text': f'{"⭐ " if b.is_default else ""}{b.holder_name} ...{b.iban[-6:]}',
            'callback_data': f'mgr:payout_bank:{b.id}',
        }]
        for b in banks
    ]
    rows.append([{'text': 'لغو', 'callback_data': 'mgr:wallet'}])
    bc.send_message(
        str(chat_id),
        f'مبلغ قابل برداشت: {avail:,} تومان\nشبای مقصد را انتخاب کنید:',
        reply_markup=bc.inline_keyboard(rows),
    )


def confirm_payout(chat_id: str, user: User, bank_id: int) -> None:
    bank = BankAccount.objects.filter(id=bank_id, user=user).first()
    if not bank:
        bc.send_message(str(chat_id), 'شبا یافت نشد.')
        return
    r = ws.request_payout(user, bank)
    if not r.get('ok'):
        bc.send_message(str(chat_id), f'❌ {r.get("error")}')
        return
    pr = r['payout']
    bc.send_message(
        str(chat_id),
        f'✅ درخواست تسویه #{pr.id} ثبت شد.\n'
        f'{pr.amount_toman:,} تومان → {pr.holder_name}\n'
        f'پس از پرداخت بانک، پیام پایا برایتان می‌آید.',
        reply_markup=main_keyboard(ws.is_operator(user.bale_user_id or '')),
    )


def operator_payout_file(chat_id: str, user: User) -> None:
    if not ws.is_operator(user.bale_user_id or ''):
        bc.send_message(str(chat_id), 'فقط اپراتور.')
        return
    r = ws.build_payout_batch(user)
    if not r.get('ok'):
        bc.send_message(str(chat_id), f'❌ {r.get("error")}')
        return
    batch = r['batch']
    body = r['file_text'] or ''
    bc.send_message(
        str(chat_id),
        f'📁 Batch #{batch.id} — {r["count"]} درخواست\nمبالغ به ریال:\n{body[:3500]}',
    )
    bc.send_message(
        str(chat_id),
        f'پس از واریز بانک دکمه را بزنید:',
        reply_markup=bc.inline_keyboard([
            [{'text': '✅ پرداخت انجام شد', 'callback_data': f'mgr:op_paid:{batch.id}'}]
        ]),
    )


# ── router ───────────────────────────────────────────────

def try_handle_callback(
    chat_id: str,
    bale_user_id: str,
    data: str,
    cq_id: Optional[str] = None,
    username: str = '',
) -> bool:
    if not data.startswith('mgr:'):
        return False
    if cq_id:
        bc.answer_callback_query(str(cq_id))

    user = _ensure_user(bale_user_id, username)

    if data in ('mgr:home', 'mgr:panel'):
        open_panel(chat_id, bale_user_id, username)
        return True
    if data == 'mgr:channels':
        show_channels(chat_id, user)
        return True
    if data == 'mgr:tariffs':
        show_tariffs(chat_id, user)
        return True
    if data == 'mgr:orders':
        show_orders(chat_id, user)
        return True
    if data == 'mgr:calendar':
        show_calendar_entry(chat_id, user)
        return True
    if data == 'mgr:busy':
        start_busy_flow(chat_id, user)
        return True
    if data.startswith('mgr:busy_ch:'):
        ask_busy_date(chat_id, user, channel_id=int(data.split(':')[2]))
        return True
    if data.startswith('mgr:busy_g:'):
        ask_busy_date(chat_id, user, group_id=int(data.split(':')[2]))
        return True
    if data == 'mgr:wallet':
        show_wallet(chat_id, user)
        return True
    if data == 'mgr:bank_add':
        start_bank_add(chat_id, user)
        return True
    if data == 'mgr:payout':
        start_payout(chat_id, user)
        return True
    if data.startswith('mgr:payout_bank:'):
        confirm_payout(chat_id, user, int(data.split(':')[2]))
        return True
    if data == 'mgr:add_channel':
        from bot_flow import handlers as flow

        sess = _sess(bale_user_id)
        flow.save_session(sess, flow.STATE_AWAIT_LINKS, role='manager', verified_ids=[])
        proof = user.bale_handle or user.bale_user_id
        bc.send_message(
            str(chat_id),
            'لینک کانال‌ها را بفرستید (هر خط یکی).\n'
            f'آیدی در بیو: {proof}',
        )
        return True
    if data.startswith('mgr:addtariff:'):
        start_add_tariff(chat_id, user, int(data.split(':')[2]))
        return True
    if data == 'mgr:op_payout_file':
        operator_payout_file(chat_id, user)
        return True
    if data.startswith('mgr:op_paid:'):
        if not ws.is_operator(bale_user_id):
            bc.send_message(str(chat_id), 'فقط اپراتور.')
            return True
        r = ws.mark_batch_paid(int(data.split(':')[2]))
        bc.send_message(str(chat_id), '✅ ثبت شد' if r.get('ok') else f'❌ {r.get("error")}')
        return True
    return False


def try_handle_text(chat_id: str, bale_user_id: str, text: str, username: str = '') -> bool:
    norm = (text or '').strip()
    if not norm:
        return False
    if norm in ('/panel', '/mgr', '/مدیر', 'پنل'):
        open_panel(chat_id, bale_user_id, username)
        return True

    user = _ensure_user(bale_user_id, username)
    if handle_bank_iban(chat_id, user, norm):
        return True
    if handle_bank_holder(chat_id, user, norm):
        return True
    if handle_busy_date_text(chat_id, user, norm):
        return True
    if handle_tariff_line(chat_id, user, norm):
        return True
    return False
