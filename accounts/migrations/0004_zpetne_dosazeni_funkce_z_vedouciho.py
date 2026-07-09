from django.db import migrations


def dosad_funkci_z_vedouciho(apps, schema_editor):
    """
    Existující přiřazení Sekce/Odbor/Oddeleni.vedouci vznikla před zavedením
    Employee.funkce a nemají svůj protějšek — bez tohoto backfillu by
    reální vedoucí ztratili přístup do sprovodňovaných přehledů/CRUD, které
    teď čtou funkce, ne přímo pole vedouci. Vyšší úroveň má přednost, pokud
    by (výjimečně) stejný zaměstnanec byl vedoucím na víc úrovních zároveň.
    """
    Sekce = apps.get_model("accounts", "Sekce")
    Odbor = apps.get_model("accounts", "Odbor")
    Oddeleni = apps.get_model("accounts", "Oddeleni")
    Employee = apps.get_model("accounts", "Employee")

    for sekce in Sekce.objects.filter(vedouci__isnull=False, vedouci__funkce=""):
        Employee.objects.filter(pk=sekce.vedouci_id).update(funkce="REDITEL_SEKCE")

    for odbor in Odbor.objects.filter(vedouci__isnull=False, vedouci__funkce=""):
        Employee.objects.filter(pk=odbor.vedouci_id).update(funkce="REDITEL_ODBORU")

    for oddeleni in Oddeleni.objects.filter(vedouci__isnull=False, vedouci__funkce=""):
        Employee.objects.filter(pk=oddeleni.vedouci_id).update(funkce="VEDOUCI_ODDELENI")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_funkce_a_viditelnost_odboru"),
    ]

    operations = [
        migrations.RunPython(dosad_funkci_z_vedouciho, migrations.RunPython.noop),
    ]
