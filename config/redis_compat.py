"""Redis client compatibility helpers for older Redis servers."""

from __future__ import annotations


def enable_redis_resp2_fallback() -> None:
    """
    Force redis-py onto RESP2 so Celery can talk to Redis 5.x.

    redis-py 5+ defaults to RESP3 (``HELLO 3``). Redis 5 rejects that. Forcing
    protocol=2 alone is not enough on recent redis-py builds: ConnectionPool may
    still enable maintenance notifications (``enabled="auto"``), which require a
    RESP3/hiredis parser. Disable those when applying the RESP2 fallback.
    """
    try:
        from redis.connection import Connection
        from redis.maint_notifications import MaintNotificationsConfig
    except ImportError:
        return

    if getattr(Connection.__init__, "_weblead_resp2_fallback", False):
        return

    original_init = Connection.__init__

    def _init_with_resp2(self, *args, protocol=None, **kwargs):  # type: ignore[no-untyped-def]
        if protocol is None:
            protocol = 2
        if int(protocol) == 2:
            kwargs["maint_notifications_config"] = MaintNotificationsConfig(
                enabled=False
            )
            kwargs.pop("maint_notifications_pool_handler", None)
        return original_init(self, *args, protocol=protocol, **kwargs)

    _init_with_resp2._weblead_resp2_fallback = True  # type: ignore[attr-defined]
    Connection.__init__ = _init_with_resp2  # type: ignore[method-assign]
