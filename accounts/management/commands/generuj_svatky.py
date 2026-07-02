"""
Management command: generuj_svatky
Vygeneruje státní svátky ČR (nebo jiné země) pro daný rok.
Admin je může poté ručně upravit v Django admin.
"""
from django.core.management.base import BaseCommand
from accounts.holidays_model import generuj_svatky_cr, StatniSvatek, Zeme


class Command(BaseCommand):
    help = "Vygeneruje státní svátky pro daný rok a zemi."

    def add_arguments(self, parser):
        parser.add_argument("rok", type=int, help="Rok (např. 2025)")
        parser.add_argument(
            "--zeme",
            type=str,
            default="CZ",
            help="ISO kód země (default: CZ)",
        )
        parser.add_argument(
            "--prepsat",
            action="store_true",
            help="Přepsat existující záznamy.",
        )

    def handle(self, *args, **options):
        rok = options["rok"]
        zeme_kod = options["zeme"].upper()
        prepsat = options["prepsat"]

        try:
            zeme = Zeme.objects.get(kod=zeme_kod)
        except Zeme.DoesNotExist:
            self.stderr.write(f"Země s kódem '{zeme_kod}' neexistuje v databázi.")
            return

        if zeme_kod == "CZ":
            svatky = generuj_svatky_cr(rok)
        else:
            self.stderr.write(f"Generátor pro zemi '{zeme_kod}' není implementován.")
            return

        vytvoreno = 0
        preskoceno = 0

        for svarek in svatky:
            obj, created = StatniSvatek.objects.get_or_create(
                zeme=zeme,
                datum=svarek["datum"],
                defaults={"nazev": svarek["nazev"]},
            )
            if not created and prepsat:
                obj.nazev = svarek["nazev"]
                obj.save()
                vytvoreno += 1
            elif created:
                vytvoreno += 1
            else:
                preskoceno += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Rok {rok} ({zeme_kod}): {vytvoreno} svátků vytvořeno/aktualizováno, "
                f"{preskoceno} přeskočeno."
            )
        )
