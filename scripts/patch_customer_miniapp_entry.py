#!/usr/bin/env python3
"""Add mini-app web_app button to customer bot home (role=customer)."""
from pathlib import Path

p = Path('bot_flow/customer.py')
t = p.read_text(encoding='utf-8')
if "miniapp_url(role='customer')" in t:
    print('already patched')
    raise SystemExit(0)

old = '''def customer_home_keyboard() -> Dict:
    return bc.inline_keyboard([
        [
            {'text': '🖼 بنرهای من', 'callback_data': 'cu:banners'},
            {'text': '➕ بنر جدید', 'callback_data': 'cu:new'},
        ],
        [
            {'text': '📋 فهرست تعرفه‌ها', 'callback_data': 'cu:catalog'},
            {'text': '🛒 انتخاب‌ها', 'callback_data': 'cu:cart'},
        ],
        [
            {'text': '📦 سفارش‌های من', 'callback_data': 'cu:orders'},
            {'text': '💰 کیف پول', 'callback_data': 'cu:wallet'},
        ],
        [{'text': '🔄 تعویض نقش', 'callback_data': 'nav:start'}],
    ])'''

new = '''def customer_home_keyboard() -> Dict:
    from miniapp.launch import miniapp_url

    rows: List[List[Dict[str, object]]] = []
    url = miniapp_url(role='customer')
    if url:
        rows.append([{'text': 'باز کردن لینک‌بان', 'web_app': {'url': url}}])
    rows.extend([
        [
            {'text': '🖼 بنرهای من', 'callback_data': 'cu:banners'},
            {'text': '➕ بنر جدید', 'callback_data': 'cu:new'},
        ],
        [
            {'text': '📋 فهرست تعرفه‌ها', 'callback_data': 'cu:catalog'},
            {'text': '🛒 انتخاب‌ها', 'callback_data': 'cu:cart'},
        ],
        [
            {'text': '📦 سفارش‌های من', 'callback_data': 'cu:orders'},
            {'text': '💰 کیف پول', 'callback_data': 'cu:wallet'},
        ],
        [{'text': '🔄 تعویض نقش', 'callback_data': 'nav:start'}],
    ])
    return bc.inline_keyboard(rows)'''

if old not in t:
    raise SystemExit('keyboard block not found — file may have changed')
t = t.replace(old, new, 1)

old2 = "        'اول بنر را بفرستید، بعد یک روز خالی بردارید.'\n    )\n    bc.send_message(str(chat_id), text, reply_markup=customer_home_keyboard())"
new2 = (
    "        'اول بنر را بفرستید، بعد یک روز خالی بردارید.\\n'\n"
    "        'برای کار راحت‌تر، «باز کردن لینک‌بان» را بزنید.'\n"
    "    )\n"
    "    bc.send_message(str(chat_id), text, reply_markup=customer_home_keyboard())"
)
if old2 in t:
    t = t.replace(old2, new2, 1)
else:
    print('home text block skipped (already different)')

p.write_text(t, encoding='utf-8')
print('patched', p)
