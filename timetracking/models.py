from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.exceptions import ValidationError


class WorkSession(models.Model):
    """
    Jeden pracovní blok zaměstnance (příchod → odchod).
    Zaměstnanec může mít za den více bloků (oběd apod.).
    """

    class Zdroj(models.TextChoices):
        PRICHOD = "prichod", _("Příchod přes web")
        RUCNI = "rucni", _("Ruční zápis / oprava")

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name=_("zaměstnanec"),
    )
    zacatek = models.DateTimeField(_("začátek"))
    konec = models.DateTimeField(_("konec"), null=True, blank=True)
    zdroj = models.CharField(
        _("zdroj záznamu"),
        max_length=10,
        choices=Zdroj.choices,
        default=Zdroj.PRICHOD,
    )
    poznamka = models.TextField(_("poznámka"), blank=True)
    opraveno = models.BooleanField(
        _("ručně opraveno"),
        default=False,
        help_text=_("Označeno, pokud byl záznam doplněn/opraven zpětně."),
    )
    vytvoreno = models.DateTimeField(_("vytvořeno"), auto_now_add=True)
    upraveno = models.DateTimeField(_("upraveno"), auto_now=True)

    class Meta:
        verbose_name = _("pracovní blok")
        verbose_name_plural = _("pracovní bloky")
        ordering = ["-zacatek"]

    def __str__(self):
        konec_str = self.konec.strftime("%H:%M") if self.konec else "probíhá"
        return (
            f"{self.employee} | "
            f"{self.zacatek.strftime('%d.%m.%Y %H:%M')} – {konec_str}"
        )

    def clean(self):
        if self.konec and self.zacatek and self.konec <= self.zacatek:
            raise ValidationError(_("Konec musí být po začátku."))

        # Blok nelze uzavřít, dokud v něm probíhá pohyb (jinak by ho
        # zaměstnanec už nikdy sám nemohl uzavřít přes návrat z pohybu).
        # Týká se jen uzavírání existujícího bloku — nový blok ještě nemůže
        # mít žádný navázaný pohyb.
        if self.konec and self.pk and Pohyb.objects.filter(
            work_session_id=self.pk, konec__isnull=True
        ).exists():
            raise ValidationError(
                _("Nelze uzavřít blok, dokud v něm probíhá pohyb — nejprve zapište návrat.")
            )

        # Kontrola překryvu s existujícími bloky stejného zaměstnance
        if self.zacatek:
            qs = WorkSession.objects.filter(employee=self.employee)
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            konec_filter = self.konec or timezone.now()
            if qs.filter(
                zacatek__lt=konec_filter,
                konec__gt=self.zacatek,
            ).exists():
                raise ValidationError(
                    _("Tento časový blok se překrývá s existujícím záznamem.")
                )

    @property
    def je_aktivni(self) -> bool:
        """Session ještě běží — zaměstnanec je přihlášen."""
        return self.konec is None

    def trvani_minut(self) -> int | None:
        """Délka bloku v minutách (None pokud ještě běží)."""
        if not self.konec:
            return None
        delta = self.konec - self.zacatek
        return int(delta.total_seconds() // 60)


class TypPohybu(models.Model):
    """Číselník typů pohybu během pracovní doby (oběd, lékař, soukromá záležitost...)."""

    nazev = models.CharField(_("název"), max_length=100)
    zkratka = models.CharField(_("zkratka"), max_length=10)
    zapocitava_se_do_pracovni_doby = models.BooleanField(
        _("započítává se do pracovní doby"),
        default=False,
        help_text=_(
            "Vypnuto (výchozí): doba pohybu se odečte z odpracované doby "
            "(např. oběd, soukromá záležitost). Zapnuto: doba pohybu se "
            "neodečítá, práce běží dál (např. placená přestávka)."
        ),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ pohybu")
        verbose_name_plural = _("typy pohybu")

    def __str__(self):
        return f"{self.zkratka} – {self.nazev}"


class Pohyb(models.Model):
    """
    Pohyb zaměstnance během probíhajícího pracovního bloku (odchod na
    oběd, k lékaři, soukromá záležitost...). Je vnořen do WorkSession —
    nemůže začít před jejím začátkem ani skončit po jejím konci.
    """

    work_session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="pohyby",
        verbose_name=_("pracovní blok"),
    )
    typ = models.ForeignKey(
        TypPohybu,
        on_delete=models.PROTECT,
        verbose_name=_("typ pohybu"),
    )
    zacatek = models.DateTimeField(_("začátek"))
    konec = models.DateTimeField(_("konec"), null=True, blank=True)
    poznamka = models.TextField(_("poznámka"), blank=True)
    vytvoreno = models.DateTimeField(_("vytvořeno"), auto_now_add=True)
    upraveno = models.DateTimeField(_("upraveno"), auto_now=True)

    class Meta:
        verbose_name = _("pohyb")
        verbose_name_plural = _("pohyby")
        ordering = ["-zacatek"]

    def __str__(self):
        konec_str = self.konec.strftime("%H:%M") if self.konec else "probíhá"
        return (
            f"{self.employee} | {self.typ.zkratka} | "
            f"{self.zacatek.strftime('%d.%m.%Y %H:%M')} – {konec_str}"
        )

    @property
    def employee(self):
        return self.work_session.employee

    @property
    def je_aktivni(self) -> bool:
        """Pohyb ještě probíhá — zaměstnanec se ještě nevrátil."""
        return self.konec is None

    def trvani_minut(self) -> int | None:
        """Délka pohybu v minutách (None pokud ještě probíhá)."""
        if not self.konec:
            return None
        delta = self.konec - self.zacatek
        return int(delta.total_seconds() // 60)

    def clean(self):
        if not self.work_session_id:
            return

        if self.konec and self.zacatek and self.konec <= self.zacatek:
            raise ValidationError(_("Konec pohybu musí být po jeho začátku."))

        if self.zacatek and self.zacatek < self.work_session.zacatek:
            raise ValidationError(
                _("Pohyb nemůže začít před začátkem pracovního bloku.")
            )

        horni_hranice = self.work_session.konec or timezone.now()
        if self.zacatek and self.zacatek > horni_hranice:
            raise ValidationError(_("Pohyb nemůže začít po konci pracovního bloku."))
        if self.konec and self.konec > horni_hranice:
            raise ValidationError(_("Pohyb nemůže skončit po konci pracovního bloku."))

        # Kontrola překryvu s ostatními pohyby ve stejném pracovním bloku
        # (včetně právě probíhajících, kde konec is None).
        if self.zacatek:
            qs = Pohyb.objects.filter(work_session=self.work_session)
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            konec_filter = self.konec or timezone.now()
            if qs.filter(
                models.Q(konec__isnull=True) | models.Q(konec__gt=self.zacatek),
                zacatek__lt=konec_filter,
            ).exists():
                raise ValidationError(
                    _("Tento pohyb se překrývá s jiným pohybem ve stejném bloku.")
                )


class WorkdaySummary(models.Model):
    """
    Denní souhrn odpracované doby pro jednoho zaměstnance.
    Přepočítává se po každé ukončené session (signal).

    Logika přestávek (dle zákoníku práce):
      - Odpracuje-li zaměstnanec více než 6 hodin, odečteme 30 min povinné přestávky.
      - Přestávka se nezapočítává do odpracované doby.
    """

    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="denni_souhrny",
        verbose_name=_("zaměstnanec"),
    )
    datum = models.DateField(_("datum"))

    # Hrubý čas (součet všech bloků)
    hrube_minuty = models.PositiveIntegerField(_("hrubé minuty"), default=0)

    # Povinná přestávka odečtená
    prestavka_minuty = models.PositiveIntegerField(
        _("přestávka (min)"), default=0,
        help_text=_("30 min odečteno při práci přes 6 hodin.")
    )

    # Součet pohybů, které se dle svého typu nezapočítávají do pracovní doby
    pohyby_minuty = models.PositiveIntegerField(
        _("odečtené pohyby (min)"), default=0,
        help_text=_("Součet dokončených pohybů, jejichž typ se nezapočítává do pracovní doby.")
    )

    # Čistá odpracovaná doba = hrube_minuty - prestavka_minuty - pohyby_minuty
    odpracovane_minuty = models.PositiveIntegerField(_("odpracované minuty"), default=0)

    # Přesčas = odpracovane_minuty − (úvazek hodin × 60)
    prescos_minuty = models.IntegerField(_("přesčas (min)"), default=0)

    je_svatek = models.BooleanField(_("státní svátek"), default=False)
    je_vikend = models.BooleanField(_("víkend"), default=False)

    class Meta:
        verbose_name = _("denní souhrn")
        verbose_name_plural = _("denní souhrny")
        unique_together = [("employee", "datum")]
        ordering = ["-datum"]

    def __str__(self):
        return (
            f"{self.employee} | {self.datum} | "
            f"{self.odpracovane_minuty // 60}h {self.odpracovane_minuty % 60}min"
        )

    @classmethod
    def prepocitej(cls, employee, datum):
        """
        Přepočítá denní souhrn pro daného zaměstnance a datum.
        Volá se ze signálu po uložení WorkSession.
        """
        from accounts.holidays_model import StatniSvatek

        sessions = WorkSession.objects.filter(
            employee=employee,
            zacatek__date=datum,
            konec__isnull=False,
        )

        hrube_minuty = sum(s.trvani_minut() or 0 for s in sessions)

        # Pohyby, jejichž typ se nezapočítává do pracovní doby, se odečtou
        # stejně jako povinná přestávka. Jen dokončené pohyby v už uzavřených
        # blocích — probíhající pohyb i probíhající blok mají neznámou/ještě
        # nezapočítanou délku, přepočet proběhne znovu při jejich uzavření.
        # Bez podmínky na work_session__konec by pohyb v ještě otevřeném
        # bloku odečítal čas z jiných, už uzavřených bloků téhož dne.
        pohyby = Pohyb.objects.filter(
            work_session__employee=employee,
            work_session__zacatek__date=datum,
            work_session__konec__isnull=False,
            konec__isnull=False,
            typ__zapocitava_se_do_pracovni_doby=False,
        )
        pohyby_minuty = sum(p.trvani_minut() or 0 for p in pohyby)

        # Povinná přestávka po 6 hodinách
        break_threshold = getattr(settings, "BREAK_THRESHOLD_HOURS", 6) * 60
        mandatory_break = getattr(settings, "MANDATORY_BREAK_MINUTES", 30)
        prestavka = mandatory_break if hrube_minuty > break_threshold else 0

        odpracovane = max(hrube_minuty - prestavka - pohyby_minuty, 0)

        # Přesčas
        uvazek_minut = int(
            employee.typ_uvazku.hodiny_denne * Decimal("60")
        )
        prescos = odpracovane - uvazek_minut

        je_svatek = StatniSvatek.objects.filter(datum=datum).exists()
        je_vikend = datum.weekday() >= 5  # Sat=5, Sun=6

        obj, _ = cls.objects.update_or_create(
            employee=employee,
            datum=datum,
            defaults={
                "hrube_minuty": hrube_minuty,
                "prestavka_minuty": prestavka,
                "pohyby_minuty": pohyby_minuty,
                "odpracovane_minuty": odpracovane,
                "prescos_minuty": prescos,
                "je_svatek": je_svatek,
                "je_vikend": je_vikend,
            },
        )
        return obj
