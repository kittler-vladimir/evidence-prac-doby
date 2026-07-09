from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
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
    zamestnanci_vidi_cely_odbor = models.BooleanField(
        _("zaměstnanci vidí celý odbor"),
        default=True,
        help_text=_(
            "Zapnuto (výchozí): řadoví zaměstnanci bez funkce vidí v přehledech "
            "přítomnosti/týmu všechny zaměstnance odboru napříč odděleními. "
            "Vypnuto: vidí jen zaměstnance vlastního oddělení."
        ),
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

    class DruhPracovniDoby(models.TextChoices):
        PRUZNA = "PRUZNA", _("Pružná")
        PEVNA = "PEVNA", _("Pevná")

    nazev = models.CharField(_("název"), max_length=100)  # např. "Plný úvazek"
    hodiny_denne = models.DecimalField(
        _("hodin denně"), max_digits=4, decimal_places=2
    )  # např. 8.00
    hodiny_tyydne = models.DecimalField(
        _("hodin týdně"), max_digits=5, decimal_places=2
    )  # např. 40.00
    druh_pracovni_doby = models.CharField(
        _("druh pracovní doby"),
        max_length=10,
        choices=DruhPracovniDoby.choices,
        default=DruhPracovniDoby.PRUZNA,
        help_text=_(
            "Pružná: jeden časový blok (jádrová doba). Pevná: jeden nebo "
            "více závazných časových bloků. Zatím jen evidence — bloky "
            "se nikde nevynucují, slouží jako podklad pro budoucí validaci."
        ),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ úvazku")
        verbose_name_plural = _("typy úvazků")
        ordering = ["-hodiny_denne"]

    def __str__(self):
        return f"{self.nazev} ({self.hodiny_denne}h/den)"


class CasovyBlokUvazku(models.Model):
    """
    Časový blok pracovní doby patřící k typu úvazku — jádrová doba u
    pružné pracovní doby (právě jeden blok), nebo jeden z více závazných
    bloků u pevné pracovní doby. Počet bloků vůči druhu typu úvazku
    validuje admin (TypUvazkuAdmin), ne tento model.
    """

    typ_uvazku = models.ForeignKey(
        TypUvazku,
        on_delete=models.CASCADE,
        related_name="casove_bloky",
        verbose_name=_("typ úvazku"),
    )
    blok_od = models.TimeField(_("od"))
    blok_do = models.TimeField(_("do"))

    class Meta:
        verbose_name = _("časový blok pracovní doby")
        verbose_name_plural = _("časové bloky pracovní doby")
        ordering = ["blok_od"]

    def __str__(self):
        return f"{self.blok_od:%H:%M}–{self.blok_do:%H:%M}"

    def clean(self):
        if self.blok_od and self.blok_do and self.blok_do <= self.blok_od:
            raise ValidationError(_("Konec bloku musí být po jeho začátku."))


# ---------------------------------------------------------------------------
# Zaměstnanec
# ---------------------------------------------------------------------------

class Employee(models.Model):
    """Profil zaměstnance navázaný na User účet."""

    class FunkceChoices(models.TextChoices):
        REDITEL_SEKCE = "REDITEL_SEKCE", _("Ředitel sekce")
        REDITEL_ODBORU = "REDITEL_ODBORU", _("Ředitel odboru")
        VEDOUCI_ODDELENI = "VEDOUCI_ODDELENI", _("Vedoucí oddělení")
        SEKRETARIAT_ODBORU = "SEKRETARIAT_ODBORU", _("Sekretariát odboru")

    # Funkce, pro které lze zvolit zástupce (má smysl jen tam, kde funkce
    # nese CRUD práva na zaměstnance — REDITEL_SEKCE je jen read-only přehled).
    FUNKCE_SE_ZASTUPCEM = (
        FunkceChoices.VEDOUCI_ODDELENI,
        FunkceChoices.REDITEL_ODBORU,
        FunkceChoices.SEKRETARIAT_ODBORU,
    )
    # Funkce, které smí přesouvat zaměstnance mezi odděleními a měnit funkci ostatním.
    FUNKCE_S_PRAVEM_PRESUN_A_ZMENA = (
        FunkceChoices.REDITEL_ODBORU,
        FunkceChoices.SEKRETARIAT_ODBORU,
    )

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
    funkce = models.CharField(
        _("funkce"),
        max_length=20,
        choices=FunkceChoices.choices,
        blank=True,
        help_text=_(
            "Řídící funkce v organizační hierarchii. Přiřazení automaticky "
            "nastaví odpovídající pole 'vedoucí' na sekci/odboru/oddělení a "
            "uvolní funkci předchozímu držiteli téže jednotky."
        ),
    )
    zastupce = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="zastupovani_za",
        verbose_name=_("zástupce"),
        help_text=_(
            "Zástupce má trvale stejná práva na správu zaměstnanců jako "
            "tento zaměstnanec a přebírá schvalování žádostí, pokud je "
            "tento zaměstnanec označen jako nepřítomný. Musí být ze "
            "stejné organizační jednotky, na kterou je vázaná funkce."
        ),
    )
    rucne_nepritomen = models.BooleanField(
        _("ručně označen jako nepřítomný"),
        default=False,
        help_text=_(
            "Dočasné přepnutí mimo evidenci dovolené/nemoci (např. "
            "služební cesta) — pokud je zapnuto, schvalování žádostí "
            "podřízených přebírá nastavený zástupce."
        ),
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

    def _zastupuje_nekoho_s_funkci(self, funkce_set):
        """Zastupuje trvale (Employee.zastupce) někoho, kdo drží některou z uvedených funkcí?"""
        return Employee.objects.filter(zastupce=self, funkce__in=funkce_set).exists()

    @property
    def muze_spravovat_zamestnance(self):
        """Smí zakládat/upravovat/přesouvat zaměstnance ve svém rozsahu (vlastní funkce, nebo trvalé zastupování za ni)."""
        if self.funkce in self.FUNKCE_SE_ZASTUPCEM:
            return True
        return self._zastupuje_nekoho_s_funkci(self.FUNKCE_SE_ZASTUPCEM)

    @property
    def muze_presouvat_zamestnance(self):
        """Smí přesouvat zaměstnance mezi odděleními (musí spravovat víc než jedno — vlastní funkce, nebo zastupování)."""
        if self.funkce in self.FUNKCE_S_PRAVEM_PRESUN_A_ZMENA:
            return True
        return self._zastupuje_nekoho_s_funkci(self.FUNKCE_S_PRAVEM_PRESUN_A_ZMENA)

    @property
    def muze_menit_funkci(self):
        """Smí přiřazovat/měnit funkci jiným zaměstnancům (ne vedoucí oddělení — vlastní funkce, nebo zastupování)."""
        if self.funkce in self.FUNKCE_S_PRAVEM_PRESUN_A_ZMENA:
            return True
        return self._zastupuje_nekoho_s_funkci(self.FUNKCE_S_PRAVEM_PRESUN_A_ZMENA)

    @property
    def muze_mit_zastupce(self):
        """Má funkci, pro kterou lze zvolit zástupce (nikoliv REDITEL_SEKCE nebo bez funkce)."""
        return self.funkce in self.FUNKCE_SE_ZASTUPCEM

    @property
    def je_reditel_sekce(self):
        return self.funkce == self.FunkceChoices.REDITEL_SEKCE

    def moznosti_zastupce(self):
        """Queryset kolegů ze stejné organizační jednotky, které lze zvolit jako zástupce."""
        if self.funkce not in self.FUNKCE_SE_ZASTUPCEM:
            return Employee.objects.none()
        if self.funkce == self.FunkceChoices.VEDOUCI_ODDELENI:
            qs = Employee.objects.filter(oddeleni=self.oddeleni)
        else:  # REDITEL_ODBORU, SEKRETARIAT_ODBORU
            qs = Employee.objects.filter(oddeleni__odbor=self.oddeleni.odbor)
        return qs.filter(aktivni=True).exclude(pk=self.pk)

    def _vlastni_spravovana_oddeleni(self):
        """Oddělení spravovaná na základě vlastní funkce (bez zastupování)."""
        if self.funkce == self.FunkceChoices.VEDOUCI_ODDELENI:
            return Oddeleni.objects.filter(pk=self.oddeleni_id)
        if self.funkce in (self.FunkceChoices.REDITEL_ODBORU, self.FunkceChoices.SEKRETARIAT_ODBORU):
            return Oddeleni.objects.filter(odbor=self.oddeleni.odbor)
        return Oddeleni.objects.none()

    def spravovana_oddeleni(self):
        """Queryset Oddeleni, mezi kterými smí zaměstnanec zakládat/přesouvat zaměstnance (vlastní funkce i trvalé zastupování)."""
        ids = set(self._vlastni_spravovana_oddeleni().values_list("pk", flat=True))
        for zastupovany in Employee.objects.filter(zastupce=self):
            ids |= set(zastupovany._vlastni_spravovana_oddeleni().values_list("pk", flat=True))
        return Oddeleni.objects.filter(pk__in=ids)

    def spravovani_zamestnanci(self):
        """Queryset zaměstnanců, které smí tento zaměstnanec spravovat (přidávat/upravovat/přesouvat)."""
        return Employee.objects.filter(oddeleni__in=self.spravovana_oddeleni())

    def _jednotka_pro_funkci(self, funkce, oddeleni):
        """Organizační jednotka (Oddeleni/Odbor/Sekce), na kterou se váže daná funkce."""
        if funkce == self.FunkceChoices.VEDOUCI_ODDELENI:
            return oddeleni
        if funkce == self.FunkceChoices.REDITEL_ODBORU:
            return oddeleni.odbor
        if funkce == self.FunkceChoices.REDITEL_SEKCE:
            return oddeleni.odbor.sekce
        return None  # SEKRETARIAT_ODBORU nemá pole vedoucí k synchronizaci

    def _drzitele_stejne_funkce(self, funkce, oddeleni):
        """Ostatní zaměstnanci, kteří mohou držet stejnou funkci na stejné jednotce."""
        if funkce == self.FunkceChoices.VEDOUCI_ODDELENI:
            return Employee.objects.filter(funkce=funkce, oddeleni=oddeleni)
        if funkce in (self.FunkceChoices.REDITEL_ODBORU, self.FunkceChoices.SEKRETARIAT_ODBORU):
            return Employee.objects.filter(funkce=funkce, oddeleni__odbor=oddeleni.odbor)
        if funkce == self.FunkceChoices.REDITEL_SEKCE:
            return Employee.objects.filter(funkce=funkce, oddeleni__odbor__sekce=oddeleni.odbor.sekce)
        return Employee.objects.none()

    def clean(self):
        super().clean()
        if self.zastupce_id:
            if self.zastupce_id == self.pk:
                raise ValidationError({"zastupce": _("Nelze zvolit sám sebe jako zástupce.")})
            if self.funkce not in self.FUNKCE_SE_ZASTUPCEM:
                raise ValidationError({
                    "zastupce": _("Zástupce lze nastavit jen pro funkci s právy na správu zaměstnanců.")
                })
            if not self.moznosti_zastupce().filter(pk=self.zastupce_id).exists():
                raise ValidationError({
                    "zastupce": _("Zástupce musí být ze stejné organizační jednotky jako tato funkce.")
                })

    def je_nepritomen(self, datum=None):
        """Je zaměstnanec k danému datu (výchozí dnes) nepřítomen pro účely předání schvalování zástupci?"""
        if self.rucne_nepritomen:
            return True
        from leaves.models import ZadostOStav  # lokální import kvůli cyklické závislosti modelů

        datum = datum or timezone.localdate()
        return ZadostOStav.objects.filter(
            employee=self,
            stav=ZadostOStav.Stav.SCHVALENO,
            typ__je_pritomnost=False,
            datum_od__lte=datum,
            datum_do__gte=datum,
        ).exists()

    def save(self, *args, **kwargs):
        stary = None if self.pk is None else Employee.objects.filter(pk=self.pk).first()
        zmenilo_se_oddeleni = stary is not None and stary.oddeleni_id != self.oddeleni_id

        # Přesun do jiného oddělení ukončuje funkci vázanou na předchozí
        # jednotku — nedává smysl zůstat "vedoucím oddělení", ze kterého
        # zaměstnanec odešel. Pokud volající v témže save() zároveň
        # explicitně nastavil jinou funkci, respektujeme ji místo mazání.
        if zmenilo_se_oddeleni and stary.funkce and self.funkce == stary.funkce:
            self.funkce = ""
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"funkce"}

        # Zástupce je vázán na funkci a jednotku, na které byl zvolen —
        # přesun do jiného oddělení nebo změna/zrušení funkce ho stejně
        # jako funkci samotnou zneplatní.
        if stary is not None and self.zastupce_id and (zmenilo_se_oddeleni or stary.funkce != self.funkce):
            self.zastupce = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"zastupce"}

        with transaction.atomic():
            super().save(*args, **kwargs)

            zmenila_se_funkce = stary is None or stary.funkce != self.funkce

            if self.funkce and zmenila_se_funkce:
                self._drzitele_stejne_funkce(self.funkce, self.oddeleni).exclude(pk=self.pk).update(funkce="")
                jednotka = self._jednotka_pro_funkci(self.funkce, self.oddeleni)
                if jednotka is not None:
                    type(jednotka).objects.filter(pk=jednotka.pk).update(vedouci=self)

            if stary is not None and stary.funkce and stary.funkce != self.funkce:
                stara_jednotka = self._jednotka_pro_funkci(stary.funkce, stary.oddeleni)
                if stara_jednotka is not None:
                    type(stara_jednotka).objects.filter(pk=stara_jednotka.pk, vedouci_id=self.pk).update(vedouci=None)

    def _schvalovatel_nebo_zastupce(self, kandidat):
        """Pokud je kandidát nepřítomen a má zástupce, schvaluje místo něj zástupce."""
        if kandidat.zastupce_id and kandidat.zastupce_id != self.pk and kandidat.je_nepritomen():
            return kandidat.zastupce
        return kandidat

    def get_schvalovatel(self):
        """
        Vrátí přímého nadřízeného dle hierarchie (nebo jeho zástupce,
        je-li nadřízený aktuálně nepřítomen a zástupce má nastaveného):
        - Zaměstnanec → vedoucí oddělení
        - Vedoucí oddělení → vedoucí odboru
        - Vedoucí odboru → vedoucí sekce
        - Vedoucí sekce → None (schvaluje admin)
        """
        oddeleni = self.oddeleni
        if oddeleni.vedouci and oddeleni.vedouci != self:
            return self._schvalovatel_nebo_zastupce(oddeleni.vedouci)

        odbor = oddeleni.odbor
        if odbor.vedouci and odbor.vedouci != self:
            return self._schvalovatel_nebo_zastupce(odbor.vedouci)

        sekce = odbor.sekce
        if sekce.vedouci and sekce.vedouci != self:
            return self._schvalovatel_nebo_zastupce(sekce.vedouci)

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


