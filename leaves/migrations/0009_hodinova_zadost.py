"""Hodinová dovolená (#82): příznak TypStavu.umoznuje_zadani_po_hodinach (zapnutý jen
u dovolené) a volitelný čas od–do u žádosti. Stávající žádosti zůstávají na celé dny."""
from django.db import migrations, models


def zapni_pro_dovolenou(apps, schema_editor):
    TypStavu = apps.get_model("leaves", "TypStavu")
    TypStavu.objects.filter(je_dovolena=True).update(umoznuje_zadani_po_hodinach=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('leaves', '0008_seed_nemoc'),
    ]

    operations = [
        migrations.AddField(
            model_name='typstavu',
            name='umoznuje_zadani_po_hodinach',
            field=models.BooleanField(default=False, help_text='Zapnuto: u žádosti tohoto typu lze místo celých dnů zadat čas od–do. Ve výchozím stavu je zapnuto jen u dovolené.', verbose_name='umožňuje zadání po hodinách'),
        ),
        migrations.AddField(
            model_name='zadostostav',
            name='cas_od',
            field=models.TimeField(blank=True, null=True, verbose_name='čas od'),
        ),
        migrations.AddField(
            model_name='zadostostav',
            name='cas_do',
            field=models.TimeField(blank=True, null=True, verbose_name='čas do'),
        ),
        migrations.RunPython(zapni_pro_dovolenou, noop_reverse),
    ]
