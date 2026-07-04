"""
Management command: obnov_rocni_naroky
Pro každého aktivního zaměstnance a každý aktivní typ stavu, který odečítá
ze zůstatku, založí zůstatek pro daný rok (výchozí: aktuální rok):
- dovolená: zbytek z minulého roku (min. 0) + roční nárok z NarokDovolene,
- indispoziční volno: aktuální hodnota z NarokIndispozicnihoVolna (bez zbytku).
Idempotentní — pokud zůstatek pro dané employee/rok/typ už existuje,
přeskočí ho a nic nemění. Spouštět jako Celery beat task každý 1. ledna.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Employee
from leaves.models import NarokDovolene, NarokIndispozicnihoVolna, TypStavu, ZustatekStavu


class Command(BaseCommand):
    help = "Založí roční zůstatky dovolené a indispozičního volna pro aktivní zaměstnance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rok",
            type=int,
            default=None,
            help="Rok, pro který se mají zůstatky založit (default: aktuální rok).",
        )

    def handle(self, *args, **options):
        rok = options["rok"] or timezone.now().year
        k_datu = date(rok, 1, 1)

        zamestnanci = list(Employee.objects.filter(aktivni=True))
        typy = list(TypStavu.objects.filter(odecita_ze_zustatku=True, aktivni=True))

        # Hodnoty platné k 1. lednu daného roku se během běhu nemění —
        # spočítat je jednou místo v každé iteraci.
        narok_dovolene = NarokDovolene.aktivni_hodnota(k_datu)
        narok_iv = NarokIndispozicnihoVolna.aktivni_hodnota(k_datu)

        # Zůstatky pro cílový rok a předchozí rok (kvůli zbytku dovolené)
        # načíst hromadně místo dotazu pro každou dvojici employee/typ.
        existujici = set(
            ZustatekStavu.objects.filter(rok=rok, typ__in=typy)
            .values_list("employee_id", "typ_id")
        )
        predchozi_zbytky = {
            (z.employee_id, z.typ_id): z.zbyvajici_hodin
            for z in ZustatekStavu.objects.filter(rok=rok - 1, typ__in=typy)
        }

        nove_zustatky = []
        preskoceno = 0

        for employee in zamestnanci:
            for typ in typy:
                if (employee.pk, typ.pk) in existujici:
                    preskoceno += 1
                    continue

                if typ.je_dovolena:
                    zbytek = max(Decimal("0"), predchozi_zbytky.get((employee.pk, typ.pk), Decimal("0")))
                    narok_hodin = zbytek + narok_dovolene
                elif typ.je_indispozicni_volno:
                    narok_hodin = narok_iv
                else:
                    narok_hodin = Decimal("0")
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ⚠ Typ {typ.zkratka} odečítá ze zůstatku, ale není "
                            f"označen jako dovolená ani indispoziční volno — "
                            f"nárok založen jako 0h, zkontrolujte ručně."
                        )
                    )

                nove_zustatky.append(
                    ZustatekStavu(employee=employee, rok=rok, typ=typ, narok_hodin=narok_hodin)
                )

        ZustatekStavu.objects.bulk_create(nove_zustatky)

        self.stdout.write(
            self.style.SUCCESS(
                f"Zpracováno {len(zamestnanci)} zaměstnanců, "
                f"vytvořeno {len(nove_zustatky)} zůstatků, "
                f"přeskočeno {preskoceno} (již existují)."
            )
        )
