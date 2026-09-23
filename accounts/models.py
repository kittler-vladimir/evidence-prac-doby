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
            "více závazných časových bloků, každý se zaškrtnutými dny v "
            "týdnu, kdy platí. Jádrová doba pružného úvazku se využívá při "
            "výpočtu odpracované doby u pohybů s příznakem „započítává se "
            "u pružné pracovní doby“. U pevné pracovní doby se odpracovaná "
            "doba ořízne na bloky platné pro daný den — den bez "
            "zaškrtnutého bloku dá 0 odpracovaných minut. Příchody a "
            "odchody se vůči blokům nekontrolují, jen se podle nich počítá "
            "odpracovaná doba."
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

    # Dny v týdnu, kdy blok platí — jen u pevné pracovní doby (viz
    # WorkdaySummary.prepocitej()): odpracovaná doba se ten den ořízne na
    # průnik se všemi bloky zaškrtnutými pro daný den; den bez zaškrtnutého
    # bloku znamená 0 odpracovaných minut. U pružné pracovní doby (jádro) se
    # tyto příznaky nevyužívají — jádro platí bez ohledu na den v týdnu.
    pondeli = models.BooleanField(_("pondělí"), default=False)
    utery = models.BooleanField(_("úterý"), default=False)
    streda = models.BooleanField(_("středa"), default=False)
    ctvrtek = models.BooleanField(_("čtvrtek"), default=False)
    patek = models.BooleanField(_("pátek"), default=False)
    sobota = models.BooleanField(_("sobota"), default=False)
    nedele = models.BooleanField(_("neděle"), default=False)

    #: Pořadí odpovídá date.weekday() (0=pondělí…6=neděle) — použito v
    #: WorkdaySummary.prepocitej() k výběru příznaku pro daný den.
    DNY_V_TYDNU = ["pondeli", "utery", "streda", "ctvrtek", "patek", "sobota", "nedele"]

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
# Funkce (role) — číselník nahrazující dřívější hardcoded enum
# ---------------------------------------------------------------------------

