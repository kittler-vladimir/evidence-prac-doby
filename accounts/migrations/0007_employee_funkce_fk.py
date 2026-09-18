import logging

import accounts.models
from django.db import migrations, models
import django.db.models.deletion

logger = logging.getLogger(__name__)


def backfill_funkce_fk(apps, schema_editor):
    """Přeloží starou CharField hodnotu Employee.funkce na FK na novou tabulku
    Funkce — prázdná hodnota (dřívější 'bez funkce') se stává ZAMESTNANEC,
    ostatní hodnoty se mapují 1:1 podle stejného kódu. Neznámý kód (choices
    u CharField nejsou vynucené na úrovni DB) se degraduje na ZAMESTNANEC,
    ale nahlas — ať administrátor při migraci uvidí, že o roli přišel."""
    Employee = apps.get_model("accounts", "Employee")
    Funkce = apps.get_model("accounts", "Funkce")

    funkce_podle_kodu = {f.kod: f for f in Funkce.objects.all()}
    zamestnanec = funkce_podle_kodu["ZAMESTNANEC"]

    for employee in Employee.objects.all():
        stary_kod = employee.funkce or "ZAMESTNANEC"
        nalezena = funkce_podle_kodu.get(stary_kod)
        if nalezena is None:
            logger.warning(
                "Employee pk=%s měl neznámý kód funkce %r — přiřazuji ZAMESTNANEC.",
                employee.pk, stary_kod,
            )
        employee.funkce_nova = nalezena or zamestnanec
        employee.save(update_fields=["funkce_nova"])


def rozbalit_funkce_fk(apps, schema_editor):
    """Reverzní backfill — z FK zpátky na CharField kód (prázdný pro ZAMESTNANEC,
    aby se obnovilo dřívější blank chování)."""
    Employee = apps.get_model("accounts", "Employee")

    for employee in Employee.objects.select_related("funkce_nova").all():
        kod = employee.funkce_nova.kod if employee.funkce_nova_id else ""
        employee.funkce = "" if kod == "ZAMESTNANEC" else kod
        employee.save(update_fields=["funkce"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_funkce"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="funkce_nova",
            field=models.ForeignKey(
                to="accounts.funkce",
                on_delete=django.db.models.deletion.PROTECT,
                null=True,
                blank=True,
                related_name="zamestnanci_docasne",
            ),
        ),
        migrations.RunPython(backfill_funkce_fk, rozbalit_funkce_fk),
        migrations.RemoveField(
            model_name="employee",
            name="funkce",
        ),
        migrations.RenameField(
            model_name="employee",
            old_name="funkce_nova",
            new_name="funkce",
        ),
        migrations.AlterField(
            model_name="employee",
            name="funkce",
            field=models.ForeignKey(
                to="accounts.funkce",
                on_delete=django.db.models.deletion.PROTECT,
                default=accounts.models._vychozi_funkce_id,
                related_name="zamestnanci",
                verbose_name="funkce",
                help_text=(
                    "Role v organizační hierarchii. U funkcí se zapnutým "
                    "'synchronizuje vedoucího' přiřazení automaticky nastaví "
                    "odpovídající pole 'vedoucí' na sekci/odboru/oddělení a uvolní "
                    "funkci předchozímu držiteli téže jednotky."
                ),
            ),
        ),
    ]
