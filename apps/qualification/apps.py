from django.apps import AppConfig


class QualificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.qualification"

    def ready(self) -> None:
        from apps.qualification.startup_validation import validate_qualification_startup_config

        validate_qualification_startup_config()
