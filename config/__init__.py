"""Django project package; load Celery app for `celery -A config` workers."""

from .sqlite_compat import enable_pysqlite3_fallback

enable_pysqlite3_fallback()

from .celery import app as celery_app

__all__ = ("celery_app",)
