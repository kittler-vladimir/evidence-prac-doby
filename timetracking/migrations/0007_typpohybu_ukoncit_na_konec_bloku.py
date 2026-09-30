"""Nový příznak TypPohybu.ukoncit_na_konec_bloku (#68) — zapnut rovnou pro služební
cestu a lékaře (podle zkratky, pokud v DB existují). Ostatní typy (oběd, vzdálení...)
zůstávají vypnuté a admin je může zapnout vědomě sám."""
from django.db import migrations, models

ZAPNOUT_PRO_ZKRATKY = ["SluzCesta", "Lekar"]


def zapni_vychozi_typy(apps, schema_editor):
    TypPohybu = apps.get_model("timetracking", "TypPohybu")
    TypPohybu.objects.filter(zkratka__in=ZAPNOUT_PRO_ZKRATKY).update(ukoncit_na_konec_bloku=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0006_schedule_close_open_sessions'),
    ]

    operations = [
        migrations.AddField(
            model_name='typpohybu',
            name='ukoncit_na_konec_bloku',
            field=models.BooleanField(default=False, help_text='Jen pro pevnou pracovní dobu: pohyb, který zaměstnanec neukončí týž den (např. služební cesta, lékař), noční údržba sama ukončí na konci pracovního bloku daného dne — spolu s pracovním blokem, ve kterém běží. Vypnuto (výchozí): zapomenutý pohyb se jen označí k ruční opravě.', verbose_name='ukončit na konci pracovního bloku'),
        ),
        migrations.RunPython(zapni_vychozi_typy, noop_reverse),
    ]
