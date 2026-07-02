from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Rozšířený uživatel."""
    email = models.EmailField(_("e-mail"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "first_name", "last_name"]

    class Meta:
        verbose_name = _("uživatel")
        verbose_name_plural = _("uživatelé")

    def __str__(self):
        return self.get_full_name() or self.email


# ---------------------------------------------------------------------------
# Organizační struktura
# ---------------------------------------------------------------------------

class Sekce(models.Model):
    """Nejvyšší úroveň organizační hierarchie."""
    nazev = models.CharField(_("název"), max_length=200)
    kod = models.CharField(_("kód"), max_length=20, unique=True)
    vedouci = models.ForeignKey(
        "Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vedouci_sekce",
        verbose_name=_("vedoucí"),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("sekce")
        verbose_name_plural = _("sekce")
        ordering = ["nazev"]

    def __str__(self):
        return f"{self.kod} – {self.nazev}"


class Odbor(models.Model):
    """Druhá úroveň — patří pod sekci."""
    sekce = models.ForeignKey(
        Sekce,
        on_delete=models.PROTECT,
        related_name="odbory",
        verbose_name=_("sekce"),
    )
    nazev = models.CharField(_("název"), max_length=200)
    kod = models.CharField(_("kód"), max_length=20, unique=True)
    vedouci = models.ForeignKey(
        "Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vedouci_odboru",
        verbose_name=_("vedoucí"),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("odbor")
        verbose_name_plural = _("odbory")
        ordering = ["sekce", "nazev"]

    def __str__(self):
        return f"{self.kod} – {self.nazev}"


class Oddeleni(models.Model):
    """Třetí úroveň — patří pod odbor."""
    odbor = models.ForeignKey(
        Odbor,
        on_delete=models.PROTECT,
        related_name="oddeleni",
        verbose_name=_("odbor"),
    )
    nazev = models.CharField(_("název"), max_length=200)
    kod = models.CharField(_("kód"), max_length=20, unique=True)
    vedouci = models.ForeignKey(
        "Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vedouci_oddeleni",
        verbose_name=_("vedoucí"),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("oddělení")
        verbose_name_plural = _("oddělení")
        ordering = ["odbor", "nazev"]

    def __str__(self):
        return f"{self.kod} – {self.nazev}"


# ---------------------------------------------------------------------------
# Typ úvazku
# ---------------------------------------------------------------------------

class TypUvazku(models.Model):
    """Číselník typů pracovních úvazků."""
    nazev = models.CharField(_("název"), max_length=100)  # např. "Plný úvazek"
    hodiny_denne = models.DecimalField(
        _("hodin denně"), max_digits=4, decimal_places=2
    )  # např. 8.00
    hodiny_tyydne = models.DecimalField(
        _("hodin týdně"), max_digits=5, decimal_places=2
    )  # např. 40.00
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ úvazku")
        verbose_name_plural = _("typy úvazků")
        ordering = ["-hodiny_denne"]

    def __str__(self):
        return f"{self.nazev} ({self.hodiny_denne}h/den)"


# ---------------------------------------------------------------------------
# Zaměstnanec
# ---------------------------------------------------------------------------

class Employee(models.Model):
    """Profil zaměstnance navázaný na User účet."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee",
        verbose_name=_("uživatel"),
    )
    osobni_cislo = models.CharField(_("osobní číslo"), max_length=20, unique=True)
    oddeleni = models.ForeignKey(
        Oddeleni,
        on_delete=models.PROTECT,
        related_name="zamestnanci",
        verbose_name=_("oddělení"),
    )
    typ_uvazku = models.ForeignKey(
        TypUvazku,
        on_delete=models.PROTECT,
        related_name="zamestnanci",
        verbose_name=_("typ úvazku"),
    )
    datum_nastupu = models.DateField(_("datum nástupu"))
    datum_ukonceni = models.DateField(_("datum ukončení"), null=True, blank=True)
    telefon = models.CharField(_("telefon"), max_length=20, blank=True)
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("zaměstnanec")
        verbose_name_plural = _("zaměstnanci")
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.osobni_cislo})"

    @property
    def jmeno(self):
        return self.user.get_full_name()

    @property
    def email(self):
        return self.user.email

    def get_schvalovatel(self):
        """
        Vrátí přímého nadřízeného dle hierarchie:
        - Zaměstnanec → vedoucí oddělení
        - Vedoucí oddělení → vedoucí odboru
        - Vedoucí odboru → vedoucí sekce
        - Vedoucí sekce → None (schvaluje admin)
        """
        oddeleni = self.oddeleni
        if oddeleni.vedouci and oddeleni.vedouci != self:
            return oddeleni.vedouci

        odbor = oddeleni.odbor
        if odbor.vedouci and odbor.vedouci != self:
            return odbor.vedouci

        sekce = odbor.sekce
        if sekce.vedouci and sekce.vedouci != self:
            return sekce.vedouci

        return None  # admin musí schválit ručně


# ---------------------------------------------------------------------------
# Historie přesunů zaměstnance
# ---------------------------------------------------------------------------

class HistoriePrislusenosti(models.Model):
    """Záznamy přesunů zaměstnance mezi odděleními."""
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="historie",
        verbose_name=_("zaměstnanec"),
    )
    oddeleni = models.ForeignKey(
        Oddeleni,
        on_delete=models.PROTECT,
        verbose_name=_("oddělení"),
    )
    datum_od = models.DateField(_("datum od"))
    datum_do = models.DateField(_("datum do"), null=True, blank=True)
    poznamka = models.TextField(_("poznámka"), blank=True)
    zmenil = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("změnil"),
    )

    class Meta:
        verbose_name = _("historie příslušnosti")
        verbose_name_plural = _("historie příslušnosti")
        ordering = ["-datum_od"]

    def __str__(self):
        return f"{self.employee} → {self.oddeleni} od {self.datum_od}"
