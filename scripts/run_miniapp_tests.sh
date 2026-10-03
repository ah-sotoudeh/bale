#!/usr/bin/env bash
# تست‌های black-box مینی‌اپ (پرداخت، publish_due، گزارش مالی، نقش‌ها)
set -euo pipefail
cd "$(dirname "$0")/.."
export USE_SQLITE="${USE_SQLITE:-1}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-bale_site.settings}"
echo "→ miniapp.tests_pay + miniapp.tests_api"
python manage.py test miniapp.tests_pay miniapp.tests_api -v 2 "$@"
