from datetime import datetime, timedelta
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.exceptions import ValidationError


def popis_intervalu(zacatek, konec):
    """Časový úsek v místním čase pro chybové hlášky, např. "22. 9. 7:59–13:14"
    nebo "21. 9. 6:39 – 22. 9. 7:59" přes půlnoc; otevřený konec jako "(probíhá)"."""
    od = timezone.localtime(zacatek)
    text_od = f"{od.day}. {od.month}. {od.hour}:{od.minute:02d}"
    if konec is None:
        return f"{text_od} – (probíhá)"
    do = timezone.localtime(konec)
    if do.date() == od.date():
        return f"{text_od}–{do.hour}:{do.minute:02d}"
    return f"{text_od} – {do.day}. {do.month}. {do.hour}:{do.minute:02d}"


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
        konec_str = timezone.localtime(self.konec).strftime("%H:%M") if self.konec else "probíhá"
        return (
            f"{self.employee} | "
            f"{timezone.localtime(self.zacatek).strftime('%d.%m.%Y %H:%M')} – {konec_str}"
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

        # Konec bloku nesmí být dřív, než skončil poslední (už uzavřený) pohyb
        # v něm — jinak by šel zpětně zkrátit blok "pod" pohyb, který v něm
        # platně proběhl (např. přes rychlou akci Odchod s vlastním časem,
        # nebo přes ruční opravu záznamu).
        if self.konec and self.pk:
            posledni_konec_pohybu = Pohyb.objects.filter(
                work_session_id=self.pk, konec__isnull=False
            ).aggregate(models.Max("konec"))["konec__max"]
            if posledni_konec_pohybu and self.konec < posledni_konec_pohybu:
                raise ValidationError(
                    _("Konec bloku nemůže být dřív, než skončil pohyb, který v něm proběhl.")
                )

        # Kontrola překryvu s existujícími bloky stejného zaměstnance
        if self.zacatek:
            qs = WorkSession.objects.filter(employee=self.employee)
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            konec_filter = self.konec or timezone.now()
            kolize = qs.filter(
                zacatek__lt=konec_filter,
                konec__gt=self.zacatek,
            ).order_by("zacatek").first()
            if kolize:
                raise ValidationError(
                    _("Tento časový blok se překrývá s blokem %(blok)s."),
                    params={"blok": popis_intervalu(kolize.zacatek, kolize.konec)},
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

    class Zapocitani(models.TextChoices):
        NE = "NE", _("Nezapočítává se (odečte se z odpracované doby)")
        ANO = "ANO", _("Započítává se celý")
        JADRO = "JADRO", _("Započítává se jen v jádrové době (mimo ni se odečte)")

    zapocitani_pevna = models.CharField(
        _("započítání u pevné pracovní doby"),
        max_length=5,
        choices=[
            (Zapocitani.ANO, _("Započítává se (neodečítá se)")),
            (Zapocitani.NE, _("Nezapočítává se (odečte se část uvnitř pracovního bloku)")),
        ],
        default=Zapocitani.ANO,
        help_text=_(
            "Jak se doba pohybu počítá zaměstnancům s pevnou pracovní dobou. "
            "Započítává se: odpracovaná doba je dána jen pracovním blokem a "
            "pohyb ji nesnižuje. Nezapočítává se: část pohybu, která leží "
            "uvnitř pracovního bloku daného dne, se z odpracované doby odečte."
        ),
    )
    zapocitani_pruzna = models.CharField(
        _("započítání u pružné pracovní doby"),
        max_length=5,
        choices=Zapocitani.choices,
        default=Zapocitani.NE,
        help_text=_(
            "Jak se doba pohybu počítá zaměstnancům s pružnou pracovní dobou. "
            "Nezapočítává se (výchozí): doba pohybu se odečte (např. oběd, "
            "soukromá záležitost). Započítává se: neodečítá se (např. placená "
            "přestávka). Jen v jádrové době: započítá se část v pevné (jádrové) "
            "době, např. 9–14 hod., část mimo ni se odečte."
        ),
    )
    zobrazuje_se_na_pracovisti = models.BooleanField(
        _("zobrazuje se na pracovišti"),
        default=False,
        help_text=_(
            "Zatím jen evidence — denní přehled přítomnosti tento příznak "
            "nečte, takže na nic nemá vliv. Zamýšlený význam: zapnuto = "
            "zaměstnanec je po dobu pohybu nadále veden jako na pracovišti "
            "(např. přestávka v areálu), vypnuto (výchozí) = pohyb znamená "
            "nepřítomnost na pracovišti (např. lékař, soukromá záležitost)."
        ),
    )
    ukoncit_na_konec_bloku = models.BooleanField(
        _("ukončit na konci pracovního bloku"),
        default=False,
        help_text=_(
            "Jen pro pevnou pracovní dobu: pohyb, který zaměstnanec neukončí "
            "týž den (např. služební cesta, lékař), noční údržba sama ukončí "
            "na konci pracovního bloku daného dne — spolu s pracovním blokem, "
            "ve kterém běží. Vypnuto (výchozí): zapomenutý pohyb se jen "
            "označí k ruční opravě."
        ),
    )
    aktivni = models.BooleanField(_("aktivní"), default=True)

    class Meta:
        verbose_name = _("typ pohybu")
        verbose_name_plural = _("typy pohybu")

    def __str__(self):
        return f"{self.zkratka} – {self.nazev}"

    def zapocitani_pro(self, typ_uvazku):
        """Jak se tento pohyb počítá do odpracované doby u daného typu úvazku
        (hodnota `Zapocitani`) — podle toho, jde-li o pevnou, nebo pružnou dobu."""
        from accounts.models import TypUvazku

        if typ_uvazku.druh_pracovni_doby == TypUvazku.DruhPracovniDoby.PEVNA:
            return self.zapocitani_pevna
        return self.zapocitani_pruzna


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
        konec_str = timezone.localtime(self.konec).strftime("%H:%M") if self.konec else "probíhá"
        return (
            f"{self.employee} | {self.typ.zkratka} | "
            f"{timezone.localtime(self.zacatek).strftime('%d.%m.%Y %H:%M')} – {konec_str}"
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
            kolize = qs.filter(
                models.Q(konec__isnull=True) | models.Q(konec__gt=self.zacatek),
                zacatek__lt=konec_filter,
            ).select_related("typ").order_by("zacatek").first()
            if kolize:
                raise ValidationError(
                    _("Tento pohyb se překrývá s pohybem %(typ)s %(cas)s ve stejném bloku."),
                    params={
                        "typ": kolize.typ.nazev,
                        "cas": popis_intervalu(kolize.zacatek, kolize.konec),
                    },
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
        help_text=_(
            "Součet dokončených pohybů, jejichž typ se nezapočítává do "
            "pracovní doby, a u pružné pracovní doby i té části pohybů "
            "„započítávaných u pružné pracovní doby“, která leží mimo "
            "jádrovou (pevnou) dobu úvazku."
        )
    )

    # Čistá odpracovaná doba = hrube_minuty - prestavka_minuty - pohyby_minuty
    odpracovane_minuty = models.PositiveIntegerField(_("odpracované minuty"), default=0)

    # Přesčas = odpracovane_minuty − denní norma (pružná: hodiny_denne × 60; pevná: čistá doba bloků toho dne)
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

    @property
    def je_zapocitan(self):
        """Má den aspoň jeden uzavřený blok? Jen takový se počítá do přesčasu/nedostatku
        (den jen s otevřeným blokem má uloženo −norma, ale ještě není dokončený)."""
        return self.hrube_minuty > 0

    @property
    def denni_prescas_minuty(self):
        """Přesčas dne = kladná část podepsané bilance prescos_minuty (0, když den není započítaný)."""
        return max(self.prescos_minuty, 0) if self.je_zapocitan else 0

    @property
    def denni_nedostatek_minuty(self):
        """Nedostatek dne = absolutní hodnota záporné části prescos_minuty (0, když den není započítaný)."""
        return max(-self.prescos_minuty, 0) if self.je_zapocitan else 0

    @classmethod
    def prepocitej(cls, employee, datum):
        """
        Přepočítá denní souhrn pro daného zaměstnance a datum.
        Volá se ze signálu po uložení WorkSession.
        """
        from accounts.holidays_model import StatniSvatek
        from accounts.models import CasovyBlokUvazku, TypUvazku

        sessions = WorkSession.objects.filter(
            employee=employee,
            zacatek__date=datum,
            konec__isnull=False,
        )

        je_pevna = (
            employee.typ_uvazku.druh_pracovni_doby
            == TypUvazku.DruhPracovniDoby.PEVNA
        )

        # Povinná přestávka po 6 hodinách
        break_threshold = getattr(settings, "BREAK_THRESHOLD_HOURS", 6) * 60
        mandatory_break = getattr(settings, "MANDATORY_BREAK_MINUTES", 30)

        # Dokončené pohyby v už uzavřených blocích — probíhající pohyb i probíhající
        # blok mají neznámou/ještě nezapočítanou délku, přepočet proběhne znovu při
        # jejich uzavření. Bez podmínky na work_session__konec by pohyb v ještě
        # otevřeném bloku odečítal čas z jiných, už uzavřených bloků téhož dne.
        zavrene_pohyby = Pohyb.objects.filter(
            work_session__employee=employee,
            work_session__zacatek__date=datum,
            work_session__konec__isnull=False,
            konec__isnull=False,
        ).select_related("typ")

        Zapocitani = TypPohybu.Zapocitani

        def prekryv_minut(od1, do1, od2, do2):
            od, do = max(od1, od2), min(do1, do2)
            return int((do - od).total_seconds() // 60) if do > od else 0

        # Bloky, mezi nimiž je mezera jen jedna minuta (konec 11:17, další začátek
        # 11:18), jsou jeden souvislý blok — zaměstnanec odešel a přišel hned,
        # čas se zapisuje na minuty a ta jedna minuta mezi nimi se nemá ztratit.
        intervaly = []
        for s in sorted(sessions, key=lambda x: x.zacatek):
            minuta_zacatku = s.zacatek.replace(second=0, microsecond=0)
            minuta_konce = intervaly[-1][1].replace(second=0, microsecond=0) if intervaly else None
            if intervaly and minuta_zacatku - minuta_konce <= timedelta(minutes=1):
                intervaly[-1][1] = max(intervaly[-1][1], s.konec)
            else:
                intervaly.append([s.zacatek, s.konec])

        pohyby_minuty = 0

        if je_pevna:
            # U pevné pracovní doby se počítá jen čas ležící uvnitř bloků
            # zaškrtnutých pro daný den v týdnu — den bez zaškrtnutého bloku
            # dá 0 minut, i když WorkSession existuje (čas mimo blok se
            # nezapočítá ani jako práce, ani jako přesčas/nedostatek).
            den_pole = CasovyBlokUvazku.DNY_V_TYDNU[datum.weekday()]
            bloky_dne = [
                (
                    timezone.make_aware(datetime.combine(datum, blok.blok_od)),
                    timezone.make_aware(datetime.combine(datum, blok.blok_do)),
                )
                for blok in CasovyBlokUvazku.objects.filter(
                    typ_uvazku=employee.typ_uvazku, **{den_pole: True}
                )
            ]
            hrube_minuty = sum(
                prekryv_minut(od, do, blok_od, blok_do)
                for od, do in intervaly
                for blok_od, blok_do in bloky_dne
            )

            # Pohyby se u pevné doby neodečítají, pokud jejich typ má u pevné doby
            # „započítává se“ (výchozí) — odpracovaná doba je pak dána jen blokem.
            # Typ s „nezapočítává se“ odečte část pohybu ležící uvnitř bloku.
            for p in zavrene_pohyby.filter(typ__zapocitani_pevna=Zapocitani.NE):
                pohyby_minuty += sum(
                    prekryv_minut(p.zacatek, p.konec, blok_od, blok_do)
                    for blok_od, blok_do in bloky_dne
                )

            # Denní norma pevné doby je čistá doba bloků toho dne, ne paušální
            # hodiny_denne — viz TypUvazku.norma_minut(). Pátek 7:30–15:00 (7 h
            # čistého času) by jinak při odpracování celého bloku ukázal nedostatek.
        else:
            hrube_minuty = sum(int((do - od).total_seconds() // 60) for od, do in intervaly)

            # Pružná doba: „nezapočítává se“ odečte celý pohyb stejně jako povinnou
            # přestávku, „započítává se“ ho neodečte vůbec a „jen v jádrové době“
            # odečte jen část ležící mimo jádro (první časový blok úvazku).
            jadro = CasovyBlokUvazku.objects.filter(
                typ_uvazku=employee.typ_uvazku
            ).first()
            jadro_od = jadro_do = None
            if jadro:
                jadro_od = timezone.make_aware(datetime.combine(datum, jadro.blok_od))
                jadro_do = timezone.make_aware(datetime.combine(datum, jadro.blok_do))

            for p in zavrene_pohyby.exclude(typ__zapocitani_pruzna=Zapocitani.ANO):
                trvani = p.trvani_minut() or 0
                if p.typ.zapocitani_pruzna == Zapocitani.NE:
                    pohyby_minuty += trvani
                elif jadro:
                    pohyby_minuty += max(
                        trvani - prekryv_minut(p.zacatek, p.konec, jadro_od, jadro_do), 0
                    )

        prestavka = mandatory_break if hrube_minuty > break_threshold else 0

        odpracovane = max(hrube_minuty - prestavka - pohyby_minuty, 0)

        # Přesčas / nedostatek proti denní normě úvazku (pevná doba: z bloků dne).
        # Schválená hodinová dovolená dne se do normy započítá — 6 h práce + 2 h
        # dovolené na osmihodinovém dni je vyrovnaná bilance (#82).
        from leaves.models import ZadostOStav

        volno = ZadostOStav.hodinove_volno_minuty(employee, datum)
        prescos = odpracovane + volno - employee.typ_uvazku.norma_minut(datum)

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