class Funkce(models.Model):
    """
    Číselník organizačních rolí. Nahrazuje dřívější `Employee.FunkceChoices`
    (hardcoded Python enum) — nová role s vlastním CRUD rozsahem, vazbou na
    organizační jednotku a právem na zástupce se dá přidat čistě přes admin,
    bez zásahu do kódu.

    Kódy pěti výchozích rolí (REDITEL_SEKCE, REDITEL_ODBORU, VEDOUCI_ODDELENI,
    SEKRETARIAT_ODBORU, ZAMESTNANEC — viz konstanty níže) mají v business
    logice zvláštní význam jen skrz `ZAMESTNANEC`, na který se funkce
    zaměstnance vrací při zrušení role (viz `Funkce.vychozi()`); ostatní
    role jsou vůči kódu jinak "hloupé" — chování řídí jen jejich příznaky.
    """

    class UrovenVazby(models.TextChoices):
        ZADNA = "ZADNA", _("Žádná")
        ODDELENI = "ODDELENI", _("Oddělení")
        ODBOR = "ODBOR", _("Odbor")
        SEKCE = "SEKCE", _("Sekce")

    REDITEL_SEKCE = "REDITEL_SEKCE"
    REDITEL_ODBORU = "REDITEL_ODBORU"
    VEDOUCI_ODDELENI = "VEDOUCI_ODDELENI"
    SEKRETARIAT_ODBORU = "SEKRETARIAT_ODBORU"
    ZAMESTNANEC = "ZAMESTNANEC"

    kod = models.SlugField(_("kód"), max_length=30, unique=True)
    nazev = models.CharField(_("název"), max_length=100)
    uroven_vazby = models.CharField(
        _("úroveň vazby"),
        max_length=10,
        choices=UrovenVazby.choices,
        default=UrovenVazby.ZADNA,
        help_text=_(
            "Organizační úroveň, na kterou je funkce vázaná — řídí rozsah "
            "pravidla 'nejvýše jeden držitel funkce na jednotku' a rozsah "
            "výběru zástupce/spravovaných oddělení. 'Žádná' = bez vazby "
            "(např. Zaměstnanec)."
        ),
    )
    synchronizuje_vedouciho = models.BooleanField(
        _("synchronizuje pole vedoucí"),
        default=False,
        help_text=_(
            "Zapnuto: přiřazení funkce automaticky nastaví pole 'vedoucí' "
            "na organizační jednotce dané úrovní vazby (a při zrušení funkce "
            "ho zase uvolní). Vypnuto: funkce nese CRUD práva na dané "
            "úrovni, ale nereprezentuje jednotku navenek jako její vedoucí "
            "(např. Sekretariát odboru)."
        ),
    )
    muze_spravovat_zamestnance = models.BooleanField(
        _("smí spravovat zaměstnance"), default=False,
        help_text=_("Smí zakládat/upravovat/přesouvat zaměstnance v rozsahu dle úrovně vazby."),
    )
    muze_presouvat_zamestnance = models.BooleanField(
        _("smí přesouvat zaměstnance"), default=False,
        help_text=_("Smí přesouvat zaměstnance mezi odděleními v rámci svého rozsahu."),
    )
    muze_menit_funkci = models.BooleanField(
        _("smí měnit funkci"), default=False,
        help_text=_("Smí přiřazovat/měnit funkci jiným zaměstnancům v rámci svého rozsahu."),
    )
    muze_mit_zastupce = models.BooleanField(
        _("smí mít zástupce"), default=False,
        help_text=_("Držitel funkce si může zvolit trvalého zástupce ze stejné organizační jednotky."),
    )
    bez_seznamu_zamestnancu = models.BooleanField(
        _("bez seznamu zaměstnanců"), default=False,
        help_text=_(
            "Zapnuto: bez přístupu k seznamu jednotlivých zaměstnanců "
            "(accounts.viditelni_zamestnanci vrátí prázdný queryset) — "
            "u funkce vázané na úroveň Sekce má místo toho zaměstnanec "
            "vlastní souhrnný přehled sekce (accounts:prehled_sekce)."
        ),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("funkce")
        verbose_name_plural = _("funkce")
        ordering = ["nazev"]

    def __str__(self):
        return self.nazev

    @classmethod
    def vychozi(cls):
        """Výchozí funkce zaměstnance bez vyšší role (nahrazuje dřívější blank funkce)."""
        return cls.objects.get(kod=cls.ZAMESTNANEC)


def _vychozi_funkce_id():
    return Funkce.vychozi().pk


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
    funkce = models.ForeignKey(
        Funkce,
        on_delete=models.PROTECT,
        default=_vychozi_funkce_id,
        related_name="zamestnanci",
        verbose_name=_("funkce"),
        help_text=_(
            "Role v organizační hierarchii. U funkcí se zapnutým "
            "'synchronizuje vedoucího' přiřazení automaticky nastaví "
            "odpovídající pole 'vedoucí' na sekci/odboru/oddělení a uvolní "
            "funkci předchozímu držiteli téže jednotky."
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

    def _zastupuje_nekoho_s_pravem(self, nazev_prava):
        """Zastupuje trvale (Employee.zastupce) někoho, jehož funkce nese dané oprávnění (název příznaku na Funkce)?"""
        return Employee.objects.filter(zastupce=self, **{f"funkce__{nazev_prava}": True}).exists()

    def _ma_pravo(self, nazev_prava):
        """Nese vlastní funkce dané oprávnění (název příznaku na Funkce), nebo ho zastupuje za někoho, kdo ho má?"""
        if self.funkce_id and getattr(self.funkce, nazev_prava):
            return True
        return self._zastupuje_nekoho_s_pravem(nazev_prava)

    @property
    def muze_spravovat_zamestnance(self):
        """Smí zakládat/upravovat/přesouvat zaměstnance ve svém rozsahu (vlastní funkce, nebo trvalé zastupování za ni)."""
        return self._ma_pravo("muze_spravovat_zamestnance")

    @property
    def muze_presouvat_zamestnance(self):
        """Smí přesouvat zaměstnance mezi odděleními (vlastní funkce, nebo zastupování)."""
        return self._ma_pravo("muze_presouvat_zamestnance")

    @property
    def muze_menit_funkci(self):
        """Smí přiřazovat/měnit funkci jiným zaměstnancům (vlastní funkce, nebo zastupování)."""
        return self._ma_pravo("muze_menit_funkci")

    @property
    def muze_mit_zastupce(self):
        """Má funkci, pro kterou lze zvolit zástupce."""
        return bool(self.funkce_id and self.funkce.muze_mit_zastupce)

    @property
    def je_reditel_sekce(self):
        """Má přístup k accounts:prehled_sekce (read-only přehled celé vlastní sekce).

        Vázáno i na uroven_vazby == SEKCE (ne jen na bez_seznamu_zamestnancu) —
        jinak by budoucí admin-přidaná funkce s bez_seznamu_zamestnancu=True na
        nižší úrovni (myšlená jen jako 'skryj ze seznamu zaměstnanců') omylem
        získala i přístup k přehledu celé sekce.
        """
        return bool(
            self.funkce_id
            and self.funkce.bez_seznamu_zamestnancu
            and self.funkce.uroven_vazby == Funkce.UrovenVazby.SEKCE
        )

    def moznosti_zastupce(self):
        """Queryset kolegů ze stejné organizační jednotky, které lze zvolit jako zástupce."""
        if not self.muze_mit_zastupce:
            return Employee.objects.none()
        uroven = self.funkce.uroven_vazby
        if uroven == Funkce.UrovenVazby.ODDELENI:
            qs = Employee.objects.filter(oddeleni=self.oddeleni)
        elif uroven == Funkce.UrovenVazby.SEKCE:
            qs = Employee.objects.filter(oddeleni__odbor__sekce=self.oddeleni.odbor.sekce)
        else:  # ODBOR (a záložně ZADNA, i když s muze_mit_zastupce=True by nastat neměla)
            qs = Employee.objects.filter(oddeleni__odbor=self.oddeleni.odbor)
        return qs.filter(aktivni=True).exclude(pk=self.pk)

    def _vlastni_spravovana_oddeleni(self):
        """Oddělení spravovaná na základě vlastní funkce (bez zastupování)."""
        if not (self.funkce_id and self.funkce.muze_spravovat_zamestnance):
            return Oddeleni.objects.none()
        uroven = self.funkce.uroven_vazby
        if uroven == Funkce.UrovenVazby.ODDELENI:
            return Oddeleni.objects.filter(pk=self.oddeleni_id)
        if uroven == Funkce.UrovenVazby.ODBOR:
            return Oddeleni.objects.filter(odbor=self.oddeleni.odbor)
        if uroven == Funkce.UrovenVazby.SEKCE:
            return Oddeleni.objects.filter(odbor__sekce=self.oddeleni.odbor.sekce)
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
        """Organizační jednotka (Oddeleni/Odbor/Sekce), do jejíhož pole 'vedoucí' se má daná funkce zapsat."""
        if funkce is None or not funkce.synchronizuje_vedouciho:
            return None  # např. Sekretariát odboru nemá pole vedoucí k synchronizaci
        if funkce.uroven_vazby == Funkce.UrovenVazby.ODDELENI:
            return oddeleni
        if funkce.uroven_vazby == Funkce.UrovenVazby.ODBOR:
            return oddeleni.odbor
        if funkce.uroven_vazby == Funkce.UrovenVazby.SEKCE:
            return oddeleni.odbor.sekce
        return None

    def _drzitele_stejne_funkce(self, funkce, oddeleni):
        """Ostatní zaměstnanci, kteří mohou držet stejnou funkci na stejné jednotce (dle úrovně vazby funkce)."""
        if funkce is None:
            return Employee.objects.none()
        if funkce.uroven_vazby == Funkce.UrovenVazby.ODDELENI:
            return Employee.objects.filter(funkce=funkce, oddeleni=oddeleni)
        if funkce.uroven_vazby == Funkce.UrovenVazby.ODBOR:
            return Employee.objects.filter(funkce=funkce, oddeleni__odbor=oddeleni.odbor)
        if funkce.uroven_vazby == Funkce.UrovenVazby.SEKCE:
            return Employee.objects.filter(funkce=funkce, oddeleni__odbor__sekce=oddeleni.odbor.sekce)
        return Employee.objects.none()  # ZADNA — např. Zaměstnanec, bez dedup pravidla

    def clean(self):
        super().clean()
        if self.zastupce_id:
            if self.zastupce_id == self.pk:
                raise ValidationError({"zastupce": _("Nelze zvolit sám sebe jako zástupce.")})
            if not self.muze_mit_zastupce:
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
        vychozi_funkce = None  # Funkce.vychozi() se dotáhne líně a nejvýš jednou za save()

        # Přesun do jiného oddělení ukončuje funkci vázanou na předchozí
        # jednotku — nedává smysl zůstat "vedoucím oddělení", ze kterého
        # zaměstnanec odešel. Pokud volající v témže save() zároveň
        # explicitně nastavil jinou funkci, respektujeme ji místo mazání.
        if (
            zmenilo_se_oddeleni and stary.funkce_id == self.funkce_id
            and stary.funkce.kod != Funkce.ZAMESTNANEC
        ):
            vychozi_funkce = Funkce.vychozi()
            self.funkce = vychozi_funkce
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"funkce"}

        # Zástupce je vázán na funkci a jednotku, na které byl zvolen —
        # přesun do jiného oddělení nebo změna/zrušení funkce ho stejně
        # jako funkci samotnou zneplatní.
        if stary is not None and self.zastupce_id and (zmenilo_se_oddeleni or stary.funkce_id != self.funkce_id):
            self.zastupce = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"zastupce"}

        with transaction.atomic():
            super().save(*args, **kwargs)

            zmenila_se_funkce = stary is None or stary.funkce_id != self.funkce_id

            # _drzitele_stejne_funkce/_jednotka_pro_funkci jsou pro ZAMESTNANEC
            # (uroven_vazby=ZADNA, synchronizuje_vedouciho=False) přirozeně
            # no-op — žádné zvláštní větvení pro "bez role" tu není potřeba.
            if self.funkce_id and zmenila_se_funkce:
                if vychozi_funkce is None:
                    vychozi_funkce = Funkce.vychozi()
                self._drzitele_stejne_funkce(self.funkce, self.oddeleni).exclude(pk=self.pk).update(
                    funkce=vychozi_funkce
                )
                jednotka = self._jednotka_pro_funkci(self.funkce, self.oddeleni)
                if jednotka is not None:
                    type(jednotka).objects.filter(pk=jednotka.pk).update(vedouci=self)

            if stary is not None and stary.funkce_id and stary.funkce_id != self.funkce_id:
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

    Toto je čistě READ scope a záměrně se neřídí CRUD rozsahem
    (Employee.spravovani_zamestnanci) — ten je užší (Vedoucí oddělení smí
    spravovat jen vlastní oddělení) a jeho použití zde by vedoucím
    oddělení v přehledech schovávalo kolegy z ostatních oddělení
    vlastního odboru, které běžný zaměstnanec bez funkce vidí.

    Odvozeno z Funkce.bez_seznamu_zamestnancu a Funkce.uroven_vazby dané
    funkce zaměstnance (ne z CRUD příznaků):
    - admin (is_staff): vidí vše
    - funkce s bez_seznamu_zamestnancu (např. Ředitel sekce): nemá přístup k
      seznamu jednotlivců (má vlastní read-only přehled, viz
      accounts:prehled_sekce)
    - funkce vázaná na úroveň Odbor/Sekce (např. Ředitel odboru,
      Sekretariát odboru): celý vlastní odbor / sekce
    - funkce vázaná na úroveň Oddělení nebo bez vazby (Vedoucí oddělení i
      Zaměstnanec): celý odbor, nebo jen vlastní oddělení dle
      Odbor.zamestnanci_vidi_cely_odbor
    """
    if user.is_staff:
        return Employee.objects.filter(aktivni=True)

    if not hasattr(user, "employee"):
        return Employee.objects.none()

    employee = user.employee
    funkce = employee.funkce

    if funkce.bez_seznamu_zamestnancu:
        return Employee.objects.none()

    if funkce.uroven_vazby == Funkce.UrovenVazby.SEKCE:
        return Employee.objects.filter(oddeleni__odbor__sekce=employee.oddeleni.odbor.sekce, aktivni=True)
    if funkce.uroven_vazby == Funkce.UrovenVazby.ODBOR:
        return Employee.objects.filter(oddeleni__odbor=employee.oddeleni.odbor, aktivni=True)

    if employee.oddeleni.odbor.zamestnanci_vidi_cely_odbor:
        return Employee.objects.filter(oddeleni__odbor=employee.oddeleni.odbor, aktivni=True)
    return Employee.objects.filter(oddeleni=employee.oddeleni, aktivni=True)
