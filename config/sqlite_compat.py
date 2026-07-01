"""Use pysqlite3 when the interpreter's built-in sqlite3 module is unavailable."""

from __future__ import annotations

import sys


def enable_pysqlite3_fallback() -> None:
    try:
        if "sqlite3" in sys.modules:
            sys.modules["sqlite3"].connect(":memory:").close()
            return
        import sqlite3

        sqlite3.connect(":memory:").close()
        return
    except Exception:
        sys.modules.pop("sqlite3", None)

    try:
        import pysqlite3
    except ImportError:
        return

    sys.modules["sqlite3"] = pysqlite3
