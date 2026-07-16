# Run tests (disables conflicting system pytest plugins on this machine)
.PHONY: test
test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python -m pytest -p pytest_django.plugin -q
