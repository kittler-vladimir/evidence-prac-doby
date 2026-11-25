"""Podklady pro detail zaměstnance v přehledu Odbor (#123): po dnech zvoleného měsíce
bloky příchod–odchod, pohyby, schválené stavy a uložený denní souhrn jednoho
zaměstnance — vysvětluje čísla, která Odbor ukazuje jen jako měsíční součty.

Nic nepřepočítává: souhrny jsou uložené `WorkdaySummary`, nepřítomnosti dává
`timetracking.nepritomnosti`, součty `timetracking.bilance.secti` (stejně jako Odbor).
"""
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Prefetch
from django.utils import timezone

from accounts.holidays_model import StatniSvatek
from timetracking.models import NEJVETSI_SPOJOVANA_MEZERA, Pohyb, WorkSession, WorkdaySummary
from timetracking.nepritomnosti import nepritomnosti_za_mesic
from timetracking.opravy import je_ze_starsiho_dne

@dataclass
class Mezera:
    """Doba mezi koncem jednoho a začátkem dalšího uzavřeného bloku téhož dne — nepočítá
    se do práce (typicky Odchod + Příchod u lékaře místo pohybu)."""

    od: datetime
    do: datetime
    minuty: int


@dataclass
class PohybDetail:
    pohyb: Pohyb
    zapocitani: str  # hodnota TypPohybu.Zapocitani podle úvazku zaměstnance
    k_oprave: bool  # otevřený a začal před dneškem


@dataclass
class BlokDetail:
    session: WorkSession
    pohyby: list
    mezera_pred: Mezera | None
    probiha: bool
    k_oprave: bool


@dataclass
class DenDetail:
    datum: date
    bloky: list = field(default_factory=list)
    nepritomnosti: list = field(default_factory=list)
    souhrn: WorkdaySummary | None = None
    je_svatek: bool = False
    je_vikend: bool = False

    @property
    def pohyby(self):
        return [p for blok in self.bloky for p in blok.pohyby]


def _minuta(dt):
    return dt.replace(second=0, microsecond=0)


def _rozsah_mesice(rok, mesic):
    prvni = date(rok, mesic, 1)
    posledni = date(rok, mesic, monthrange(rok, mesic)[1])
    od = timezone.make_aware(datetime.combine(prvni, time.min))
    do = timezone.make_aware(datetime.combine(posledni + timedelta(days=1), time.min))
    return prvni, posledni, od, do


def dny_zamestnance(employee, rok, mesic):
    """`[DenDetail]` chronologicky — jen dny měsíce, kdy zaměstnanec má blok, souhrn
    nebo schválenou nepřítomnost. Počet dotazů nezávisí na počtu dní."""
    prvni, posledni, od, do = _rozsah_mesice(rok, mesic)

    sessions = (
        WorkSession.objects.filter(employee=employee, zacatek__gte=od, zacatek__lt=do)
        .prefetch_related(Prefetch(
            "pohyby", queryset=Pohyb.objects.select_related("typ").order_by("zacatek"),
        ))
        .order_by("zacatek")
    )
    souhrny = {
        s.datum: s
        for s in WorkdaySummary.objects.filter(employee=employee, datum__range=(prvni, posledni))
    }
    nepritomnosti = nepritomnosti_za_mesic([employee], rok, mesic).get(employee.pk, {})
    svatky = set(
        StatniSvatek.objects.filter(datum__range=(prvni, posledni)).values_list("datum", flat=True)
    )

    bloky_podle_dne = {}
    for session in sessions:
        bloky = bloky_podle_dne.setdefault(timezone.localdate(session.zacatek), [])
        predchozi = bloky[-1].session if bloky else None
        mezera = None
        if predchozi and predchozi.konec:
            rozdil = _minuta(session.zacatek) - _minuta(predchozi.konec)
            if rozdil > NEJVETSI_SPOJOVANA_MEZERA:
                mezera = Mezera(predchozi.konec, session.zacatek, int(rozdil.total_seconds() // 60))
        bloky.append(BlokDetail(
            session=session,
            pohyby=[
                PohybDetail(
                    pohyb=p,
                    zapocitani=p.typ.zapocitani_pro(employee.typ_uvazku),
                    k_oprave=p.konec is None and je_ze_starsiho_dne(p.zacatek),
                )
                for p in session.pohyby.all()
            ],
            mezera_pred=mezera,
            probiha=session.konec is None and not je_ze_starsiho_dne(session.zacatek),
            k_oprave=session.konec is None and je_ze_starsiho_dne(session.zacatek),
        ))

    dny = set(bloky_podle_dne) | set(souhrny) | set(nepritomnosti)
    return [
        DenDetail(
            datum=den,
            bloky=bloky_podle_dne.get(den, []),
            nepritomnosti=nepritomnosti.get(den, []),
            souhrn=souhrny.get(den),
            je_svatek=den in svatky,
            je_vikend=den.weekday() >= 5,
        )
        for den in sorted(dny)
    ]
