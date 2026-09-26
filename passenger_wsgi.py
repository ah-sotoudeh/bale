"""cPanel Python app entry. Application startup file: passenger_wsgi.py — callable: application."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bale_site.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
