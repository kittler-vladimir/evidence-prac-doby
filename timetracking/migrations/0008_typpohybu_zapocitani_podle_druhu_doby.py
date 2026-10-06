"""Nahrazuje dva příznaky TypPohybu (započítává se do pracovní doby / u pružné doby)
dvěma samostatnými volbami podle druhu pracovní doby: zapocitani_pevna a
zapocitani_pruzna. Stávající chování zůstává beze změny:

- pružná: nezapočítává se -> NE, započítává se + „u pružné“ -> JADRO, jinak ANO,
- pevná: pohyby se dosud neodečítaly nikdy -> ANO u všech existujících typů.
"""
from django.db import migrations, models


def prevedi_na_nove_volby(apps, schema_editor):
    TypPohybu = apps.get_model("timetracking", "TypPohybu")
    for typ in TypPohybu.objects.all():
        if not typ.zapocitava_se_do_pracovni_doby:
            typ.zapocitani_pruzna = "NE"
        elif typ.zapocitava_se_u_pruzne_pracovni_doby:
            typ.zapocitani_pruzna = "JADRO"
        else:
            typ.zapocitani_pruzna = "ANO"
        typ.zapocitani_pevna = "ANO"
        typ.save(update_fields=["zapocitani_pruzna", "zapocitani_pevna"])


def prevedi_zpet(apps, schema_editor):
    TypPohybu = apps.get_model("timetracking", "TypPohybu")
    for typ in TypPohybu.objects.all():
        typ.zapocitava_se_do_pracovni_doby = typ.zapocitani_pruzna != "NE"
        typ.zapocitava_se_u_pruzne_pracovni_doby = typ.zapocitani_pruzna == "JADRO"
        typ.save(update_fields=[
            "zapocitava_se_do_pracovni_doby", "zapocitava_se_u_pruzne_pracovni_doby",
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('timetracking', '0007_typpohybu_ukoncit_na_konec_bloku'),
    ]

    operations = [
        migrations.AddField(
            model_name='typpohybu',
            name='zapocitani_pevna',
            field=models.CharField(choices=[('ANO', 'Započítává se (neodečítá se)'), ('NE', 'Nezapočítává se (odečte se část uvnitř pracovního bloku)')], default='ANO', help_text='Jak se doba pohybu počítá zaměstnancům s pevnou pracovní dobou. Započítává se: odpracovaná doba je dána jen pracovním blokem a pohyb ji nesnižuje. Nezapočítává se: část pohybu, která leží uvnitř pracovního bloku daného dne, se z odpracované doby odečte.', max_length=5, verbose_name='započítání u pevné pracovní doby'),
        ),
        migrations.AddField(
            model_name='typpohybu',
            name='zapocitani_pruzna',
            field=models.CharField(choices=[('NE', 'Nezapočítává se (odečte se z odpracované doby)'), ('ANO', 'Započítává se celý'), ('JADRO', 'Započítává se jen v jádrové době (mimo ni se odečte)')], default='NE', help_text='Jak se doba pohybu počítá zaměstnancům s pružnou pracovní dobou. Nezapočítává se (výchozí): doba pohybu se odečte (např. oběd, soukromá záležitost). Započítává se: neodečítá se (např. placená přestávka). Jen v jádrové době: započítá se část v pevné (jádrové) době, např. 9–14 hod., část mimo ni se odečte.', max_length=5, verbose_name='započítání u pružné pracovní doby'),
        ),
        migrations.RunPython(prevedi_na_nove_volby, prevedi_zpet),
        migrations.RemoveField(model_name='typpohybu', name='zapocitava_se_do_pracovni_doby'),
        migrations.RemoveField(model_name='typpohybu', name='zapocitava_se_u_pruzne_pracovni_doby'),
    ]