# ---------------------------------------------------------------------------
# Viditelnost zaměstnanců v přehledech (reports, seznam zaměstnanců)
# ---------------------------------------------------------------------------

def viditelni_zamestnanci(user):
    """
    Queryset aktivních zaměstnanců viditelných danému uživateli v
    (read-only) přehledech — sdíleno mezi accounts a reports, aby se
    pravidla viditelnosti v aplikaci časem nerozešla.

    - admin (is_staff): vidí vše
    - Vedoucí oddělení: vlastní oddělení
    - Ředitel odboru / Sekretariát odboru: celý vlastní odbor
    - Ředitel sekce: nemá přístup k seznamu jednotlivců (má vlastní
      read-only přehled sekce, viz accounts:prehled_sekce)
    - bez funkce: celý odbor, nebo jen vlastní oddělení dle
      Odbor.zamestnanci_vidi_cely_odbor
    """
    if user.is_staff:
        return Employee.objects.filter(aktivni=True)

    if not hasattr(user, "employee"):
        return Employee.objects.none()

    employee = user.employee
    if employee.muze_spravovat_zamestnance:
        return employee.spravovani_zamestnanci().filter(aktivni=True)
    if employee.funkce == Employee.FunkceChoices.REDITEL_SEKCE:
        return Employee.objects.none()

    if employee.oddeleni.odbor.zamestnanci_vidi_cely_odbor:
        return Employee.objects.filter(oddeleni__odbor=employee.oddeleni.odbor, aktivni=True)
    return Employee.objects.filter(oddeleni=employee.oddeleni, aktivni=True)
