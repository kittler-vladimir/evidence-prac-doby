from django.apps import AppConfig


class TimetrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "timetracking"
    verbose_name = "Docházka"

    def ready(self):
        import timetracking.signals  # noqa: F401
