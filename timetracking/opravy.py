"""Zapomenuté (otevřené z předchozího dne) pracovní bloky a pohyby: kdo je smí
opravit, jak je najít a jak po opravě uklidit poznámku [AUTOMATICKY].

Jediné místo pro text značek, který zapisuje close_open_sessions — oprava ho
odstraňuje a příkaz podle něj pozná už označený záznam.
"""
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Pohyb, WorkSession

ZNACKA_SESSION = "[AUTOMATICKY] Odchod nebyl zaznamenán. Prosím doplňte čas odchodu.\n"
ZNACKA_POHYB = "[AUTOMATICKY] Návrat z pohybu nebyl zaznamenán. Prosím doplňte čas návratu.\n"
# Auditní poznámka k pohybu i bloku, které noční údržba sama ukončila (#68); {cas} = HH:MM.
ZNACKA_AUTO_UKONCENI = "[AUTOMATICKY] Ukončeno automaticky na konci pracovního bloku ({cas}).\n"


def odstran_znacku(poznamka, znacka):
    """Poznámka bez systémové věty [AUTOMATICKY]; vlastní text zaměstnance zůstane."""
    return poznamka.replace(znacka, "").replace(znacka.rstrip("\n"), "")


def muze_opravovat(user, employee):
    """Záznam smí opravit jeho zaměstnanec, is_staff, nebo vedoucí/zástupce, který
    daného zaměstnance spravuje (spravovani_zamestnanci — rozsah CRUD, ne jen čtení)."""
    if user.is_staff:
        return True
    vlastni = getattr(user, "employee", None)
    if vlastni is None:
        return False
    if vlastni.pk == employee.pk:
        return True
    return vlastni.spravovani_zamestnanci().filter(pk=employee.pk).exists()


def zacatek_dneska():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time.min))


def je_ze_starsiho_dne(dt):
    return dt < zacatek_dneska()


def zaznamy_k_oprave(zamestnanci):
    """Otevřené bloky a pohyby daných zaměstnanců, které začaly před dneškem
    (bez ohledu na to, jestli je už označil close_open_sessions), seřazené podle
    začátku — jako slovníky pro šablonu _zaznamy_k_oprave.html."""
    hranice = zacatek_dneska()
    sessions = WorkSession.objects.filter(
        employee__in=zamestnanci, konec__isnull=True, zacatek__lt=hranice,
    ).select_related("employee__user")
    pohyby = Pohyb.objects.filter(
        work_session__employee__in=zamestnanci, konec__isnull=True, zacatek__lt=hranice,
    ).select_related("typ", "work_session__employee__user")

    zaznamy = [
        {
            "druh": "Pracovní blok",
            "employee": s.employee,
            "zacatek": s.zacatek,
            "oznaceno": s.poznamka.startswith(ZNACKA_SESSION.rstrip("\n")),
            "url": reverse("timetracking:opravit_session", args=[s.pk]),
        }
        for s in sessions
    ] + [
        {
            "druh": f"Pohyb ({p.typ.nazev})",
            "employee": p.work_session.employee,
            "zacatek": p.zacatek,
            "oznaceno": p.poznamka.startswith(ZNACKA_POHYB.rstrip("\n")),
            "url": reverse("timetracking:opravit_pohyb", args=[p.pk]),
        }
        for p in pohyby
    ]
    return sorted(zaznamy, key=lambda z: z["zacatek"])


def bezpecny_next(request, vychozi="timetracking:dashboard"):
    """Kam se vrátit po uložení opravy — jen na vlastní web (ochrana proti open redirectu)."""
    kam = request.POST.get("next") or request.GET.get("next")
    if kam and url_has_allowed_host_and_scheme(
        kam, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return kam
    return reverse(vychozi)


def konec_bloku_pevne_doby(employee, datum):
    """Konec posledního časového bloku pevné pracovní doby zaškrtnutého pro den
    v týdnu `datum` (aware datetime), nebo None — zaměstnanec nemá pevnou
    pracovní dobu, nebo pro ten den žádný blok neplatí (víkend...)."""
    from accounts.models import CasovyBlokUvazku, TypUvazku

    typ = employee.typ_uvazku
    if typ is None or typ.druh_pracovni_doby != TypUvazku.DruhPracovniDoby.PEVNA:
        return None
    den_pole = CasovyBlokUvazku.DNY_V_TYDNU[datum.weekday()]
    blok = (
        CasovyBlokUvazku.objects.filter(typ_uvazku=typ, **{den_pole: True})
        .order_by("-blok_do").first()
    )
    if blok is None:
        return None
    return timezone.make_aware(datetime.combine(datum, blok.blok_do))


def ukonci_na_konec_bloku(pohyb):
    """Zapomenutý pohyb typu s `ukoncit_na_konec_bloku` u zaměstnance s pevnou
    pracovní dobou ukončí — spolu s jeho pracovním blokem — na konci bloku dne,
    kdy pohyb začal (#68). Vrátí použitý konec, nebo None, když pravidlo nejde
    použít (pak zůstává jen označení k ruční opravě): jiný typ/úvazek, den bez
    bloku, pohyb začal až po konci bloku, blok začal jiný den, nebo by uložení
    neprošlo validací modelu (vše se pak vrátí zpět)."""
    session = pohyb.work_session
    if not pohyb.typ.ukoncit_na_konec_bloku or pohyb.konec is not None or session.konec is not None:
        return None
    datum = timezone.localdate(pohyb.zacatek)
    if timezone.localdate(session.zacatek) != datum:
        return None
    konec = konec_bloku_pevne_doby(session.employee, datum)
    if konec is None or pohyb.zacatek >= konec:
        return None

    poznamka = ZNACKA_AUTO_UKONCENI.format(cas=f"{timezone.localtime(konec):%H:%M}")
    try:
        with transaction.atomic():
            pohyb.konec = konec
            pohyb.poznamka = poznamka + odstran_znacku(pohyb.poznamka, ZNACKA_POHYB)
            pohyb.full_clean()
            pohyb.save()
            session.konec = konec
            session.poznamka = poznamka + odstran_znacku(session.poznamka, ZNACKA_SESSION)
            session.full_clean()
            session.save()
    except ValidationError:
        pohyb.refresh_from_db()
        session.refresh_from_db()
        return None
    return konec
