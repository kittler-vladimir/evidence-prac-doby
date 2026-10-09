from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

from accounts.models import Employee

from .models import TypStavu, ZadostOStav, ZustatekStavu


def _posli_email(subject: str, template: str, context: dict, recipients: list[str]):
    """Pomocná funkce pro odesílání e-mailu."""
    if not recipients:
        return
    body = render_to_string(template, context)
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


@receiver(post_save, sender=Employee)
def zaloz_zustatky_noveho_zamestnance(sender, instance, created, raw=False, **kwargs):
    """Nový aktivní zaměstnanec dostane hned zůstatky stavů pro letošní rok — stejné, jaké
    by mu k 1. lednu založil příkaz obnov_rocni_naroky (typy odečítající ze zůstatku).
    Už existující zůstatek se u nového zaměstnance nepřepisuje.

    Při (opětovné) aktivaci neaktivního zaměstnance (Employee.save() nastaví
    _byl_aktivovan) se letošnímu zůstatku každého takového typu nastaví nárok na
    výchozí hodnotu — chybějící zůstatek se založí. Už čerpané hodiny se nemění;
    běžné další uložení aktivního zaměstnance nedělá nic."""
    if raw or not instance.aktivni:
        return
    aktivace = getattr(instance, "_byl_aktivovan", False)
    if not (created or aktivace):
        return

    # Dovolená a indispoziční volno mají globální nárok vždy, i kdyby u nich admin
    # nezaškrtl odecita_ze_zustatku (stejný výběr jako „Moje žádosti“ v leaves.views).
    typy = TypStavu.objects.filter(aktivni=True).filter(
        Q(odecita_ze_zustatku=True) | Q(je_dovolena=True) | Q(je_indispozicni_volno=True)
    )
    dnes = timezone.localdate()
    for typ in typy:
        vychozi_narok = typ.vychozi_narok(dnes)
        if aktivace:
            ZustatekStavu.objects.update_or_create(
                employee=instance, rok=dnes.year, typ=typ,
                defaults={"narok_hodin": vychozi_narok},
            )
        else:
            ZustatekStavu.objects.get_or_create(
                employee=instance, rok=dnes.year, typ=typ,
                defaults={"narok_hodin": vychozi_narok},
            )


@receiver(post_save, sender=ZadostOStav)
def prepocitej_souhrny_hodinove_zadosti(sender, instance, created, **kwargs):
    """Schválená hodinová žádost se počítá do denní normy ve Výkazu (#82) — po vzniku
    nebo přechodu stavu se přepočítají už existující denní souhrny jejích dnů. Dny bez
    souhrnu (bez uzavřeného bloku docházky) se nezakládají."""
    zadost = instance
    if not zadost.je_po_hodinach:
        return
    if not (created or getattr(zadost, "_stav_se_zmenil", True)):
        return

    from timetracking.models import WorkdaySummary

    for den in zadost.hodiny_po_dnech():
        if WorkdaySummary.objects.filter(employee=zadost.employee, datum=den).exists():
            WorkdaySummary.prepocitej(zadost.employee, den)


@receiver(post_save, sender=ZadostOStav)
def notifikace_zadost(sender, instance, created, **kwargs):
    """
    Odesílá e-mailové notifikace:
    - při vytvoření žádosti → schvalovateli
    - při schválení → zaměstnanci
    - při zamítnutí → zaměstnanci
    """
    zadost = instance

    if created:
        # Notifikace schvalovateli
        if zadost.schvalovatele and zadost.schvalovatele.email:
            _posli_email(
                subject=f"Nová žádost o {zadost.typ.nazev.lower()} – {zadost.employee.jmeno}",
                template="leaves/emails/nova_zadost.txt",
                context={"zadost": zadost},
                recipients=[zadost.schvalovatele.email],
            )
        return

    # Poslat jen při skutečném přechodu stavu, ne při každém dalším uložení
    # už vyřízené žádosti (viz ZadostOStav.save()).
    if not getattr(zadost, "_stav_se_zmenil", True):
        return

    # Při změně stavu
    if zadost.stav == ZadostOStav.Stav.SCHVALENO:
        if zadost.samoschvaleno:
            return  # schválil si to sám — e-mail sám sobě nedává smysl (#90)
        _posli_email(
            subject=f"Vaše žádost o {zadost.typ.nazev.lower()} byla schválena",
            template="leaves/emails/schvaleno.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )

    elif zadost.stav == ZadostOStav.Stav.ZAMITNUTO:
        _posli_email(
            subject=f"Vaše žádost o {zadost.typ.nazev.lower()} byla zamítnuta",
            template="leaves/emails/zamitnuto.txt",
            context={"zadost": zadost},
            recipients=[zadost.employee.email],
        )
