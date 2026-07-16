"""Celery application for durable delayed qualification jobs."""

from __future__ import annotations

import os

# Must run before Django imports sqlite3 (Celery does not go through manage.py).
from .sqlite_compat import enable_pysqlite3_fallback

enable_pysqlite3_fallback()

# redis-py 5+ defaults to RESP3; local Redis 5.x rejects HELLO.
from .redis_compat import enable_redis_resp2_fallback

enable_redis_resp2_fallback()

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("weblead")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
