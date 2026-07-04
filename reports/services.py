from dataclasses import dataclass

from django.utils import timezone

from leaves.models import ZadostOStav
from timetracking.models import WorkSession

PRITOMEN = "PRITOMEN"
NEPRITOMEN = "NEPRITOMEN"

_BADGE_TRIDY = {
    PRITOMEN: "bg-success",
    NEPRITOMEN: "bg-dark",
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
    barva: str = ""


def _stav_z_typu(typ) -> StavZamestnance:
    """Odznak/popisek platného záznamu čerpá přímo z daného TypStavu — nový
    typ založený jen v adminu (bez odkazu na KategoriePrehled) tak funguje
    bez jakéhokoli zásahu do kódu. Záložní bg-secondary pro případ, že by
    typ měl prázdnou barvu."""
    return StavZamestnance(typ.zkratka, typ.nazev, "bg-secondary" if not typ.barva else "", typ.barva)


def stavy_zamestnancu(zamestnanci, datum) -> dict:
    """
    Vrátí {employee_id: StavZamestnance} pro danou skupinu zaměstnanců a datum,
    jednou dávkou (2 dotazy celkem, ne 2 na zaměstnance).

    Pravidlo priority: platný záznam typu přítomnosti (TypStavu.je_pritomnost,
    např. home office) > Přítomen (dle WorkSession) > platný záznam typu
    nepřítomnosti > Nepřítomen. "Platný" = stav SCHVALENO, ať už schválením
    vedoucím, nebo automaticky u typů se samo-záznamem (vyzaduje_schvaleni=False).

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

    zaznamy_podle_zamestnance = {}
    zaznamy = ZadostOStav.objects.filter(
        employee__in=zamestnanci,
        stav=ZadostOStav.Stav.SCHVALENO,
        datum_od__lte=datum,
        datum_do__gte=datum,
    ).select_related("typ").order_by("-vytvoreno")
    for zaznam in zaznamy:
        zaznamy_podle_zamestnance.setdefault(zaznam.employee_id, []).append(zaznam)

    vysledek = {}
    for zam in zamestnanci:
        zaznamy_zam = zaznamy_podle_zamestnance.get(zam.pk, [])

        pritomnostni_zaznam = next((z for z in zaznamy_zam if z.typ.je_pritomnost), None)
        if pritomnostni_zaznam:
            vysledek[zam.pk] = _stav_z_typu(pritomnostni_zaznam.typ)
            continue

        if zam.pk in pritomni_ids:
            vysledek[zam.pk] = StavZamestnance(PRITOMEN, _POPISKY[PRITOMEN], _BADGE_TRIDY[PRITOMEN])
            continue

        if zaznamy_zam:
            vysledek[zam.pk] = _stav_z_typu(zaznamy_zam[0].typ)
        else:
            vysledek[zam.pk] = StavZamestnance(NEPRITOMEN, _POPISKY[NEPRITOMEN], _BADGE_TRIDY[NEPRITOMEN])

    return vysledek


def stav_zamestnance(employee, datum) -> StavZamestnance:
    """Stav jednoho zaměstnance k danému dni — viz stavy_zamestnancu()."""
    return stavy_zamestnancu([employee], datum)[employee.pk]
