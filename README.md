# Bale ads-bot (initial skeleton)

این شاخه اسکلت اولیه پروژهٔ تبلیغات (بازوی بله) را شامل می‌شود.

نکات سریع برای راه‌اندازی روی cPanel:
- Python 3.10+ را انتخاب کنید و virtualenv بسازید.
- قبل از اجرای migrate، متغیرهای محیطی زیر را ست کنید (در تنظیمات سرویس یا فایل .env که در .gitignore قرار دارد):
  - DJANGO_SECRET_KEY
  - DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
  - BALE_BOT_TOKEN (توکن بازوی بله)
  - BALE_CARD_NUMBER (شماره کارت تستی)
- نصب وابستگی‌ها: pip install -r requirements.txt
- اجرای مهاجرت‌ها: python manage.py migrate
- ایجاد سوپر یوزر: python manage.py createsuperuser
- اجرای سرور (برای تست): python manage.py runserver

امنیت: به دلایل امنیتی، توکن‌ها و شماره کارت را در مخزن عمومی قرار ندهید. از GitHub Secrets یا فایل .env در سرور استفاده کنید.
