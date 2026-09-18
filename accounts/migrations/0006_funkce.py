from django.db import migrations, models
import django.db.models.deletion


FUNKCE_SEED = [
    # kod, nazev, uroven_vazby, synchronizuje_vedouciho, muze_spravovat,
    # muze_presouvat, muze_menit_funkci, muze_mit_zastupce, bez_seznamu_zamestnancu
    ("REDITEL_SEKCE", "Ředitel sekce", "SEKCE", True, False, False, False, False, True),
    ("REDITEL_ODBORU", "Ředitel odboru", "ODBOR", True, True, True, True, True, False),
    ("VEDOUCI_ODDELENI", "Vedoucí oddělení", "ODDELENI", True, True, False, False, True, False),
    ("SEKRETARIAT_ODBORU", "Sekretariát odboru", "ODBOR", False, True, True, True, True, False),
    ("ZAMESTNANEC", "Zaměstnanec", "ZADNA", False, False, False, False, False, False),
]


def seed_funkce(apps, schema_editor):
    """Vytvoří 5 řádků Funkce s příznaky, které 1:1 reprodukují dřívější
    hardcoded chování (Employee.FunkceChoices + FUNKCE_SE_ZASTUPCEM +
    FUNKCE_S_PRAVEM_PRESUN_A_ZMENA), plus novou roli ZAMESTNANEC."""
    Funkce = apps.get_model("accounts", "Funkce")
    for (
        kod, nazev, uroven_vazby, synchronizuje_vedouciho, muze_spravovat,
        muze_presouvat, muze_menit_funkci, muze_mit_zastupce, bez_seznamu_zamestnancu,
    ) in FUNKCE_SEED:
        Funkce.objects.create(
            kod=kod, nazev=nazev, uroven_vazby=uroven_vazby,
            synchronizuje_vedouciho=synchronizuje_vedouciho,
            muze_spravovat_zamestnance=muze_spravovat,
            muze_presouvat_zamestnance=muze_presouvat,
            muze_menit_funkci=muze_menit_funkci,
            muze_mit_zastupce=muze_mit_zastupce,
            bez_seznamu_zamestnancu=bez_seznamu_zamestnancu,
            aktivni=True,
        )


def unseed_funkce(apps, schema_editor):
    Funkce = apps.get_model("accounts", "Funkce")
    Funkce.objects.filter(kod__in=[row[0] for row in FUNKCE_SEED]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_employee_rucne_nepritomen_employee_zastupce"),
    ]

    operations = [
        migrations.CreateModel(
            name="Funkce",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kod", models.SlugField(max_length=30, unique=True, verbose_name="kód")),
                ("nazev", models.CharField(max_length=100, verbose_name="název")),
                (
                    "uroven_vazby",
                    models.CharField(
                        choices=[("ZADNA", "Žádná"), ("ODDELENI", "Oddělení"), ("ODBOR", "Odbor"), ("SEKCE", "Sekce")],
                        default="ZADNA",
                        help_text="Organizační úroveň, na kterou je funkce vázaná — řídí rozsah pravidla 'nejvýše jeden držitel funkce na jednotku' a rozsah výběru zástupce/spravovaných oddělení. 'Žádná' = bez vazby (např. Zaměstnanec).",
                        max_length=10,
                        verbose_name="úroveň vazby",
                    ),
                ),
                (
                    "synchronizuje_vedouciho",
                    models.BooleanField(
                        default=False,
                        help_text="Zapnuto: přiřazení funkce automaticky nastaví pole 'vedoucí' na organizační jednotce dané úrovní vazby (a při zrušení funkce ho zase uvolní). Vypnuto: funkce nese CRUD práva na dané úrovni, ale nereprezentuje jednotku navenek jako její vedoucí (např. Sekretariát odboru).",
                        verbose_name="synchronizuje pole vedoucí",
                    ),
                ),
                (
                    "muze_spravovat_zamestnance",
                    models.BooleanField(
                        default=False,
                        help_text="Smí zakládat/upravovat/přesouvat zaměstnance v rozsahu dle úrovně vazby.",
                        verbose_name="smí spravovat zaměstnance",
                    ),
                ),
                (
                    "muze_presouvat_zamestnance",
                    models.BooleanField(
                        default=False,
                        help_text="Smí přesouvat zaměstnance mezi odděleními v rámci svého rozsahu.",
                        verbose_name="smí přesouvat zaměstnance",
                    ),
                ),
                (
                    "muze_menit_funkci",
                    models.BooleanField(
                        default=False,
                        help_text="Smí přiřazovat/měnit funkci jiným zaměstnancům v rámci svého rozsahu.",
                        verbose_name="smí měnit funkci",
                    ),
                ),
                (
                    "muze_mit_zastupce",
                    models.BooleanField(
                        default=False,
                        help_text="Držitel funkce si může zvolit trvalého zástupce ze stejné organizační jednotky.",
                        verbose_name="smí mít zástupce",
                    ),
                ),
                (
                    "bez_seznamu_zamestnancu",
                    models.BooleanField(
                        default=False,
                        help_text="Zapnuto: bez přístupu k seznamu jednotlivých zaměstnanců (accounts.viditelni_zamestnanci vrátí prázdný queryset) — u funkce vázané na úroveň Sekce má místo toho zaměstnanec vlastní souhrnný přehled sekce (accounts:prehled_sekce).",
                        verbose_name="bez seznamu zaměstnanců",
                    ),
                ),
                ("aktivni", models.BooleanField(default=True, verbose_name="aktivní")),
            ],
            options={
                "verbose_name": "funkce",
                "verbose_name_plural": "funkce",
                "ordering": ["nazev"],
            },
        ),
        migrations.RunPython(seed_funkce, unseed_funkce),
    ]
