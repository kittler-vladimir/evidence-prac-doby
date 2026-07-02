from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone


class TypDovolene(models.Model):
    """Číselník typů absence (dovolená, nemoc, sick day, OČR...)."""
    nazev = models.CharField(_("název"), max_length=100)
    zkratka = models.CharField(_("zkratka"), max_length=10)
    odecita_ze_zustatku = models.BooleanField(
        _("odečítá ze zůstatku dovolené"),
        default=True,
        help_text=_("Např. nemoc se neodečítá z dovolené."),
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


class ZustatekDovolene(models.Model):
    """Nárok a čerpání dovolené v hodinách pro daného zaměstnance a rok."""

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="zustatky_dovolene",
        verbose_name=_("zaměstnanec"),
    )
    rok = models.PositiveSmallIntegerField(_("rok"))
    narok_hodin = models.DecimalField(
        _("nárok (hod)"), max_digits=6, decimal_places=2, default=0
    )
    cerpano_hodin = models.DecimalField(
        _("čerpáno (hod)"), max_digits=6, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = _("zůstatek dovolené")
        verbose_name_plural = _("zůstatky dovolené")
        unique_together = [("employee", "rok")]
        ordering = ["-rok"]

    def __str__(self):
        return (
            f"{self.employee} | {self.rok} | "
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
        self.stav = self.Stav.SCHVALENO
        self.schvaleno_kym = schvalovatele
        self.schvaleno_kdy = timezone.now()
        self.save()

        if self.typ.odecita_ze_zustatku:
            rok = self.datum_od.year
            zustatek, _ = ZustatekDovolene.objects.get_or_create(
                employee=self.employee,
                rok=rok,
                defaults={"narok_hodin": 0},
            )
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
