"""
Bilance odpracované doby vůči denní normě: formátování minut a součty
za ISO týden a měsíc.

WorkdaySummary.prescos_minuty je podepsaný rozdíl proti normě; přesčas
(kladné dny) a nedostatek (záporné dny) se z něj odvozují až při zobrazení
(WorkdaySummary.denni_prescas_minuty / denni_nedostatek_minuty).
"""
from dataclasses import dataclass
from datetime import date, timedelta

MINUS = "−"


def format_minut(minuty, se_znamenkem=False):
    """'Xh Ymin' z absolutní hodnoty; záporná hodnota dostane '−' jen se se_znamenkem."""
    hodiny, zbytek = divmod(abs(int(minuty)), 60)
    text = f"{hodiny}h {zbytek}min"
    if se_znamenkem and minuty < 0:
        return f"{MINUS}{text}"
    return text


@dataclass
class Bilance:
    prescas: int = 0
    nedostatek: int = 0

    @property
    def bilance(self):
        return self.prescas - self.nedostatek


def secti(souhrny):
    vysledek = Bilance()
    for souhrn in souhrny:
        vysledek.prescas += souhrn.denni_prescas_minuty
        vysledek.nedostatek += souhrn.denni_nedostatek_minuty
    return vysledek


@dataclass
class Tyden:
    cislo: int
    od: date
    do: date
    souhrny: list
    bilance: Bilance


def rozdel_na_tydny(souhrny, rok, mesic):
    """
    Seskupí denní souhrny jednoho měsíce podle ISO týdne (v chronologickém
    pořadí; týdny bez záznamů se vynechají). Týden zasahující do sousedního
    měsíce se sčítá jen přes dny zobrazeného měsíce, proto se jeho rozsah
    (od–do) ořízne na hranice měsíce.
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok + (mesic == 12), mesic % 12 + 1, 1) - timedelta(days=1)

    skupiny = {}
    for souhrn in sorted(souhrny, key=lambda s: s.datum):
        iso_rok, iso_tyden, _ = souhrn.datum.isocalendar()
        skupiny.setdefault((iso_rok, iso_tyden), []).append(souhrn)

    tydny = []
    for (iso_rok, iso_tyden), radky in skupiny.items():
        pondeli = date.fromisocalendar(iso_rok, iso_tyden, 1)
        tydny.append(Tyden(
            cislo=iso_tyden,
            od=max(pondeli, prvni_den),
            do=min(pondeli + timedelta(days=6), posledni_den),
            souhrny=radky,
            bilance=secti(radky),
        ))
    return tydny
