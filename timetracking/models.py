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

    # Čistá odpracovaná doba = hrube_minuty - prestavka_minuty
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

        # Povinná přestávka po 6 hodinách
        break_threshold = getattr(settings, "BREAK_THRESHOLD_HOURS", 6) * 60
        mandatory_break = getattr(settings, "MANDATORY_BREAK_MINUTES", 30)
        prestavka = mandatory_break if hrube_minuty > break_threshold else 0

        odpracovane = max(hrube_minuty - prestavka, 0)

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
                "odpracovane_minuty": odpracovane,
                "prescos_minuty": prescos,
                "je_svatek": je_svatek,
                "je_vikend": je_vikend,
            },
        )
        return obj
