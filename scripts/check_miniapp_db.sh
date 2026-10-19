#!/bin/bash
# روی سرور بعد از git pull:
cd "$(dirname "$0")/.."
python manage.py migrate channels_app --noinput
python manage.py migrate orders --noinput
python manage.py migrate --noinput
echo "migrate done"
