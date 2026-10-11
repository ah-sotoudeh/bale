# مینی‌اپ لینک‌بانک

پس از `git pull` روی سی‌پنل:

1. `passenger_wsgi.py` و `.env` دست نزنید.
2. `MINIAPP_BASE_URL=https://bale.taiyebestan.ir`
3. وب‌اپ: `/miniapp/` برای هر سه نقش (مدیر / مشتری / پشتیبانی) بر اساس شناسه تشخیص داده می‌شود.
4. تست مرورگر: `/miniapp/?debug_bale_id=80619262` فقط اگر `ALLOW_MINIAPP_DEBUG=1`.

قابلیت‌ها:
- پنل مدیر: کانال، نحوه ارسال، تعرفه، تقویم شمسی ۱۴ روزه، نوبت دستی، سفارش، کیف پول
- پنل مشتری: بنر، فهرست، روز خالی، سبد، تسویه
- پنل پشتیبانی: تأیید بنر، فایل تسویه ریالی بانک، ثبت پایا

## حالت دمو (بدون بله)

```
/miniapp/?demo=1&role=customer
/miniapp/?demo=1&role=manager
/miniapp/?demo=1&role=operator
```

- برای مدیر دمو کانال و تعرفه نمونه ساخته می‌شود.
- در پروداکشن می‌توانید `DEMO_MINIAPP=0` بگذارید و دسترسی دمو را محدود کنید (فعلاً با `?demo=1` فعال است).
- نوار پایین صفحه نقش دمو را عوض می‌کند.

### Pipeline سفارش
`waiting_banner → waiting_managers → waiting_customer_confirm → waiting_payment → paid → completed`

### تأیید ماندن پست
`bot_flow/post_verify.py` — `flag_item_if_missing(order_item_id)`
