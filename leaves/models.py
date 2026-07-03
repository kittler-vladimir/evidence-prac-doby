from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone


class TypDovolene(models.Model):
    """Číselník typů absence (dovolená, nemoc, sick day, OČR...)."""

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
        _("odečítá ze zůstatku dovolené"),
        default=True,
        help_text=_("Např. nemoc se neodečítá z dovolené."),
    )
    je_indispozicni_volno = models.BooleanField(
        _("je indispoziční volno"),
        default=False,
        help_text=_(
            "Nárok se pro tento typ automaticky dosazuje z globálního "
            "nastavení (NarokIndispozicnihoVolna), ne ručně na zaměstnance."
        ),
    )
    kategorie_pro_prehled = models.CharField(
        _("kategorie pro přehled přítomnosti"),
        max_length=20,
        choices=KategoriePrehled.choices,
        default=KategoriePrehled.JINA,
        help_text=_(
            "Určuje, pod jakou kategorií se schválené žádosti tohoto typu "
            "zobrazí v denním přehledu přítomnosti a vyhledání zaměstnance."
        ),
    )
    barva = models.CharField(
        _("barva (hex)"), max_length=7, default="#4A90E2",
        help_text=_("Barva pro zobrazení v kalendáři."),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ dovolené")
        verbose_name_plural = _("typy dovolené")

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

    def vychozi_narok(self, datum):
        """
        Výchozí nárok pro nově zakládaný zůstatek tohoto typu k danému datu.
        U indispozičního volna se dosazuje z globálního nastavení; u ostatních
        typů zůstává 0 (admin zůstatek pro daný rok zakládá ručně).
        """
        if self.je_indispozicni_volno:
            return NarokIndispozicnihoVolna.aktivni_hodnota(datum)
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


class ZustatekDovolene(models.Model):
    """Nárok a čerpání absence v hodinách pro daného zaměstnance, rok a typ."""

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="zustatky_dovolene",
        verbose_name=_("zaměstnanec"),
    )
    rok = models.PositiveSmallIntegerField(_("rok"))
    typ = models.ForeignKey(
        TypDovolene,
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
        verbose_name = _("zůstatek dovolené")
        verbose_name_plural = _("zůstatky dovolené")
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


class ZadostODovolenou(models.Model):
    """Žádost zaměstnance o dovolenou / absenci."""

    class Stav(models.TextChoices):
        CEKA = "ceka", _("Čeká na schválení")
        SCHVALENO = "schvaleno", _("Schváleno")
        ZAMITNUTO = "zamitnuto", _("Zamítnuto")
        STORNOVÁNO = "stornovano", _("Stornováno")

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="zadosti_o_dovolenou",
        verbose_name=_("zaměstnanec"),
    )
    typ = models.ForeignKey(
        TypDovolene,
        on_delete=models.PROTECT,
        verbose_name=_("typ"),
    )
    datum_od = models.DateField(_("datum od"))
    datum_do = models.DateField(_("datum do"))

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
    poznamka_zamestnance = models.TextField(_("poznámka zaměstnance"), blank=True)
    poznamka_schvalovatele = models.TextField(_("poznámka schvalovatele"), blank=True)
    vytvoreno = models.DateTimeField(_("vytvořeno"), auto_now_add=True)
    upraveno = models.DateTimeField(_("upraveno"), auto_now=True)

    class Meta:
        verbose_name = _("žádost o dovolenou")
        verbose_name_plural = _("žádosti o dovolenou")
        ordering = ["-vytvoreno"]

    def __str__(self):
        return (
            f"{self.employee} | {self.typ.zkratka} | "
            f"{self.datum_od} – {self.datum_do} | {self.get_stav_display()}"
        )

    def clean(self):
        if self.datum_od and self.datum_do and self.datum_do < self.datum_od:
            raise ValidationError(_("Datum do musí být po datu od."))

    def vypocitej_hodiny(self):
        """
        Spočítá počet hodin dovolené:
        pracovní dny v rozsahu (bez víkendů a státních svátků) × hod/den dle úvazku.
        """
        from accounts.holidays_model import StatniSvatek
        from datetime import timedelta

        if not (self.datum_od and self.datum_do and self.employee_id):
            return

        svatky = set(
            StatniSvatek.objects.filter(
                datum__gte=self.datum_od,
                datum__lte=self.datum_do,
            ).values_list("datum", flat=True)
        )

        hodiny_denne = self.employee.typ_uvazku.hodiny_denne
        celkem = 0
        current = self.datum_od
        while current <= self.datum_do:
            if current.weekday() < 5 and current not in svatky:
                celkem += hodiny_denne
            current += timedelta(days=1)

        self.pocet_hodin = celkem

    def schval(self, schvalovatele):
        """Schválí žádost a aktualizuje zůstatek dovolené."""
        zustatek = None
        if self.typ.odecita_ze_zustatku:
            rok = self.datum_od.year
            zustatek = ZustatekDovolene.objects.filter(
                employee=self.employee, rok=rok, typ=self.typ
            ).first()
            if not zustatek:
                narok_default = self.typ.vychozi_narok(self.datum_od)
                if self.typ.je_indispozicni_volno and narok_default <= 0:
                    raise ValidationError(
                        _("Pro indispoziční volno není nastaven žádný aktivní nárok.")
                    )
                zustatek = ZustatekDovolene.objects.create(
                    employee=self.employee, rok=rok, typ=self.typ,
                    narok_hodin=narok_default,
                )

        self.stav = self.Stav.SCHVALENO
        self.schvaleno_kym = schvalovatele
        self.schvaleno_kdy = timezone.now()
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
        # Přepočítat hodiny před uložením pokud je potřeba
        if not self.pocet_hodin and self.datum_od and self.datum_do:
            self.vypocitej_hodiny()
        # Nastavit schvalovatele pokud není
        if not self.schvalovatele_id and self.employee_id:
            self.schvalovatele = self.employee.get_schvalovatel()
        super().save(*args, **kwargs)
