from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone


class TypStavu(models.Model):
    """
    Číselník typů stavu zaměstnance v daný okamžik (dovolená, nemoc,
    indispoziční volno, home office...). Dovolená je jen jednou instancí
    tohoto obecného konceptu, ne výchozím případem.
    """

    class KategoriePrehled(models.TextChoices):
        DOVOLENA = "DOVOLENA", _("Dovolená")
        NEMOC = "NEMOC", _("Nemoc")
        INDISPOZICNI_VOLNO = "INDISPOZICNI_VOLNO", _("Indispoziční volno")
        SLUZEBNI_VOLNO = "SLUZEBNI_VOLNO", _("Služební volno")
        OCR = "OCR", _("Ošetřování člena rodiny")
        JINA = "JINA", _("Jiná absence")

    nazev = models.CharField(_("název"), max_length=100)
    zkratka = models.CharField(_("zkratka"), max_length=10)
    odecita_ze_zustatku = models.BooleanField(
        _("odečítá ze zůstatku"),
        default=True,
        help_text=_(
            "Schválená žádost se odečte z ročního zůstatku tohoto typu "
            "(např. dovolená, indispoziční volno). Např. nemoc se neodečítá."
        ),
    )
    je_indispozicni_volno = models.BooleanField(
        _("je indispoziční volno"),
        default=False,
        help_text=_(
            "Nárok se pro tento typ automaticky dosazuje z globálního "
            "nastavení (NarokIndispozicnihoVolna), ne ručně na zaměstnance."
        ),
    )
    je_dovolena = models.BooleanField(
        _("je dovolená"),
        default=False,
        help_text=_(
            "Nárok se pro tento typ každý rok automaticky aktualizuje "
            "(zbytek z minulého roku + roční nárok z NarokDovolene) "
            "příkazem obnov_rocni_naroky."
        ),
    )
    vyzaduje_schvaleni = models.BooleanField(
        _("vyžaduje schválení"),
        default=True,
        help_text=_(
            "Zapnuto: zaměstnanec podává žádost, kterou schvaluje vedoucí "
            "(dovolená, indispoziční volno). Vypnuto: zaměstnanec si stav "
            "zapisuje sám na daný den/rozsah, bez schvalování (např. "
            "nemoc, OČR, služební volno, home office)."
        ),
    )
    je_pritomnost = models.BooleanField(
        _("je přítomnost"),
        default=False,
        help_text=_(
            "Zapnuto u typů, kdy zaměstnanec pracuje, jen ne na pracovišti "
            "(např. home office) — v denním přehledu má přednost i před "
            "běžným „Přítomen“ na základě docházky. Vypnuto u typů "
            "nepřítomnosti na pracovišti."
        ),
    )
    umoznuje_zadani_po_hodinach = models.BooleanField(
        _("umožňuje zadání po hodinách"),
        default=False,
        help_text=_(
            "Zapnuto: u žádosti tohoto typu lze místo celých dnů zadat čas "
            "od–do. Ve výchozím stavu je zapnuto jen u dovolené."
        ),
    )
    kategorie_pro_prehled = models.CharField(
        _("kategorie pro přehled přítomnosti"),
        max_length=20,
        choices=KategoriePrehled.choices,
        default=KategoriePrehled.JINA,
        help_text=_(
            "Volitelné hrubé třídění pro administraci. Zobrazení a priorita "
            "v denním přehledu přítomnosti na tomto poli nezávisí — vychází "
            "přímo z názvu/barvy tohoto typu a z pole „je přítomnost“."
        ),
    )
    barva = models.CharField(
        _("barva (hex)"), max_length=7, default="#4A90E2",
        help_text=_("Barva pro zobrazení v kalendáři a v denním přehledu přítomnosti."),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ stavu")
        verbose_name_plural = _("typy stavu")

    def __str__(self):
        return f"{self.zkratka} – {self.nazev}"

    def clean(self):
        je_iv_kategorie = self.kategorie_pro_prehled == self.KategoriePrehled.INDISPOZICNI_VOLNO
        if self.je_indispozicni_volno and not je_iv_kategorie:
            raise ValidationError(
                _(
                    "Typ označený jako indispoziční volno musí mít kategorii pro "
                    "přehled nastavenou na „Indispoziční volno“."
                )
            )
        if je_iv_kategorie and not self.je_indispozicni_volno:
            raise ValidationError(
                _(
                    "Kategorii pro přehled „Indispoziční volno“ smí mít jen typ "
                    "označený jako indispoziční volno."
                )
            )
        je_dovolena_kategorie = self.kategorie_pro_prehled == self.KategoriePrehled.DOVOLENA
        if self.je_dovolena and not je_dovolena_kategorie:
            raise ValidationError(
                _(
                    "Typ označený jako dovolená musí mít kategorii pro přehled "
                    "nastavenou na „Dovolená“."
                )
            )
        if je_dovolena_kategorie and not self.je_dovolena:
            raise ValidationError(
                _(
                    "Kategorii pro přehled „Dovolená“ smí mít jen typ označený "
                    "jako dovolená."
                )
            )
        if self.odecita_ze_zustatku and not self.vyzaduje_schvaleni:
            raise ValidationError(
                _(
                    "Typ, který odečítá ze zůstatku, musí vyžadovat schválení — "
                    "zůstatek se aktualizuje jen při schválení vedoucím "
                    "(ZadostOStav.schval()), samo-záznam ho nikdy neupraví."
                )
            )

    def vychozi_narok(self, datum):
        """
        Výchozí nárok pro nově zakládaný zůstatek tohoto typu k danému datu.
        U indispozičního volna a dovolené se dosazuje z globálního nastavení
        (bez zbytku z minulého roku — ten řeší jen roční příkaz
        obnov_rocni_naroky); u ostatních typů zůstává 0 (admin zůstatek pro
        daný rok zakládá ručně).
        """
        if self.je_indispozicni_volno:
            return NarokIndispozicnihoVolna.aktivni_hodnota(datum)
        if self.je_dovolena:
            return NarokDovolene.aktivni_hodnota(datum)
        return Decimal("0")


class NarokIndispozicnihoVolna(models.Model):
    """
    Globální (nikoli individuální) nárok na indispoziční volno v hodinách.
    Platí pro všechny zaměstnance stejně; hodnota může být admin průběžně
    měněna, vždy s platností od zadaného data (bez zpětného přepočtu už
    vytvořených zůstatků).
    """
    hodin = models.DecimalField(_("hodin"), max_digits=6, decimal_places=2)
    platne_od = models.DateField(_("platné od"))

    class Meta:
        verbose_name = _("nárok na indispoziční volno")
        verbose_name_plural = _("nárok na indispoziční volno")
        ordering = ["-platne_od"]

    def __str__(self):
        return f"{self.hodin}h od {self.platne_od}"

    @classmethod
    def aktivni_hodnota(cls, datum):
        """Vrátí nárok v hodinách platný k danému datu (nejnovější platné_od <= datum)."""
        radek = cls.objects.filter(platne_od__lte=datum).order_by("-platne_od").first()
        return radek.hodin if radek else Decimal("0")


class NarokDovolene(models.Model):
    """
    Globální (nikoli individuální) roční nárok na dovolenou v hodinách.
    Platí pro všechny zaměstnance stejně; hodnota může být admin průběžně
    měněna, vždy s platností od zadaného data (bez zpětného přepočtu už
    vytvořených zůstatků). Na rozdíl od indispozičního volna se při ročním
    obnovení (obnov_rocni_naroky) k této hodnotě navíc připočítává zbytek
    nevyčerpané dovolené z předchozího roku.
    """
    hodin = models.DecimalField(_("hodin"), max_digits=6, decimal_places=2)
    platne_od = models.DateField(_("platné od"))

    class Meta:
        verbose_name = _("nárok na dovolenou")
        verbose_name_plural = _("nárok na dovolenou")
        ordering = ["-platne_od"]

    def __str__(self):
        return f"{self.hodin}h od {self.platne_od}"

    @classmethod
    def aktivni_hodnota(cls, datum):
        """Vrátí nárok v hodinách platný k danému datu (nejnovější platné_od <= datum)."""
        radek = cls.objects.filter(platne_od__lte=datum).order_by("-platne_od").first()
        return radek.hodin if radek else Decimal("0")


class ZustatekStavu(models.Model):
    """Nárok a čerpání v hodinách pro daného zaměstnance, rok a typ stavu."""

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="zustatky_stavu",
        verbose_name=_("zaměstnanec"),
    )
    rok = models.PositiveSmallIntegerField(_("rok"))
    typ = models.ForeignKey(
        TypStavu,
        on_delete=models.PROTECT,
        related_name="zustatky",
        verbose_name=_("typ"),
    )
    narok_hodin = models.DecimalField(
        _("nárok (hod)"), max_digits=6, decimal_places=2, default=0
    )
    cerpano_hodin = models.DecimalField(
        _("čerpáno (hod)"), max_digits=6, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = _("zůstatek stavu")
        verbose_name_plural = _("zůstatky stavu")
        unique_together = [("employee", "rok", "typ")]
        ordering = ["-rok"]

    def __str__(self):
        return (
            f"{self.employee} | {self.rok} | {self.typ.zkratka} | "
            f"zbývá {self.zbyvajici_hodin}h"
        )

    @property
    def zbyvajici_hodin(self):
        return self.narok_hodin - self.cerpano_hodin


class ZadostOStav(models.Model):
    """
    Žádost o stav (typy s vyzaduje_schvaleni=True, např. dovolená,
    indispoziční volno) nebo samo-záznam stavu (vyzaduje_schvaleni=False,
    např. nemoc, OČR, služební volno, home office) — stejná struktura,
    liší se jen tím, jestli prochází schválením vedoucím.
    """

    class Stav(models.TextChoices):
        CEKA = "ceka", _("Čeká na schválení")
        SCHVALENO = "schvaleno", _("Schváleno")
        ZAMITNUTO = "zamitnuto", _("Zamítnuto")
        STORNOVÁNO = "stornovano", _("Stornováno")

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="zadosti_o_stav",
        verbose_name=_("zaměstnanec"),
    )
    typ = models.ForeignKey(
        TypStavu,
        on_delete=models.PROTECT,
        verbose_name=_("typ"),
    )
    datum_od = models.DateField(_("datum od"))
    datum_do = models.DateField(_("datum do"))
    # Volitelný čas od–do (jen u typů s umoznuje_zadani_po_hodinach): vyplněné oba
    # = hodinová žádost, prázdné oba = celé dny jako dřív.
    cas_od = models.TimeField(_("čas od"), null=True, blank=True)
    cas_do = models.TimeField(_("čas do"), null=True, blank=True)

    # Počet hodin se vypočítá při uložení (pracovní dny × hod/den dle úvazku, bez svátků)
    pocet_hodin = models.DecimalField(
        _("počet hodin"), max_digits=6, decimal_places=2, default=0
    )

    stav = models.CharField(
        _("stav"),
        max_length=12,
        choices=Stav.choices,
        default=Stav.CEKA,
    )
    schvalovatele = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ke_schvaleni",
        verbose_name=_("schvaluje"),
    )
    schvaleno_kym = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schvalil_zadosti",
        verbose_name=_("schválil"),
    )
    schvaleno_kdy = models.DateTimeField(_("schváleno kdy"), null=True, blank=True)
    samoschvaleno = models.BooleanField(
        _("schváleno vlastní osobou"), default=False,
        help_text=_("Schvalovatel schválil vlastní žádost ve výjimečném případě (důvod je v poznámce schvalovatele)."),
    )
    poznamka_zamestnance = models.TextField(_("poznámka zaměstnance"), blank=True)
    poznamka_schvalovatele = models.TextField(_("poznámka schvalovatele"), blank=True)
    vytvoreno = models.DateTimeField(_("vytvořeno"), auto_now_add=True)
    upraveno = models.DateTimeField(_("upraveno"), auto_now=True)

    class Meta:
        verbose_name = _("žádost o stav")
        verbose_name_plural = _("žádosti o stav")
        ordering = ["-vytvoreno"]

    def __str__(self):
        return (
            f"{self.employee} | {self.typ.zkratka} | "
            f"{self.datum_od} – {self.datum_do} | {self.get_stav_display()}"
        )

    @property
    def je_po_hodinach(self):
        """Hodinová žádost (čas od–do vyplněný), ne celé dny."""
        return self.cas_od is not None and self.cas_do is not None

    @staticmethod
    def _minuty_dne(cas):
        return cas.hour * 60 + cas.minute

    def popis_rozsahu(self):
        """Rozsah žádosti pro hlášky, např. „12. 10. 2026 9:00–11:30“."""
        def den(d):
            return f"{d.day}. {d.month}. {d.year}"

        def cas(t):
            return f"{t.hour}:{t.minute:02d}"

        if not self.je_po_hodinach:
            if self.datum_od == self.datum_do:
                return den(self.datum_od)
            return f"{den(self.datum_od)} – {den(self.datum_do)}"
        if self.datum_od == self.datum_do:
            return f"{den(self.datum_od)} {cas(self.cas_od)}–{cas(self.cas_do)}"
        return f"{den(self.datum_od)} {cas(self.cas_od)} – {den(self.datum_do)} {cas(self.cas_do)}"

    def hodiny_po_dnech(self, svatky=None):
        """Minuty dovolené po jednotlivých dnech rozsahu: `{datum: minuty}` jen pro dny
        Po–Pá bez státního svátku, ve kterých je něco k započítání. Jediné místo, ze
        kterého čerpá `vypocitej_hodiny()` i kontroly součtu za den. `svatky` (množina
        dat) volající předá, když počítá víc žádostí najednou (měsíční přehledy) — jinak
        se načtou z databáze pro tuto žádost.

        Celé dny: denní norma (`TypUvazku.norma_minut`). Hodinová žádost na jeden den:
        rozdíl `cas_do − cas_od`. Hodinová žádost přes více dnů (pevná doba) je souvislý
        interval: první den od `cas_od` do konce pracovního dne (`TypUvazku.okno_dne`),
        poslední den od začátku pracovního dne do `cas_do`, dny mezi nimi celá norma.
        Každý den nejvýš do své normy."""
        from accounts.holidays_model import StatniSvatek
        from datetime import timedelta

        if not (self.datum_od and self.datum_do and self.employee_id):
            return {}

        if svatky is None:
            svatky = set(
                StatniSvatek.objects.filter(
                    datum__gte=self.datum_od, datum__lte=self.datum_do,
                ).values_list("datum", flat=True)
            )
        typ_uvazku = self.employee.typ_uvazku
        po_hodinach = self.je_po_hodinach
        jeden_den = self.datum_od == self.datum_do

        dny = {}
        den = self.datum_od
        while den <= self.datum_do:
            if den.weekday() < 5 and den not in svatky:
                norma = typ_uvazku.norma_minut(den)
                minuty = norma
                if po_hodinach:
                    od = self._minuty_dne(self.cas_od)
                    do = self._minuty_dne(self.cas_do)
                    okno = typ_uvazku.okno_dne(den)
                    if jeden_den or okno is None:
                        minuty = do - od
                    elif den == self.datum_od:
                        minuty = self._minuty_dne(okno[1]) - od
                    elif den == self.datum_do:
                        minuty = do - self._minuty_dne(okno[0])
                minuty = min(minuty, norma)
                if minuty > 0:
                    dny[den] = minuty
            den += timedelta(days=1)
        return dny

    def intervaly_po_dnech(self):
        """Časové okno žádosti v každém započítaném dni jako `{datum: (od_min, do_min)}`
        v minutách od půlnoci — celé dny zabírají celý den (0–1440)."""
        intervaly = {}
        for den in self.hodiny_po_dnech():
            if not self.je_po_hodinach:
                intervaly[den] = (0, 1440)
            elif self.datum_od == self.datum_do:
                intervaly[den] = (self._minuty_dne(self.cas_od), self._minuty_dne(self.cas_do))
            elif den == self.datum_od:
                intervaly[den] = (self._minuty_dne(self.cas_od), 1440)
            elif den == self.datum_do:
                intervaly[den] = (0, self._minuty_dne(self.cas_do))
            else:
                intervaly[den] = (0, 1440)
        return intervaly

    def clean(self):
        if self.datum_od and self.datum_do and self.datum_do < self.datum_od:
            raise ValidationError(_("Datum do musí být po datu od."))
        self._zkontroluj_hodinovou_zadost()

    def _zkontroluj_hodinovou_zadost(self):
        """Pravidla hodinové dovolené (#82): čas od i do zároveň, jen u typů s příznakem,
        pružná doba jen v rámci jednoho dne, aspoň jeden započítaný den, žádné časové
        překryvy s jinou žádostí a součet za den do denní normy."""
        from accounts.models import TypUvazku

        if (self.cas_od is None) != (self.cas_do is None):
            raise ValidationError(_("Vyplňte čas od i čas do, nebo ani jeden z nich."))

        po_hodinach = self.je_po_hodinach
        if po_hodinach:
            if self.typ_id and not self.typ.umoznuje_zadani_po_hodinach:
                raise ValidationError(
                    _("Typ „%(typ)s“ nelze zadat po hodinách.") % {"typ": self.typ.nazev}
                )
            if (
                self.datum_od and self.datum_do and self.datum_od == self.datum_do
                and self.cas_do <= self.cas_od
            ):
                raise ValidationError(_("Čas do musí být po čase od."))

        if not (self.employee_id and self.datum_od and self.datum_do):
            return

        if po_hodinach and self.datum_od != self.datum_do and (
            self.employee.typ_uvazku.druh_pracovni_doby != TypUvazku.DruhPracovniDoby.PEVNA
        ):
            raise ValidationError(
                _("U pružné pracovní doby lze hodinovou žádost zadat jen v rámci jednoho dne.")
            )

        dny = self.hodiny_po_dnech()
        if po_hodinach and not dny:
            raise ValidationError(_("V zadaném rozsahu není žádný pracovní den."))

        ostatni = list(
            ZadostOStav.objects.filter(
                employee_id=self.employee_id,
                stav__in=[self.Stav.CEKA, self.Stav.SCHVALENO],
                datum_od__lte=self.datum_do,
                datum_do__gte=self.datum_od,
            ).exclude(pk=self.pk).select_related("typ", "employee__typ_uvazku")
        )
        # Kolize hlídáme jen tam, kde je aspoň jedna ze žádostí hodinová — překryv
        # dvou žádostí na celé dny se dosud nehlídá.
        moje_intervaly = self.intervaly_po_dnech()
        for jina in ostatni:
            if not (po_hodinach or jina.je_po_hodinach):
                continue
            for den, (od2, do2) in jina.intervaly_po_dnech().items():
                od1, do1 = moje_intervaly.get(den, (0, 0))
                if od1 < do2 and od2 < do1:
                    raise ValidationError(
                        _("Žádost se časově překrývá s jinou žádostí: %(typ)s, %(rozsah)s.")
                        % {"typ": jina.typ.nazev, "rozsah": jina.popis_rozsahu()}
                    )

        if po_hodinach:
            typ_uvazku = self.employee.typ_uvazku
            for den, minuty in dny.items():
                celkem = minuty + sum(j.hodiny_po_dnech().get(den, 0) for j in ostatni)
                if celkem > typ_uvazku.norma_minut(den):
                    raise ValidationError(
                        _("Součet dovolené za %(den)s by překročil denní normu.")
                        % {"den": f"{den.day}. {den.month}. {den.year}"}
                    )

    @classmethod
    def hodinove_volno_minuty(cls, employee, datum, useky_prace=(), useky_pohybu=()):
        """Minuty schválené hodinové žádosti zaměstnance v daný den (0, když žádná není) —
        `WorkdaySummary.prepocitej()` je přičte k odpracované době (#82).

        `useky_prace` jsou započítané úseky práce dne (aware `(od, do)`), `useky_pohybu`
        z nich odečtené pohyby. Část dovolené, která leží v započítané práci, se vynechá —
        ta už je v odpracované době a jinak by se započítala dvakrát (#97)."""
        def prekryv_minut(od1, do1, od2, do2):
            od, do = max(od1, od2), min(do1, do2)
            return int((do - od).total_seconds() // 60) if do > od else 0

        pulnoc = timezone.make_aware(datetime.combine(datum, time.min))
        zadosti = cls.objects.filter(
            employee=employee,
            stav=cls.Stav.SCHVALENO,
            cas_od__isnull=False,
            cas_do__isnull=False,
            datum_od__lte=datum,
            datum_do__gte=datum,
        ).select_related("employee__typ_uvazku")
        celkem = 0
        for z in zadosti:
            minuty = z.hodiny_po_dnech().get(datum, 0)
            if not minuty:
                continue
            od_min, do_min = z.intervaly_po_dnech()[datum]
            volno_od = pulnoc + timedelta(minutes=od_min)
            volno_do = pulnoc + timedelta(minutes=do_min)
            v_praci = sum(
                prekryv_minut(volno_od, volno_do, od, do) for od, do in useky_prace
            ) - sum(prekryv_minut(volno_od, volno_do, od, do) for od, do in useky_pohybu)
            celkem += max(minuty - v_praci, 0)
        return celkem

    def vypocitej_hodiny(self):
        """
        Spočítá počet hodin žádosti jako součet minut z `hodiny_po_dnech()`:
        pracovní dny v rozsahu (bez víkendů a státních svátků) × denní norma úvazku
        (TypUvazku.norma_minut: pružná doba hodiny_denne, pevná čistá doba bloků dne),
        u hodinové žádosti jen zadaný čas od–do.
        """
        if not (self.datum_od and self.datum_do and self.employee_id):
            return

        minuty = sum(self.hodiny_po_dnech().values())
        self.pocet_hodin = (Decimal(minuty) / 60).quantize(Decimal("0.01"))

    @classmethod
    def konflikty_pro_prichod(cls, employee, cas):
        """Žádosti (čekající i schválené), které kolidují s příchodem v čase `cas` (#100):
        kryjí dnešek jako započítaný den a nejde o typ přítomnosti (home office). U hodinové
        žádosti jen tehdy, když její okno dnes ještě neskončilo před příchodem."""
        mistni = timezone.localtime(cas)
        dnes = mistni.date()
        minuta = mistni.hour * 60 + mistni.minute
        zadosti = cls.objects.filter(
            employee=employee,
            stav__in=[cls.Stav.CEKA, cls.Stav.SCHVALENO],
            datum_od__lte=dnes,
            datum_do__gte=dnes,
            typ__je_pritomnost=False,
        ).select_related("typ", "employee__typ_uvazku").order_by("datum_od", "pk")
        konflikty = []
        for zadost in zadosti:
            if dnes not in zadost.hodiny_po_dnech():
                continue
            if zadost.je_po_hodinach and zadost.intervaly_po_dnech()[dnes][1] <= minuta:
                continue
            konflikty.append(zadost)
        return konflikty

    @property
    def lze_zrusit_jen_dnes(self):
        """Má smysl nabídnout zrušení jen jednoho dne: vícedenní žádost na celé dny.
        Hodinovou žádost (souvislý interval) lze zrušit jen celou."""
        return not self.je_po_hodinach and self.datum_od != self.datum_do

    @property
    def je_rozpracovana(self):
        """Žádost už začala, ale ještě neskončila (dnes je v jejím rozsahu, nezačíná dnes)."""
        dnes = timezone.localdate()
        return self.datum_od < dnes <= self.datum_do

    @property
    def je_skoncena(self):
        return self.datum_do < timezone.localdate()

    @property
    def lze_zrusit_zbyvajici(self):
        """Nabídnout „zrušit zbývající dny“: rozpracovaná žádost na celé dny, které má od
        dneška do konce aspoň jeden pracovní den (#103)."""
        if not self.je_rozpracovana or self.je_po_hodinach:
            return False
        zbytek = ZadostOStav(
            employee=self.employee, typ=self.typ,
            datum_od=timezone.localdate(), datum_do=self.datum_do,
        )
        zbytek.vypocitej_hodiny()
        return zbytek.pocet_hodin > 0

    @property
    def lze_zrusit_pri_prichodu(self):
        """Příchod nabízí zrušení všude kromě rozpracované hodinové žádosti — ta jde zrušit
        jen celá, včetně už proběhlých dnů, a to se nemá stát mimochodem při příchodu."""
        return not (self.je_po_hodinach and self.je_rozpracovana)

    def rozsah_zruseni(self, volba):
        """Rozsah dnů pro volbu zrušení z detailu/příchodu (#103) — vrací `(od, do)`:
        `cely` = celá žádost včetně už proběhlých dnů (None, None), `zbyvajici` = od dneška
        do konce rozpracované žádosti na celé dny, `dnes` = jen dnešek vícedenní žádosti."""
        dnes = timezone.localdate()
        if volba == "cely":
            return None, None
        if volba == "zbyvajici":
            if not self.lze_zrusit_zbyvajici:
                raise ValidationError(_("Zbývající dny lze zrušit jen u rozpracované žádosti."))
            return dnes, self.datum_do
        if volba == "dnes":
            if not (self.lze_zrusit_jen_dnes and self.datum_od <= dnes <= self.datum_do):
                raise ValidationError(_("Tuto žádost lze zrušit jen celou."))
            return dnes, dnes
        raise ValidationError(_("Neplatný rozsah zrušení."))

    def cekajici_zruseni(self):
        """Čekající žádost o zrušení této (schválené) žádosti, nebo None."""
        return self.zadosti_o_zruseni.filter(stav=ZadostOZruseni.Stav.CEKA).first()

    @property
    def ma_cekajici_zruseni(self):
        return self.cekajici_zruseni() is not None

    def _zkontroluj_zruseni(self, od, do):
        """Pravidla zrušení schválené žádosti (#100, #103) — vrací (od, do). Platí při podání
        i při schválení; zrušit lze i už proběhlé dny (zpětně), bez časového limitu."""
        od = od or self.datum_od
        do = do or self.datum_do
        if self.stav != self.Stav.SCHVALENO:
            raise ValidationError(_("Zrušit lze jen schválenou žádost."))
        if od > do or od < self.datum_od or do > self.datum_do:
            raise ValidationError(_("Rozsah zrušení musí ležet uvnitř žádosti."))
        if (od, do) != (self.datum_od, self.datum_do) and self.je_po_hodinach:
            raise ValidationError(_("Hodinovou žádost lze zrušit jen celou."))
        zrusene = ZadostOStav(employee=self.employee, typ=self.typ, datum_od=od, datum_do=do)
        zrusene.vypocitej_hodiny()
        if zrusene.pocet_hodin <= 0 and not self.je_po_hodinach:
            raise ValidationError(_("V rozsahu zrušení není žádný pracovní den."))
        return od, do

    def zrus_nepritomnost(self, od=None, do=None, poznamka=""):
        """Zaměstnanec ruší svou schválenou žádost, celou (i už proběhlou, #103) nebo
        (vícedenní na celé dny) jen dny od–do (#100). Typ bez schvalování se zruší hned
        a vrací None; typ se schvalováním vytvoří žádost o zrušení pro schvalovatele
        a vrací ji."""
        od, do = self._zkontroluj_zruseni(od, do)
        if not self.typ.vyzaduje_schvaleni:
            self.zrus(od, do)
            return None
        if self.cekajici_zruseni():
            raise ValidationError(_("Žádost o zrušení už čeká na schválení."))
        return ZadostOZruseni.objects.create(
            zadost=self, datum_od=od, datum_do=do, poznamka_zamestnance=poznamka,
        )

    def zrus(self, od=None, do=None):
        """Provede zrušení schválené žádosti: celé (stav `stornovano`), nebo jen dny od–do
        vícedenní žádosti na celé dny — ta se rozdělí na zbylé schválené části před a po.
        Hodiny zrušené části se vrátí do zůstatku (jen u typů, kterým je `schval()` odečetl).
        Vrací počet vrácených hodin."""
        od, do = self._zkontroluj_zruseni(od, do)
        with transaction.atomic():
            puvodni_hodiny = self.pocet_hodin
            rok = self.datum_od.year
            useky = []
            if (od, do) != (self.datum_od, self.datum_do):
                for a, b in (
                    (self.datum_od, od - timedelta(days=1)),
                    (do + timedelta(days=1), self.datum_do),
                ):
                    if a > b:
                        continue
                    cast = ZadostOStav(
                        employee=self.employee, typ=self.typ, datum_od=a, datum_do=b,
                    )
                    cast.vypocitej_hodiny()
                    if cast.pocet_hodin > 0:
                        useky.append(cast)

            if not useky:
                self.stav = self.Stav.STORNOVÁNO
                self.save()
                vratit = puvodni_hodiny
            else:
                prvni, *dalsi = useky
                self.datum_od, self.datum_do = prvni.datum_od, prvni.datum_do
                self.pocet_hodin = prvni.pocet_hodin
                self.save()
                for cast in dalsi:
                    cast.stav = self.Stav.SCHVALENO
                    cast.schvalovatele = self.schvalovatele
                    cast.schvaleno_kym = self.schvaleno_kym
                    cast.schvaleno_kdy = self.schvaleno_kdy
                    cast.samoschvaleno = self.samoschvaleno
                    cast.poznamka_zamestnance = self.poznamka_zamestnance
                    cast.poznamka_schvalovatele = self.poznamka_schvalovatele
                    cast._bez_notifikace = True
                    cast.save()
                    # save() u typů bez schvalování přepíše schválení „teď“ — části mají
                    # zachovat audit původní žádosti.
                    ZadostOStav.objects.filter(pk=cast.pk).update(
                        schvaleno_kdy=self.schvaleno_kdy, vytvoreno=self.vytvoreno,
                    )
                vratit = puvodni_hodiny - sum(c.pocet_hodin for c in useky)

            if vratit > 0 and self.typ.vyzaduje_schvaleni and self.typ.odecita_ze_zustatku:
                zustatek = ZustatekStavu.objects.filter(
                    employee=self.employee, rok=rok, typ=self.typ
                ).first()
                if zustatek:
                    zustatek.cerpano_hodin = max(zustatek.cerpano_hodin - vratit, 0)
                    zustatek.save()
        return vratit

    def muze_schvalit_sam(self, employee):
        """Smí `employee` schválit tuto žádost sám sobě (#90)? Jen vlastní čekající žádost
        zaměstnance, který jinak schvaluje žádosti (vedoucí, zástupce)."""
        return bool(
            employee
            and self.employee_id == employee.pk
            and self.stav == self.Stav.CEKA
            and self.typ.vyzaduje_schvaleni
            and employee.schvaluje_zadosti
        )

    def schval(self, schvalovatele, samoschvaleno=False, duvod=""):
        """Schválí žádost a aktualizuje zůstatek stavu. Při `samoschvaleno` se uloží
        důvod do poznámky schvalovatele a žádost se tak označí (#90)."""
        zustatek = None
        if self.typ.odecita_ze_zustatku:
            rok = self.datum_od.year
            zustatek = ZustatekStavu.objects.filter(
                employee=self.employee, rok=rok, typ=self.typ
            ).first()
            if not zustatek:
                narok_default = self.typ.vychozi_narok(self.datum_od)
                if (self.typ.je_indispozicni_volno or self.typ.je_dovolena) and narok_default <= 0:
                    raise ValidationError(
                        _("Pro typ „%(typ)s“ není nastaven žádný aktivní nárok.")
                        % {"typ": self.typ.nazev}
                    )
                zustatek = ZustatekStavu.objects.create(
                    employee=self.employee, rok=rok, typ=self.typ,
                    narok_hodin=narok_default,
                )

        self.stav = self.Stav.SCHVALENO
        self.schvaleno_kym = schvalovatele
        self.schvaleno_kdy = timezone.now()
        if samoschvaleno:
            self.samoschvaleno = True
            self.poznamka_schvalovatele = duvod
        self.save()

        if zustatek:
            zustatek.cerpano_hodin += self.pocet_hodin
            zustatek.save()

    def zamitni(self, schvalovatele, poznamka=""):
        """Zamítne žádost."""
        self.stav = self.Stav.ZAMITNUTO
        self.schvaleno_kym = schvalovatele
        self.schvaleno_kdy = timezone.now()
        self.poznamka_schvalovatele = poznamka
        self.save()

    def save(self, *args, **kwargs):
        je_novy = self.pk is None
        puvodni_stav = None
        if not je_novy:
            puvodni_stav = (
                ZadostOStav.objects.filter(pk=self.pk).values_list("stav", flat=True).first()
            )

        # Přepočítat hodiny před uložením pokud je potřeba
        if not self.pocet_hodin and self.datum_od and self.datum_do:
            self.vypocitej_hodiny()

        if je_novy and self.typ_id and not self.typ.vyzaduje_schvaleni:
            # Samo-záznam (nemoc, OČR, služební volno, home office): platí
            # okamžitě, bez schvalovatele a bez e-mailové notifikace.
            self.stav = self.Stav.SCHVALENO
            self.schvaleno_kdy = timezone.now()
        elif not self.schvalovatele_id and self.employee_id:
            # Žádost vyžadující schválení — přiřadit schvalovatele, pokud není.
            self.schvalovatele = self.employee.get_schvalovatel()

        # Signálu se hodí vědět, jestli šlo o skutečný přechod stavu (aby
        # neposílal "schváleno/zamítnuto" znovu při každém dalším uložení
        # už vyřízené žádosti, např. při editaci poznámky v adminu). Nastavuje se
        # PŘED uložením — signál běží uvnitř save() a u znovu použité instance by
        # jinak viděl hodnotu z předchozího uložení.
        self._stav_se_zmenil = je_novy or puvodni_stav != self.stav

        super().save(*args, **kwargs)


class ZadostOZruseni(models.Model):
    """
    Žádost zaměstnance o zrušení své už schválené žádosti (#100) u typů se schvalováním
    (dovolená, indispoziční volno). Do schválení platí původní žádost beze změny; po
    schválení se provede `ZadostOStav.zrus()` pro rozsah `datum_od`–`datum_do`.
    """

    class Stav(models.TextChoices):
        CEKA = "ceka", _("Čeká na schválení")
        SCHVALENO = "schvaleno", _("Schváleno")
        ZAMITNUTO = "zamitnuto", _("Zamítnuto")

    zadost = models.ForeignKey(
        ZadostOStav,
        on_delete=models.CASCADE,
        related_name="zadosti_o_zruseni",
        verbose_name=_("zrušovaná žádost"),
    )
    datum_od = models.DateField(_("rušit od"))
    datum_do = models.DateField(_("rušit do"))
    stav = models.CharField(_("stav"), max_length=12, choices=Stav.choices, default=Stav.CEKA)
    schvalovatel = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="zruseni_ke_schvaleni",
        verbose_name=_("schvaluje"),
    )
    schvaleno_kym = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schvalil_zruseni",
        verbose_name=_("vyřídil"),
    )
    schvaleno_kdy = models.DateTimeField(_("vyřízeno kdy"), null=True, blank=True)
    samoschvaleno = models.BooleanField(_("schváleno vlastní osobou"), default=False)
    poznamka_zamestnance = models.TextField(_("poznámka zaměstnance"), blank=True)
    poznamka_schvalovatele = models.TextField(_("poznámka schvalovatele"), blank=True)
    vytvoreno = models.DateTimeField(_("vytvořeno"), auto_now_add=True)

    class Meta:
        verbose_name = _("žádost o zrušení")
        verbose_name_plural = _("žádosti o zrušení")
        ordering = ["-vytvoreno"]

    def __str__(self):
        return f"Zrušení: {self.zadost} | {self.get_stav_display()}"

    @property
    def employee(self):
        return self.zadost.employee

    @property
    def je_zpetne(self):
        """Ruší dny, které už začaly (#103) — počítá se při zobrazení, ne při podání:
        schvalovatel rozhoduje o dnech, jak vypadají teď."""
        return self.datum_od < timezone.localdate()

    def popis_rozsahu(self):
        def den(d):
            return f"{d.day}. {d.month}. {d.year}"

        if self.datum_od == self.datum_do:
            return den(self.datum_od)
        return f"{den(self.datum_od)} – {den(self.datum_do)}"

    def muze_schvalit_sam(self, employee):
        """Smí `employee` schválit zrušení vlastní žádosti sám (stejná pravidla jako #90)?"""
        return bool(
            employee
            and self.zadost.employee_id == employee.pk
            and self.stav == self.Stav.CEKA
            and employee.schvaluje_zadosti
        )

    def schval(self, schvalovatel, samoschvaleno=False, duvod=""):
        """Schválí zrušení a provede ho na původní žádosti."""
        if self.stav != self.Stav.CEKA:
            raise ValidationError(_("Žádost o zrušení už byla vyřízena."))
        with transaction.atomic():
            self.zadost.zrus(self.datum_od, self.datum_do)
            self.stav = self.Stav.SCHVALENO
            self.schvaleno_kym = schvalovatel
            self.schvaleno_kdy = timezone.now()
            if samoschvaleno:
                self.samoschvaleno = True
                self.poznamka_schvalovatele = duvod
            self.save()

    def zamitni(self, schvalovatel, poznamka=""):
        """Zamítne zrušení — původní žádost zůstane schválená beze změny."""
        if self.stav != self.Stav.CEKA:
            raise ValidationError(_("Žádost o zrušení už byla vyřízena."))
        self.stav = self.Stav.ZAMITNUTO
        self.schvaleno_kym = schvalovatel
        self.schvaleno_kdy = timezone.now()
        self.poznamka_schvalovatele = poznamka
        self.save()

    def save(self, *args, **kwargs):
        je_nova = self.pk is None
        puvodni_stav = None
        if not je_nova:
            puvodni_stav = (
                ZadostOZruseni.objects.filter(pk=self.pk).values_list("stav", flat=True).first()
            )
        if je_nova and not self.schvalovatel_id:
            # Stejný řetězec jako u původní žádosti, ale určený až teď — nadřízený se
            # mohl od schválení změnit nebo být nepřítomen (zástupce).
            self.schvalovatel = self.zadost.employee.get_schvalovatel()
        self._stav_se_zmenil = je_nova or puvodni_stav != self.stav
        super().save(*args, **kwargs)
