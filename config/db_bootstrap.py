"""Ensure database schema exists (needed for Vercel SQLite cold starts)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("apps.qualification")


def ensure_database_schema() -> None:
    """
    Run migrations when using SQLite on Vercel.

    Vercel serverless uses an ephemeral ``/tmp`` SQLite file that is empty on
    every cold start, so tables must be created at process boot. Postgres
    deployments should migrate in CI/deploy; opt in with DJANGO_MIGRATE_ON_STARTUP.
    """
    from django.conf import settings
    from django.core.management import call_command

    engine = str(settings.DATABASES.get("default", {}).get("ENGINE", ""))
    is_sqlite = "sqlite3" in engine
    force = os.getenv("DJANGO_MIGRATE_ON_STARTUP", "").lower() == "true"
    on_vercel = os.getenv("VERCEL") == "1"

    if not (force or (on_vercel and is_sqlite)):
        return

    try:
        call_command("migrate", run_syncdb=True, verbosity=0)
        logger.info(
            '{"event":"database_migrate_on_startup","engine":"%s","vercel":%s}',
            engine,
            "true" if on_vercel else "false",
        )
    except Exception:
        logger.exception(
            '{"event":"database_migrate_on_startup_failed"}',
        )
        raise
