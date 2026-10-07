"""Výběr měsíce a roku měsíčních přehledů (Výkaz, Odbor, export XLSX) — jediné místo,
které čte GET parametry `rok` a `mesic`, takže se stránky a export nemůžou rozejít (#87)."""
from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Min
from django.utils import timezone

from .models import WorkdaySummary

NAZVY_MESICU = [
    "", "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec",
]


def _posun(rok, mesic, o):
    """(rok, měsíc) posunuté o `o` měsíců."""
    index = rok * 12 + (mesic - 1) + o
    return index // 12, index % 12 + 1


@dataclass
class Obdobi:
    """Zvolený měsíc přehledu a povolený rozsah (od měsíce prvních dat po aktuální měsíc)."""

    rok: int
    mesic: int
    prvni: tuple
    aktualni: tuple
    ostatni_parametry: list  # (název, hodnota) ostatních GET parametrů — např. filtr Odboru

    @property
    def nazev(self):
        return f"{NAZVY_MESICU[self.mesic]} {self.rok}"

    @property
    def je_aktualni(self):
        return (self.rok, self.mesic) == self.aktualni

    @property
    def predchozi(self):
        """(rok, měsíc) předchozího měsíce, nebo None na prvním povoleném měsíci."""
        cil = _posun(self.rok, self.mesic, -1)
        return cil if cil >= self.prvni else None

    @property
    def dalsi(self):
        """(rok, měsíc) dalšího měsíce, nebo None na aktuálním měsíci."""
        cil = _posun(self.rok, self.mesic, 1)
        return cil if cil <= self.aktualni else None

    def _query(self, rok=None, mesic=None):
        parametry = list(self.ostatni_parametry)
        if rok is not None:
            parametry += [("rok", rok), ("mesic", mesic)]
        return "?" + urlencode(parametry)

    @property
    def url_predchozi(self):
        return self._query(*self.predchozi) if self.predchozi else None

    @property
    def url_dalsi(self):
        return self._query(*self.dalsi) if self.dalsi else None

    @property
    def url_dnes(self):
        return self._query()

    @property
    def roky(self):
        return list(range(self.prvni[0], self.aktualni[0] + 1))

    @property
    def rozsah_pro_skript(self):
        """Povolený rozsah a názvy měsíců pro skript, který při změně roku přepočítá nabídku
        měsíců — jinak by zůstal vybraný měsíc, který zvolený rok nenabízí (např. leden
        v prvním roce dat), a stránka by spadla na aktuální měsíc."""
        return {
            "prvni": list(self.prvni),
            "aktualni": list(self.aktualni),
            "mesice": NAZVY_MESICU,
        }

    @property
    def mesice(self):
        """Měsíce nabízené ve vybraném roce: v prvním a aktuálním roce jen povolené."""
        od = self.prvni[1] if self.rok == self.prvni[0] else 1
        do = self.aktualni[1] if self.rok == self.aktualni[0] else 12
        return [(m, NAZVY_MESICU[m]) for m in range(od, do + 1)]


def _cislo(request, nazev, vychozi):
    hodnota = request.GET.get(nazev)
    if hodnota in (None, ""):
        return vychozi
    try:
        return int(hodnota)
    except ValueError:
        return None


def zvolene_obdobi(request):
    """Měsíc a rok z GET parametrů `rok`/`mesic`. Chybějící hodnota = aktuální měsíc či rok;
    nečíselná hodnota, měsíc mimo 1–12 nebo měsíc mimo povolený rozsah (před prvními daty
    nebo v budoucnosti) se bere jako aktuální měsíc — stránka nikdy nespadne."""
    dnes = timezone.localdate()
    aktualni = (dnes.year, dnes.month)

    nejstarsi = WorkdaySummary.objects.aggregate(Min("datum"))["datum__min"]
    prvni = (nejstarsi.year, nejstarsi.month) if nejstarsi else aktualni
    prvni = min(prvni, aktualni)

    rok = _cislo(request, "rok", dnes.year)
    mesic = _cislo(request, "mesic", dnes.month)
    if rok is None or mesic is None or not 1 <= mesic <= 12 or not prvni <= (rok, mesic) <= aktualni:
        rok, mesic = aktualni

    ostatni = [
        (nazev, hodnota)
        for nazev, hodnoty in request.GET.lists()
        if nazev not in ("rok", "mesic")
        for hodnota in hodnoty
    ]
    return Obdobi(rok=rok, mesic=mesic, prvni=prvni, aktualni=aktualni, ostatni_parametry=ostatni)
