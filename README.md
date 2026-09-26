# لینک‌بانک — وب‌اپ پایتون روی سی‌پنل

## سی‌پنل
1. Python App بسازید. نسخه ۳.۱۰ یا جدیدتر. ریشهٔ برنامه همین پوشه.
2. Startup file: `passenger_wsgi.py` و callable: `application`.
3. `pip install -r requirements.txt` سپس `python manage.py migrate`.
4. در Environment Variables این‌ها را بگذارید: `DJANGO_SECRET_KEY`، `BALE_BOT_TOKEN`، `BALE_PROVIDER_TOKEN` (توکن کیف‌پول از @botfather)، `BALE_TOKEN` (حساب لینک‌یار، برای آمار کانال)، `MINIAPP_BASE_URL=https://دامنه-شما` ، و اگر MySQL دارید `USE_SQLITE=0` به‌همراه `DB_*`.
5. دامنه باید HTTPS روی پورت ۴۴۳ باشد. بله وب‌هوک را فقط روی ۴۴۳ یا ۸۸ می‌فرستد.

## اتصال بازو
روی میزبان فعلی دیوار آتش ممکن است POST وب‌هوک بله را ببندد. مسیر عملیاتی لانگ‌پولینگ است:

```bash
python scripts/poll_bot.py
```

کد وب‌هوک هم هست، اگر مسیر POST باز باشد:

```bash
python scripts/set_webhook.py
```

آدرس ثبت‌شده: `https://دامنه/bot/webhook/`. اگر `WEBHOOK_SECRET` پر باشد، اسکریپت `?token=` را خودش اضافه می‌کند.

هر دو مسیر از `bot_flow.dispatch.handle_update` می‌گذرند.

## آمار کانال
حساب لینک‌یار با `BALE_TOKEN` تعداد عضو و بازدید کانال‌های تعرفه را می‌خواند. مدیر این عددها را وارد نمی‌کند. بعد از `python manage.py migrate` جدول عکس‌های آماری ساخته می‌شود. `python scripts/run_jobs_once.py` کانال‌هایی را که بیش از شش ساعت از آخرین برداشتشان گذشته تازه می‌کند، به شرطی که `BALE_TOKEN` تنظیم شده باشد.

## مینی‌اپ
دکمهٔ `web_app` مینی‌اپ را روی `MINIAPP_BASE_URL/miniapp/` باز می‌کند. اسکریپت رسمی `https://tapi.bale.ai/miniapp.js?3` در صفحه است. تم از `themeParams` و `colorScheme` بله می‌آید (روشن و تاریک). بیرون از بله دکمهٔ «تغییر تم» هست.

رابط تازه‌تر سه نقش، از جمله صفحهٔ پشتیبانی «اتصال لینک‌یار»، در پوشهٔ `simulator/` است. دادهٔ آن دمو است و با `git pull` روی سی‌پنل جایگزین `miniapp/static` نمی‌شود.

## درگاه کیف‌پول بله
مبالغ داخل سامانه به تومان است و به ریال (×۱۰) به بله فرستاده می‌شود.

- داخل گفتگو: `sendInvoice`
- داخل مینی‌اپ: `createInvoiceLink` و سپس `Bale.WebApp.openInvoice` با همان مقدار، بدون تغییر
- قبل از قطعی شدن پول، آپدیت `pre_checkout_query` حداکثر تا ۱۰ ثانیه با `answerPreCheckoutQuery` جواب داده می‌شود
- فقط آپدیت `successful_payment` سفارش را پرداخت‌شده می‌کند
