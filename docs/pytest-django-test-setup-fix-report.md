# Pytest-Django Test Setup Fix Report

## Root Cause
- **ROS plugin conflict:** This machine has ROS Foxy pytest plugins installed under `/opt/ros/foxy/lib/python3.8/site-packages/`. Running plain `pytest` autoloads those plugins into Python 3.11 and fails with `AttributeError: module 'asyncio' has no attribute 'coroutine'` before project tests start.
- **Unsafe conftest import:** Root `conftest.py` called `django.setup()` and `call_command("migrate", …)` at module import time. With `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and explicit `-p pytest_django.plugin`, pytest-django had not yet unblocked database access when `conftest.py` was imported, causing `RuntimeError: Database access not allowed`.

## Files Inspected
| File | Finding |
|---|---|
| `conftest.py` | Had import-time `django.setup()`, `call_command("migrate")`, `pytest_plugins`, and a custom read-only `settings` fixture |
| `pytest.ini` | Sets `DJANGO_SETTINGS_MODULE = config.settings_test`, registers `language_gate` marker |
| `pyproject.toml` | Not present |
| `setup.cfg` | Not present |
| `tox.ini` | Not present |
| `config/settings_test.py` | Imports from `settings.py`; uses in-memory SQLite |
| `config/settings.py` | Production settings; no test-specific pytest hooks |
| `requirements.txt` | Declares `pytest>=8.0.0` and `pytest-django>=4.8.0` |
| `requirements-dev.txt` | Not present |
| `Makefile` | Had canonical test target but used `-p pytest_django` (incomplete entry point) |
| Other `conftest.py` files | None (root only) |

## Files Changed
| File | Change | Reason |
|---|---|---|
| `conftest.py` | Removed `pytest_plugins`, `django.setup()`, `call_command("migrate")`, and custom `settings` fixture | Let pytest-django manage Django init, DB lifecycle, and the mutable `settings` fixture |
| `Makefile` | Updated test command to use `.venv/bin/python -m pytest -p pytest_django.plugin -q` | One canonical, reliable command on this machine |
| `apps/qualification/tests/test_arabic_supertonic_tts.py` | Added `pytestmark = pytest.mark.django_db` | Autouse fixture deletes ORM rows at setup; requires explicit DB access under pytest-django |

## Test Database Handling
- **pytest-django default setup is used.** No manual migration fixture was added.
- **Import-time `call_command("migrate")` was removed.** pytest-django creates the test database and applies migrations when tests request database access via `django_db` (or related fixtures).
- **Safe because:** `config/settings_test.py` uses standard Django apps/migrations; all DB-touching tests either already had `@pytest.mark.django_db` or were updated where an autouse fixture required it. No production code or migration files were changed.

## Final Canonical Test Command
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
DJANGO_SETTINGS_MODULE=config.settings_test \
.venv/bin/python -m pytest -p pytest_django.plugin -q
```

Equivalent via Makefile:

```bash
make test
```

## Validation Results
| Command | Result |
| ------- | ------ |
| `.venv/bin/python manage.py makemigrations --check --dry-run` | No changes detected |
| Full suite with canonical command | **593 passed** in ~6.3s |
| Language-picker subset (`test_language_picker_safe_body_fallback.py`, `test_language_change_command.py`) | **33 passed** |

## Remaining Warnings or Limitations
- **ROS/Python environment:** Normal `pytest` without `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` will still attempt to load broken global ROS plugins on this machine. Always use the canonical command above.
- **Plugin entry point:** Use `-p pytest_django.plugin`, not `-p pytest_django`. The shorter name does not fully register pytest-django markers and config options.
- **Some test modules** use Django `Client` without a module-level `django_db` mark but do not touch the ORM in fixtures; they continue to pass. Any new test with autouse DB fixtures should add `pytest.mark.django_db`.

## Final Result
**PASS**
