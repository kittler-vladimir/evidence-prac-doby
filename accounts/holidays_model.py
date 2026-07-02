from django.db import models
from django.utils.translation import gettext_lazy as _
import holidays as holidays_lib


class Zeme(models.Model):
    """Stát pro číselník státních svátků."""
    nazev = models.CharField(_("název"), max_length=100)
    kod = models.CharField(_("kód ISO 3166-1"), max_length=2, unique=True)  # CZ, SK...

    class Meta:
        verbose_name = _("země")
        verbose_name_plural = _("země")
        ordering = ["nazev"]

    def __str__(self):
        return f"{self.nazev} ({self.kod})"


class StatniSvatek(models.Model):
    """
    Státní svátek nebo firemní volno.
    Adminem upravitelný seznam — každý rok se může dogenerovat
    přes management command a pak ručně upravit.
    """
    zeme = models.ForeignKey(
        Zeme,
        on_delete=models.CASCADE,
        related_name="svatky",
        verbose_name=_("země"),
    )
    datum = models.DateField(_("datum"))
    nazev = models.CharField(_("název"), max_length=200)
    firemni = models.BooleanField(
        _("firemní volno"),
        default=False,
        help_text=_("Volno stanovené firmou, ne státem."),
    )

    class Meta:
        verbose_name = _("státní svátek")
        verbose_name_plural = _("státní svátky")
        ordering = ["datum"]
        unique_together = [("zeme", "datum")]

    def __str__(self):
        return f"{self.datum} – {self.nazev} ({self.zeme.kod})"


def generuj_svatky_cr(rok: int) -> list[dict]:
    """
    Vygeneruje seznam státních svátků ČR pro daný rok pomocí knihovny holidays.
    Vrací list slovníků připravených pro hromadné vytvoření objektů StatniSvatek.
    """
    cr_holidays = holidays_lib.CZ(years=rok)
    return [
        {"datum": datum, "nazev": nazev}
        for datum, nazev in sorted(cr_holidays.items())
    ]
