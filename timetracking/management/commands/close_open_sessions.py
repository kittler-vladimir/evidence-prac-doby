"""
Management command: close_open_sessions
Označí zapomenuté otevřené sessions (starší než X hodin) jako vyžadující ruční opravu.
Spouští se přes timetracking.tasks.close_open_sessions jako nightly Celery Beat úloha
(2:00 Europe/Prague, zaregistrováno migrací 0006_schedule_close_open_sessions).

Idempotentní: záznam, který už nese poznámku [AUTOMATICKY] z dřívějšího běhu, se
znovu neoznačuje (jen se vypíše jako stále čekající na opravu) — jinak by neopravený
záznam dostával další kopii poznámky každou noc.
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from timetracking.models import WorkSession, Pohyb

POZNAMKA_SESSION = "[AUTOMATICKY] Odchod nebyl zaznamenán. Prosím doplňte čas odchodu.\n"
POZNAMKA_POHYB = "[AUTOMATICKY] Návrat z pohybu nebyl zaznamenán. Prosím doplňte čas návratu.\n"


def _cas(dt):
    return f"{timezone.localtime(dt):%d.%m.%Y %H:%M}"


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

        stare_sessions = WorkSession.objects.filter(konec__isnull=True, zacatek__lt=threshold)
        znacka_session = POZNAMKA_SESSION.rstrip("\n")
        nove_sessions = list(stare_sessions.exclude(poznamka__startswith=znacka_session))
        drive_sessions = list(stare_sessions.filter(poznamka__startswith=znacka_session))

        if not nove_sessions:
            self.stdout.write("Žádné nové otevřené sessions k označení.")
        else:
            for session in nove_sessions:
                session.poznamka = POZNAMKA_SESSION + session.poznamka
                session.opraveno = False
                session.save(update_fields=["poznamka", "opraveno"])
                self.stdout.write(
                    f"  ! {session.employee} – session od {_cas(session.zacatek)} označena k opravě."
                )
            self.stdout.write(
                self.style.WARNING(f"Celkem označeno {len(nove_sessions)} sessions k ruční opravě.")
            )
        for session in drive_sessions:
            self.stdout.write(
                f"  … {session.employee} – session od {_cas(session.zacatek)} "
                f"stále čeká na opravu (označena dříve)."
            )

        stare_pohyby = Pohyb.objects.filter(konec__isnull=True, zacatek__lt=threshold)
        znacka_pohyb = POZNAMKA_POHYB.rstrip("\n")
        nove_pohyby = list(stare_pohyby.exclude(poznamka__startswith=znacka_pohyb))
        drive_pohyby = list(stare_pohyby.filter(poznamka__startswith=znacka_pohyb))

        if not nove_pohyby:
            self.stdout.write("Žádné nové otevřené pohyby k označení.")
        else:
            for pohyb in nove_pohyby:
                pohyb.poznamka = POZNAMKA_POHYB + pohyb.poznamka
                pohyb.save(update_fields=["poznamka"])
                self.stdout.write(
                    f"  ! {pohyb.employee} – pohyb ({pohyb.typ.zkratka}) od "
                    f"{_cas(pohyb.zacatek)} označen k opravě."
                )
            self.stdout.write(
                self.style.WARNING(f"Celkem označeno {len(nove_pohyby)} pohybů k ruční opravě.")
            )
        for pohyb in drive_pohyby:
            self.stdout.write(
                f"  … {pohyb.employee} – pohyb ({pohyb.typ.zkratka}) od {_cas(pohyb.zacatek)} "
                f"stále čeká na opravu (označen dříve)."
            )
