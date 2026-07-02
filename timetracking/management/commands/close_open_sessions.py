"""
Management command: close_open_sessions
Označí zapomenuté otevřené sessions (starší než X hodin) jako vyžadující ruční opravu.
Spouštět jako Celery beat task každou noc (např. ve 23:59).
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from timetracking.models import WorkSession


class Command(BaseCommand):
    help = "Označí otevřené pracovní bloky starší než daný počet hodin."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hodiny",
            type=int,
            default=14,
            help="Označit sessions starší než X hodin (default: 14).",
        )

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(hours=options["hodiny"])

        staré_sessions = WorkSession.objects.filter(
            konec__isnull=True,
            zacatek__lt=threshold,
        )

        count = staré_sessions.count()
        if count == 0:
            self.stdout.write("Žádné otevřené sessions k označení.")
            return

        for session in staré_sessions:
            session.poznamka = (
                "[AUTOMATICKY] Odchod nebyl zaznamenán. Prosím doplňte čas odchodu.\n"
                + session.poznamka
            )
            session.opraveno = False
            session.save(update_fields=["poznamka", "opraveno"])

            self.stdout.write(
                f"  ⚠ {session.employee} – session od {session.zacatek:%d.%m.%Y %H:%M} "
                f"označena k opravě."
            )

        self.stdout.write(
            self.style.WARNING(f"Celkem označeno {count} sessions k ruční opravě.")
        )
