from dataclasses import dataclass

from django.utils import timezone

from leaves.models import TypDovolene, ZadostODovolenou
from timetracking.models import WorkSession

PRITOMEN = "PRITOMEN"
NEPRITOMEN = "NEPRITOMEN"

_BADGE_TRIDY = {
    PRITOMEN: "bg-success",
    NEPRITOMEN: "bg-dark",
    TypDovolene.KategoriePrehled.DOVOLENA: "bg-warning text-dark",
    TypDovolene.KategoriePrehled.NEMOC: "bg-danger",
    TypDovolene.KategoriePrehled.INDISPOZICNI_VOLNO: "bg-info text-dark",
    TypDovolene.KategoriePrehled.SLUZEBNI_VOLNO: "bg-primary",
    TypDovolene.KategoriePrehled.OCR: "bg-secondary",
    TypDovolene.KategoriePrehled.JINA: "bg-secondary",
}

_POPISKY = {
    PRITOMEN: "Přítomen",
    NEPRITOMEN: "Nepřítomen",
}


@dataclass(frozen=True)
class StavZamestnance:
    kod: str
    popisek: str
    badge_trida: str


def stavy_zamestnancu(zamestnanci, datum) -> dict:
    """
    Vrátí {employee_id: StavZamestnance} pro danou skupinu zaměstnanců a datum,
    jednou dávkou (2 dotazy celkem, ne 2 na zaměstnance).

    Pravidlo priority: Přítomen > schválená absence (dle
    TypDovolene.kategorie_pro_prehled) > Nepřítomen.

    "Přítomen" k dnešnímu dni znamená aktuálně odpíchnutou (neuzavřenou)
    WorkSession; pro jiná data stačí jakákoli WorkSession toho dne — pozor,
    `close_open_sessions` otevřené session z minulosti sama neuzavírá, jen je
    označí `[AUTOMATICKY]` pro ruční opravu, takže i zapomenutý odchod se zde
    k danému dni počítá jako přítomnost.
    """
    zamestnanci = list(zamestnanci)
    if not zamestnanci:
        return {}

    sessions = WorkSession.objects.filter(employee__in=zamestnanci, zacatek__date=datum)
    if datum == timezone.localdate():
        sessions = sessions.filter(konec__isnull=True)
    pritomni_ids = set(sessions.values_list("employee_id", flat=True))

    zadost_podle_zamestnance = {}
    zadosti = ZadostODovolenou.objects.filter(
        employee__in=zamestnanci,
        stav=ZadostODovolenou.Stav.SCHVALENO,
        datum_od__lte=datum,
        datum_do__gte=datum,
    ).select_related("typ").order_by("-vytvoreno")
    for zadost in zadosti:
        zadost_podle_zamestnance.setdefault(zadost.employee_id, zadost)

    vysledek = {}
    for zam in zamestnanci:
        if zam.pk in pritomni_ids:
            vysledek[zam.pk] = StavZamestnance(PRITOMEN, _POPISKY[PRITOMEN], _BADGE_TRIDY[PRITOMEN])
            continue

        zadost = zadost_podle_zamestnance.get(zam.pk)
        if zadost:
            kategorie = zadost.typ.kategorie_pro_prehled
            vysledek[zam.pk] = StavZamestnance(
                kategorie,
                zadost.typ.get_kategorie_pro_prehled_display(),
                _BADGE_TRIDY.get(kategorie, _BADGE_TRIDY[TypDovolene.KategoriePrehled.JINA]),
            )
        else:
            vysledek[zam.pk] = StavZamestnance(NEPRITOMEN, _POPISKY[NEPRITOMEN], _BADGE_TRIDY[NEPRITOMEN])

    return vysledek


def stav_zamestnance(employee, datum) -> StavZamestnance:
    """Stav jednoho zaměstnance k danému dni — viz stavy_zamestnancu()."""
    return stavy_zamestnancu([employee], datum)[employee.pk]
