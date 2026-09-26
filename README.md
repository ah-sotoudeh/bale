# لینک‌بانک — وب‌اپ پایتون روی سی‌پنل

## سی‌پنل
1. Python App بسازید. نسخه ۳.۱۰ یا جدیدتر. ریشهٔ برنامه همین پوشه.
2. Startup file: `passenger_wsgi.py` و callable: `application`.
3. `pip install -r requirements.txt` سپس `python manage.py migrate`.
4. در Environment Variables این‌ها را بگذارید: `DJANGO_SECRET_KEY`، `BALE_BOT_TOKEN`، `BALE_PROVIDER_TOKEN` (توکن کیف‌پول از @botfather)، `MINIAPP_BASE_URL=https://دامنه-شما` ، و اگر MySQL دارید `USE_SQLITE=0` به‌همراه `DB_*`.
5. دامنه باید HTTPS روی پورت ۴۴۳ باشد. بله وب‌هوک را فقط روی ۴۴۳ یا ۸۸ می‌فرستد.

## اتصال بازو
وب‌هوک (پیشنهادی روی سی‌پنل):

```bash
python scripts/set_webhook.py
```

آدرس ثبت‌شده: `https://دامنه/bot/webhook/`. اگر `WEBHOOK_SECRET` پر باشد، اسکریپت `?token=` را خودش اضافه می‌کند.

لانگ‌پولینگ فقط وقتی وب‌هوک ممکن نیست و یک پروسهٔ دائمی دارید:

```bash
python scripts/poll_bot.py
```

هر دو مسیر از `bot_flow.dispatch.handle_update` می‌گذرند.

## مینی‌اپ
دکمهٔ `web_app` مینی‌اپ را روی `MINIAPP_BASE_URL/miniapp/` باز می‌کند. اسکریپت رسمی `https://tapi.bale.ai/miniapp.js?3` در صفحه است. تم از `themeParams` و `colorScheme` بله می‌آید (روشن و تاریک). بیرون از بله دکمهٔ «تغییر تم» هست.

## درگاه کیف‌پول بله
مبالغ داخل سامانه به تومان است و به ریال (×۱۰) به بله فرستاده می‌شود.

- داخل گفتگو: `sendInvoice`
- داخل مینی‌اپ: `createInvoiceLink` و سپس `Bale.WebApp.openInvoice` با همان مقدار، بدون تغییر
- قبل از قطعی شدن پول، آپدیت `pre_checkout_query` حداکثر تا ۱۰ ثانیه با `answerPreCheckoutQuery` جواب داده می‌شود
- فقط آپدیت `successful_payment` سفارش را پرداخت‌شده می‌کند


