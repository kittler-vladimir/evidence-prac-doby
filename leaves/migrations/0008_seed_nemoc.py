"""Doplní chybějící typ stavu "Nemoc" — CLAUDE.md i KategoriePrehled.NEMOC s ním
počítaly jako se standardním self-recorded typem (jako OČR/služební volno/home
office), ale samotný TypStavu záznam nikdy nebyl založen."""
from django.db import migrations


def vytvor_nemoc(apps, schema_editor):
    TypStavu = apps.get_model("leaves", "TypStavu")
    TypStavu.objects.get_or_create(
        zkratka="NEM",
        defaults={
            "nazev": "Nemoc",
            "odecita_ze_zustatku": False,
            "je_indispozicni_volno": False,
            "je_dovolena": False,
            "vyzaduje_schvaleni": False,
            "je_pritomnost": False,
            "kategorie_pro_prehled": "NEMOC",
            "barva": "#DC3545",
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0007_narok_dovolene"),
    ]

    operations = [
        migrations.RunPython(vytvor_nemoc, noop_reverse),
    ]
