"""Django project package."""

from .sqlite_compat import enable_pysqlite3_fallback

enable_pysqlite3_fallback()
