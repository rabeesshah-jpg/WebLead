# Run tests (disables conflicting system pytest plugins on this machine)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 DJANGO_SETTINGS_MODULE=config.settings_test pytest -p pytest_django
