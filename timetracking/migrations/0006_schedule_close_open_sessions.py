"""Zaregistruje close_open_sessions jako nightly Celery Beat úlohu (2:00 Europe/Prague).

Idempotentní přes get_or_create — bezpečné i při opakovaném spuštění. Task samotný
(timetracking.tasks.close_open_sessions) se objeví, jakmile poběží Celery worker + beat
proti této databázi; do té doby je PeriodicTask jen zaregistrovaný a čeká.
"""
from django.db import migrations

NAZEV_ULOHY = "Označit zapomenuté otevřené sessions/pohyby (close_open_sessions)"
NAZEV_TASKU = "timetracking.tasks.close_open_sessions"


def vytvor_ulohu(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="2",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Europe/Prague",
    )
    PeriodicTask.objects.get_or_create(
        name=NAZEV_ULOHY,
        defaults={
            "crontab": schedule,
            "task": NAZEV_TASKU,
            "enabled": True,
        },
    )


def smazat_ulohu(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=NAZEV_ULOHY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("timetracking", "0005_typpohybu_help_texty"),
        ("django_celery_beat", "0018_improve_crontab_helptext"),
    ]

    operations = [
        migrations.RunPython(vytvor_ulohu, smazat_ulohu),
    ]
