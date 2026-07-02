from django.db import migrations


def seed_and_backfill(apps, schema_editor):
    TypDovolene = apps.get_model("leaves", "TypDovolene")
    ZustatekDovolene = apps.get_model("leaves", "ZustatekDovolene")

    TypDovolene.objects.get_or_create(
        zkratka="IV",
        defaults={
            "nazev": "Indispoziční volno",
            "odecita_ze_zustatku": True,
            "je_indispozicni_volno": True,
        },
    )

    bez_typu = ZustatekDovolene.objects.filter(typ__isnull=True)
    if bez_typu.exists():
        # Přednostně použít existující typ dovolené (odečítá ze zůstatku,
        # není indispoziční volno) — teprve pokud žádný neexistuje, založit "DOV".
        dovolena_typ = TypDovolene.objects.filter(
            odecita_ze_zustatku=True, je_indispozicni_volno=False
        ).order_by("id").first()
        if dovolena_typ is None:
            dovolena_typ = TypDovolene.objects.create(
                zkratka="DOV", nazev="Dovolená", odecita_ze_zustatku=True,
            )
        bez_typu.update(typ=dovolena_typ)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0002_add_indispozicni_volno_schema"),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, noop_reverse),
    ]
