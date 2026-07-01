"""WSGI entrypoint."""

import os

from config.sqlite_compat import enable_pysqlite3_fallback

enable_pysqlite3_fallback()

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
