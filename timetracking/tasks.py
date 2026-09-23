from celery import shared_task
from django.core.management import call_command


@shared_task
def close_open_sessions():
    """Celery obal nad management příkazem `close_open_sessions` — naplánováno
    jako nightly PeriodicTask (viz migrace 0006_schedule_close_open_sessions)."""
    call_command("close_open_sessions")
