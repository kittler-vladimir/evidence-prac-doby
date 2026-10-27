"""Nepřítomnosti ve měsíčních přehledech (Výkaz, Odbor, export XLSX) — jediné místo,
které ze schválených ZadostOStav skládá `{datum: [nepřítomnost]}` za měsíc, takže se
tři výstupy nemůžou rozejít (#117). Hodiny po dnech dává `ZadostOStav.hodiny_po_dnech()`
(ne `pocet_hodin`, ten u starších žádostí odpovídá dřívějšímu výpočtu)."""
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date

from accounts.holidays_model import StatniSvatek
from leaves.models import TypStavu, ZadostOStav


@dataclass(frozen=True)
class NepritomnostDne:
    """Jedna nepřítomnost (nebo přítomnost mimo pracoviště) zaměstnance v jednom dni."""

    typ: TypStavu
    minuty: int
    po_hodinach: bool
    casy: str  # "9:00–11:30" u hodinové žádosti jednodenní, jinak ""

    @property
    def je_pritomnost(self):
        return self.typ.je_pritomnost


@dataclass
class SouhrnTypu:
    """Měsíční součet jednoho typu: dny z celodenních žádostí, minuty ze všech."""

    typ: TypStavu
    dny: int = 0
    minuty: int = 0


@dataclass
class DenBezDochazky:
    """Řádek Výkazu pro den s nepřítomností, ale bez WorkdaySummary. Nese stejná pole,
    která Výkaz/`rozdel_na_tydny` čtou ze souhrnu, s nulami — do bilance nepřispívá."""

    datum: date
    nepritomnosti: list = field(default_factory=list)
    odpracovane_minuty: int = 0
    denni_prescas_minuty: int = 0
    denni_nedostatek_minuty: int = 0
    je_svatek: bool = False
    je_vikend: bool = False
    je_zapocitan: bool = False


def _casy(zadost):
    if not zadost.je_po_hodinach or zadost.datum_od != zadost.datum_do:
        return ""
    return f"{zadost.cas_od.hour}:{zadost.cas_od.minute:02d}–{zadost.cas_do.hour}:{zadost.cas_do.minute:02d}"


def nepritomnosti_za_mesic(zamestnanci, rok, mesic):
    """`{employee_id: {datum: [NepritomnostDne]}}` ze schválených žádostí (i
    samoschválených) zaměstnanců, jen dny zvoleného měsíce. Zaměstnanec bez
    nepřítomnosti v klíčích není. Dotazy: žádosti, svátky, a to co si
    `hodiny_po_dnech()` bere samo (u pevné doby bloky úvazku)."""
    zamestnanci = list(zamestnanci)
    if not zamestnanci:
        return {}

    prvni = date(rok, mesic, 1)
    posledni = date(rok, mesic, monthrange(rok, mesic)[1])

    zadosti = (
        ZadostOStav.objects
        .filter(
            employee__in=zamestnanci, stav=ZadostOStav.Stav.SCHVALENO,
            datum_od__lte=posledni, datum_do__gte=prvni,
        )
        .select_related("typ", "employee__typ_uvazku")
    )
    svatky = set(
        StatniSvatek.objects.filter(datum__gte=prvni, datum__lte=posledni)
        .values_list("datum", flat=True)
    )

    vysledek = {}
    for zadost in zadosti:
        for den, minuty in zadost.hodiny_po_dnech(svatky=svatky).items():
            if not prvni <= den <= posledni:
                continue
            vysledek.setdefault(zadost.employee_id, {}).setdefault(den, []).append(
                NepritomnostDne(zadost.typ, minuty, zadost.je_po_hodinach, _casy(zadost))
            )

    for dny in vysledek.values():
        for polozky in dny.values():
            polozky.sort(key=lambda n: (n.je_pritomnost, n.typ.zkratka))
    return vysledek


def souhrn_podle_typu(dny):
    """`{typ.pk: SouhrnTypu}` z `{datum: [NepritomnostDne]}` jednoho zaměstnance."""
    souhrn = {}
    dny_celodenni = {}
    for den, polozky in dny.items():
        for n in polozky:
            radek = souhrn.setdefault(n.typ.pk, SouhrnTypu(n.typ))
            radek.minuty += n.minuty
            if not n.po_hodinach:
                dny_celodenni.setdefault(n.typ.pk, set()).add(den)
    for pk, datumy in dny_celodenni.items():
        souhrn[pk].dny = len(datumy)
    return souhrn


def typy_pro_souhrn(pouzite_typy=()):
    """Typy stavu do souhrnu: všechny aktivní plus použité neaktivní; nejdřív skutečné
    nepřítomnosti, pak přítomnost mimo pracoviště (home office)."""
    typy = {t.pk: t for t in TypStavu.objects.filter(aktivni=True)}
    for typ in pouzite_typy:
        typy.setdefault(typ.pk, typ)
    return sorted(typy.values(), key=lambda t: (t.je_pritomnost, t.nazev))


def typy_sloupcu(souhrny):
    """Typy použité alespoň v jednom z `souhrny` (každý je výstup `souhrn_podle_typu`),
    seřazené jako v souhrnu: nepřítomnosti, pak přítomnost mimo pracoviště."""
    pouzite = {pk: r.typ for souhrn in souhrny for pk, r in souhrn.items()}
    return sorted(pouzite.values(), key=lambda t: (t.je_pritomnost, t.nazev))


def radky_souhrnu(souhrn):
    """Řádky souhrnu pro Výkaz a XLSX: `(nepritomnosti, pritomnost_mimo_pracoviste)`,
    obě jako `[SouhrnTypu]` přes všechny aktivní typy (nepoužité s nulami)."""
    typy = typy_pro_souhrn(r.typ for r in souhrn.values())
    radky = [souhrn.get(t.pk) or SouhrnTypu(t) for t in typy]
    return (
        [r for r in radky if not r.typ.je_pritomnost],
        [r for r in radky if r.typ.je_pritomnost],
    )


def radky_vykazu(souhrny, dny):
    """Řádky Výkazu: souhrny dní s docházkou (každému přibude `.nepritomnosti`) plus
    `DenBezDochazky` pro dny s nepřítomností bez souhrnu, chronologicky."""
    radky = []
    ma_souhrn = set()
    for souhrn in souhrny:
        souhrn.nepritomnosti = dny.get(souhrn.datum, [])
        ma_souhrn.add(souhrn.datum)
        radky.append(souhrn)
    for den, polozky in dny.items():
        if den not in ma_souhrn:
            radky.append(DenBezDochazky(den, polozky))
    radky.sort(key=lambda r: r.datum)
    return radky
