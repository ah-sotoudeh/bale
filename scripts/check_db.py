#!/usr/bin/env python3
"""Simple DB connection check used by CI.
Exits non-zero if Django cannot connect to the default DB.
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')
try:
    import django
    django.setup()
    from django.db import connections
    connections['default'].cursor()
    print('DB OK')
except Exception as e:
    print('DB connection failed:', e)
    sys.exit(1)
