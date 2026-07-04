from django.db import migrations, models
import django.db.models.deletion


def vytvor_chybejici_typy_a_zaznamy_stavu(apps, schema_editor):
    """
    Nemoc a služební volno už jako řádky číselníku existují (založené mimo
    migrace 0001-0005) — jen se doplní o nové pole vyzaduje_schvaleni=False
    (samo-záznam), podle kategorie_pro_prehled, ne podle zkratky (ta se mezi
    prostředími může lišit). OČR a home office dosud neexistují vůbec —
    ty se zakládají nově. Dovolená a indispoziční volno zůstávají
    vyzaduje_schvaleni=True (výchozí hodnota pole).
    """
    TypStavu = apps.get_model("leaves", "TypStavu")

    TypStavu.objects.filter(kategorie_pro_prehled="NEMOC").update(
        vyzaduje_schvaleni=False, je_pritomnost=False,
    )
    TypStavu.objects.filter(kategorie_pro_prehled="SLUZEBNI_VOLNO").update(
        vyzaduje_schvaleni=False, je_pritomnost=False,
    )

    TypStavu.objects.get_or_create(
        kategorie_pro_prehled="OCR",
        defaults=dict(
            zkratka="OCR",
            nazev="Ošetřování člena rodiny",
            odecita_ze_zustatku=False,
            je_pritomnost=False,
            vyzaduje_schvaleni=False,
            barva="#6C757D",
        ),
    )
    TypStavu.objects.get_or_create(
        zkratka="HO",
        defaults=dict(
            nazev="Home office",
            odecita_ze_zustatku=False,
            je_pritomnost=True,
            vyzaduje_schvaleni=False,
            kategorie_pro_prehled="JINA",
            barva="#6610F2",
        ),
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0005_add_kategorie_pro_prehled"),
    ]

    operations = [
        migrations.RenameModel(old_name="TypDovolene", new_name="TypStavu"),
        migrations.RenameModel(old_name="ZadostODovolenou", new_name="ZadostOStav"),
        migrations.RenameModel(old_name="ZustatekDovolene", new_name="ZustatekStavu"),
        migrations.AlterModelOptions(
            name="typstavu",
            options={"verbose_name": "typ stavu", "verbose_name_plural": "typy stavu"},
        ),
        migrations.AlterModelOptions(
            name="zadostostav",
            options={"ordering": ["-vytvoreno"], "verbose_name": "žádost o stav", "verbose_name_plural": "žádosti o stav"},
        ),
        migrations.AlterModelOptions(
            name="zustatekstavu",
            options={"ordering": ["-rok"], "verbose_name": "zůstatek stavu", "verbose_name_plural": "zůstatky stavu"},
        ),
        migrations.AddField(
            model_name="typstavu",
            name="vyzaduje_schvaleni",
            field=models.BooleanField(
                default=True,
                verbose_name="vyžaduje schválení",
                help_text=(
                    "Zapnuto: zaměstnanec podává žádost, kterou schvaluje vedoucí "
                    "(dovolená, indispoziční volno). Vypnuto: zaměstnanec si stav "
                    "zapisuje sám na daný den/rozsah, bez schvalování (např. "
                    "nemoc, OČR, služební volno, home office)."
                ),
            ),
        ),
        migrations.AddField(
            model_name="typstavu",
            name="je_pritomnost",
            field=models.BooleanField(
                default=False,
                verbose_name="je přítomnost",
                help_text=(
                    "Zapnuto u typů, kdy zaměstnanec pracuje, jen ne na pracovišti "
                    "(např. home office) — v denním přehledu má přednost i před "
                    "běžným „Přítomen“ na základě docházky. Vypnuto u typů "
                    "nepřítomnosti na pracovišti."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="typstavu",
            name="kategorie_pro_prehled",
            field=models.CharField(
                choices=[
                    ("DOVOLENA", "Dovolená"),
                    ("NEMOC", "Nemoc"),
                    ("INDISPOZICNI_VOLNO", "Indispoziční volno"),
                    ("SLUZEBNI_VOLNO", "Služební volno"),
                    ("OCR", "Ošetřování člena rodiny"),
                    ("JINA", "Jiná absence"),
                ],
                default="JINA",
                help_text=(
                    "Volitelné hrubé třídění pro administraci. Zobrazení a priorita "
                    "v denním přehledu přítomnosti na tomto poli nezávisí — vychází "
                    "přímo z názvu/barvy tohoto typu a z pole „je přítomnost“."
                ),
                max_length=20,
                verbose_name="kategorie pro přehled přítomnosti",
            ),
        ),
        migrations.AlterField(
            model_name="typstavu",
            name="barva",
            field=models.CharField(
                default="#4A90E2",
                help_text="Barva pro zobrazení v kalendáři a v denním přehledu přítomnosti.",
                max_length=7,
                verbose_name="barva (hex)",
            ),
        ),
        migrations.AlterField(
            model_name="zustatekstavu",
            name="employee",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="zustatky_stavu",
                to="accounts.employee",
                verbose_name="zaměstnanec",
            ),
        ),
        migrations.AlterField(
            model_name="zadostostav",
            name="employee",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="zadosti_o_stav",
                to="accounts.employee",
                verbose_name="zaměstnanec",
            ),
        ),
        migrations.RunPython(vytvor_chybejici_typy_a_zaznamy_stavu, noop_reverse),
    ]
