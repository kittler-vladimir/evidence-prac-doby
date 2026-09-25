import re
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from django.utils import timezone

from django_celery_beat.models import PeriodicTask

from accounts.models import User, Employee, Funkce, Sekce, Odbor, Oddeleni, TypUvazku, CasovyBlokUvazku
from timetracking.opravy import ZNACKA_POHYB, ZNACKA_SESSION, zaznamy_k_oprave
from timetracking.bilance import format_minut, rozdel_na_tydny, secti
from timetracking.forms import WorkSessionOpravitForm, PohybRucneForm
from timetracking.models import WorkSession, WorkdaySummary, TypPohybu, Pohyb
from timetracking.tasks import close_open_sessions as close_open_sessions_task


def vytvor_zamestnance(email="zamestnanec@example.com", osobni_cislo="0001"):
    user = User.objects.create_user(
        username=email, email=email, password="testpass123",
        first_name="Test", last_name="Zaměstnanec",
    )
    sekce = Sekce.objects.create(nazev="Sekce", kod=f"S-{osobni_cislo}")
    odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod=f"O-{osobni_cislo}")
    oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod=f"OD-{osobni_cislo}")
    typ_uvazku = TypUvazku.objects.create(
        nazev="Plný úvazek", hodiny_denne=8, hodiny_tyydne=40,
    )
    return Employee.objects.create(
        user=user, osobni_cislo=osobni_cislo, oddeleni=oddeleni,
        typ_uvazku=typ_uvazku, datum_nastupu=timezone.localdate(),
    )


class PohybModelTests(TestCase):
    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ_neuznavany = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        self.typ_uznavany = TypPohybu.objects.create(
            nazev="Placená přestávka", zkratka="PP", zapocitava_se_do_pracovni_doby=True,
        )
        zacatek = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        self.session = WorkSession.objects.create(
            employee=self.employee, zacatek=zacatek,
            konec=zacatek + timedelta(hours=8),
        )

    def test_pohyb_musi_byt_uvnitr_session(self):
        pohyb = Pohyb(
            work_session=self.session,
            typ=self.typ_neuznavany,
            zacatek=self.session.zacatek - timedelta(hours=1),
            konec=self.session.zacatek,
        )
        with self.assertRaises(ValidationError):
            pohyb.full_clean()

    def test_prekryvajici_se_pohyby_jsou_odmitnuty(self):
        Pohyb.objects.create(
            work_session=self.session,
            typ=self.typ_neuznavany,
            zacatek=self.session.zacatek + timedelta(hours=1),
            konec=self.session.zacatek + timedelta(hours=2),
        )
        prekryvajici = Pohyb(
            work_session=self.session,
            typ=self.typ_neuznavany,
            zacatek=self.session.zacatek + timedelta(hours=1, minutes=30),
            konec=self.session.zacatek + timedelta(hours=2, minutes=30),
        )
        with self.assertRaises(ValidationError):
            prekryvajici.full_clean()

    def test_neuznavany_pohyb_se_odecte_z_odpracovane_doby(self):
        Pohyb.objects.create(
            work_session=self.session,
            typ=self.typ_neuznavany,
            zacatek=self.session.zacatek + timedelta(hours=1),
            konec=self.session.zacatek + timedelta(hours=1, minutes=30),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        # 8h session - 30min povinná přestávka (>6h) - 30min neuznaný pohyb
        self.assertEqual(souhrn.pohyby_minuty, 30)
        self.assertEqual(souhrn.odpracovane_minuty, 8 * 60 - 30 - 30)

    def test_uznavany_pohyb_se_neodecita(self):
        Pohyb.objects.create(
            work_session=self.session,
            typ=self.typ_uznavany,
            zacatek=self.session.zacatek + timedelta(hours=1),
            konec=self.session.zacatek + timedelta(hours=1, minutes=30),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        self.assertEqual(souhrn.pohyby_minuty, 0)
        self.assertEqual(souhrn.odpracovane_minuty, 8 * 60 - 30)

    def test_pohyb_v_otevrenem_bloku_se_neodecita_predcasne(self):
        # Jiný den než setUp's self.session, ať se souhrny nesčítají dohromady.
        # Uzavřený blok ten den (60 min), bez přestávky (< 6h práh).
        uzavreny_den = (self.session.zacatek - timedelta(days=1)).replace(hour=6, minute=0)
        WorkSession.objects.create(
            employee=self.employee,
            zacatek=uzavreny_den,
            konec=uzavreny_den + timedelta(minutes=60),
        )
        # Ještě otevřený blok se stejným dnem, s pohybem uvnitř.
        otevreny_blok = WorkSession.objects.create(
            employee=self.employee, zacatek=uzavreny_den + timedelta(hours=2),
        )
        Pohyb.objects.create(
            work_session=otevreny_blok,
            typ=self.typ_neuznavany,
            zacatek=otevreny_blok.zacatek + timedelta(minutes=10),
            konec=otevreny_blok.zacatek + timedelta(minutes=40),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, uzavreny_den.date())
        # Pohyb v ještě otevřeném bloku nesmí odečítat z už uzavřeného bloku.
        self.assertEqual(souhrn.hrube_minuty, 60)
        self.assertEqual(souhrn.pohyby_minuty, 0)
        self.assertEqual(souhrn.odpracovane_minuty, 60)


class PruznaPracovniDobaPohybTests(TestCase):
    """Pohyb se 'zapocitava_se_u_pruzne_pracovni_doby' se u pružné pracovní
    doby počítá do odpracované doby jen v jádrové (pevné) části úvazku."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.employee.typ_uvazku.druh_pracovni_doby = TypUvazku.DruhPracovniDoby.PRUZNA
        self.employee.typ_uvazku.save()
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.employee.typ_uvazku,
            blok_od="09:00",
            blok_do="14:00",
        )
        self.typ = TypPohybu.objects.create(
            nazev="Placená přestávka", zkratka="PP",
            zapocitava_se_do_pracovni_doby=True,
            zapocitava_se_u_pruzne_pracovni_doby=True,
        )
        # Sestaveno přes make_aware/combine (ne .replace() na aware "now"),
        # aby čas 07:00 byl skutečně lokální čas 07:00 a ne 07:00 UTC, které
        # se v letním čase (UTC+2) posouvá na 09:00 lokálně a spadá do jádra.
        zacatek = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(7, 0))
        )
        self.session = WorkSession.objects.create(
            employee=self.employee, zacatek=zacatek,
            konec=zacatek + timedelta(hours=9),
        )

    def test_pohyb_cely_uvnitr_jadra_se_neodecita(self):
        Pohyb.objects.create(
            work_session=self.session, typ=self.typ,
            zacatek=self.session.zacatek + timedelta(hours=3),  # 10:00
            konec=self.session.zacatek + timedelta(hours=3, minutes=30),  # 10:30
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        self.assertEqual(souhrn.pohyby_minuty, 0)

    def test_pohyb_cely_mimo_jadro_se_odecita_cely(self):
        Pohyb.objects.create(
            work_session=self.session, typ=self.typ,
            zacatek=self.session.zacatek + timedelta(minutes=30),  # 07:30
            konec=self.session.zacatek + timedelta(hours=1),  # 08:00
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        self.assertEqual(souhrn.pohyby_minuty, 30)

    def test_pohyb_castecne_v_jadru_se_odecita_jen_mimo_jadro(self):
        Pohyb.objects.create(
            work_session=self.session, typ=self.typ,
            zacatek=self.session.zacatek + timedelta(hours=1, minutes=30),  # 08:30
            konec=self.session.zacatek + timedelta(hours=2, minutes=30),  # 09:30
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        # 08:30-09:00 mimo jádro (30 min), 09:00-09:30 v jádru (30 min).
        self.assertEqual(souhrn.pohyby_minuty, 30)

    def test_pevna_pracovni_doba_se_jadrem_neomezuje(self):
        self.employee.typ_uvazku.druh_pracovni_doby = TypUvazku.DruhPracovniDoby.PEVNA
        self.employee.typ_uvazku.save()
        Pohyb.objects.create(
            work_session=self.session, typ=self.typ,
            zacatek=self.session.zacatek + timedelta(minutes=30),  # 07:30, mimo jádro
            konec=self.session.zacatek + timedelta(hours=1),  # 08:00
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.session.zacatek.date())
        self.assertEqual(souhrn.pohyby_minuty, 0)


class PevnaPracovniDobaVypocetTests(TestCase):
    """Issue #47 — u pevné pracovní doby se odpracovaná doba ořízne na časové
    bloky zaškrtnuté pro daný den v týdnu; mimo blok se nepočítá nic (ani jako
    práce, ani jako přesčas/nedostatek) a pohyby se nikdy neodečítají."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.employee.typ_uvazku.druh_pracovni_doby = TypUvazku.DruhPracovniDoby.PEVNA
        self.employee.typ_uvazku.save()
        dnes = timezone.localdate()
        self.pondeli = dnes - timedelta(days=dnes.weekday())
        self.patek = self.pondeli + timedelta(days=4)
        self.sobota = self.pondeli + timedelta(days=5)
        # Přesně scénář ze zadání: po-čt jeden (delší) blok, pátek kratší blok.
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.employee.typ_uvazku,
            blok_od="07:30", blok_do="16:15",
            pondeli=True, utery=True, streda=True, ctvrtek=True,
        )
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.employee.typ_uvazku,
            blok_od="07:30", blok_do="15:00",
            patek=True,
        )

    @staticmethod
    def _cas(datum, hodina, minuta=0):
        return timezone.make_aware(datetime.combine(datum, time(hodina, minuta)))

    def test_cas_mimo_blok_se_neodecita(self):
        WorkSession.objects.create(
            employee=self.employee,
            zacatek=self._cas(self.pondeli, 7, 0),
            konec=self._cas(self.pondeli, 17, 0),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.pondeli)
        self.assertEqual(souhrn.hrube_minuty, 525)  # jen 07:30–16:15, ne celých 10h
        self.assertEqual(souhrn.prestavka_minuty, 30)
        self.assertEqual(souhrn.odpracovane_minuty, 495)

    def test_den_bez_zadaneho_bloku_da_nulu(self):
        WorkSession.objects.create(
            employee=self.employee,
            zacatek=self._cas(self.sobota, 9, 0),
            konec=self._cas(self.sobota, 12, 0),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.sobota)
        self.assertEqual(souhrn.hrube_minuty, 0)
        self.assertEqual(souhrn.odpracovane_minuty, 0)

    def test_patecni_blok_je_kratsi_nez_v_tydnu(self):
        WorkSession.objects.create(
            employee=self.employee,
            zacatek=self._cas(self.patek, 7, 30),
            konec=self._cas(self.patek, 15, 0),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.patek)
        self.assertEqual(souhrn.hrube_minuty, 450)  # 7h30min, ne 8h45min jako po-čt
        self.assertEqual(souhrn.odpracovane_minuty, 420)

    def test_pohyb_uvnitr_bloku_se_nikdy_neodecita(self):
        """Na rozdíl od pružné pracovní doby se u pevné pohyby neodečítají
        vůbec — bez ohledu na TypPohybu.zapocitava_se_do_pracovni_doby."""
        typ = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        session = WorkSession.objects.create(
            employee=self.employee,
            zacatek=self._cas(self.pondeli, 7, 30),
            konec=self._cas(self.pondeli, 16, 15),
        )
        Pohyb.objects.create(
            work_session=session, typ=typ,
            zacatek=self._cas(self.pondeli, 12, 0),
            konec=self._cas(self.pondeli, 12, 30),
        )
        souhrn = WorkdaySummary.prepocitej(self.employee, self.pondeli)
        self.assertEqual(souhrn.pohyby_minuty, 0)
        self.assertEqual(souhrn.odpracovane_minuty, 495)

    def test_den_bez_session_neni_ovlivnen(self):
        souhrn = WorkdaySummary.prepocitej(self.employee, self.pondeli)
        self.assertEqual(souhrn.hrube_minuty, 0)
        self.assertEqual(souhrn.odpracovane_minuty, 0)


class ClockOutBlockedByOpenPohybTests(TestCase):
    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        self.client = Client()
        self.client.force_login(self.employee.user)
        self.session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=1),
        )

    def test_clock_out_odmitnut_pri_otevrenem_pohybu(self):
        Pohyb.objects.create(
            work_session=self.session, typ=self.typ, zacatek=timezone.now(),
        )
        self.client.post(reverse("timetracking:clock_out"))
        self.session.refresh_from_db()
        self.assertIsNone(self.session.konec)

    def test_clock_out_projde_bez_otevreneho_pohybu(self):
        self.client.post(reverse("timetracking:clock_out"))
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.konec)

    def test_start_pohyb_bez_typu_nespada(self):
        response = self.client.post(reverse("timetracking:start_pohyb"), {"typ_id": ""})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Pohyb.objects.filter(work_session=self.session).exists())

    def test_start_pohyb_s_neplatnym_typem_nespada(self):
        response = self.client.post(reverse("timetracking:start_pohyb"), {"typ_id": "abc"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Pohyb.objects.filter(work_session=self.session).exists())

    def test_uzavreni_bloku_s_otevrenym_pohybem_je_odmitnuto_na_urovni_modelu(self):
        pohyb = Pohyb.objects.create(
            work_session=self.session, typ=self.typ, zacatek=timezone.now(),
        )
        self.session.konec = timezone.now()
        with self.assertRaises(ValidationError):
            self.session.full_clean()
        pohyb.refresh_from_db()
        self.assertIsNone(pohyb.konec)


def _souhrn(datum, prescos, hrube=480):
    return WorkdaySummary(datum=datum, hrube_minuty=hrube, prescos_minuty=prescos)


class FormatMinutTests(SimpleTestCase):
    def test_absolutni_hodnota_bez_znamenka(self):
        for minuty, ocekavano in [
            (0, "0h 0min"), (59, "0h 59min"), (60, "1h 0min"), (61, "1h 1min"),
            (90, "1h 30min"), (-90, "1h 30min"), (-60, "1h 0min"), (-1, "0h 1min"),
        ]:
            with self.subTest(minuty=minuty):
                self.assertEqual(format_minut(minuty), ocekavano)

    def test_znamenko_jen_u_zaporne_bilance(self):
        self.assertEqual(format_minut(-90, se_znamenkem=True), "−1h 30min")
        self.assertEqual(format_minut(-1, se_znamenkem=True), "−0h 1min")
        self.assertEqual(format_minut(90, se_znamenkem=True), "1h 30min")
        self.assertEqual(format_minut(0, se_znamenkem=True), "0h 0min")

    def test_zaporna_hodnota_nikdy_nedava_zaporne_minuty(self):
        # regrese: -90 // 60 == -2 a -90 % 60 == 30 vedlo k "-2h 30min"
        self.assertNotIn("-2h", format_minut(-90, se_znamenkem=True))
        self.assertNotIn("-2h", format_minut(-90))


class DenniPrescasANedostatekTests(SimpleTestCase):
    def test_kladna_bilance_je_prescas(self):
        s = _souhrn(date(2026, 9, 7), 45)
        self.assertEqual((s.denni_prescas_minuty, s.denni_nedostatek_minuty), (45, 0))

    def test_zaporna_bilance_je_nedostatek(self):
        s = _souhrn(date(2026, 9, 8), -90)
        self.assertEqual((s.denni_prescas_minuty, s.denni_nedostatek_minuty), (0, 90))

    def test_den_presne_na_norme_nema_nic(self):
        s = _souhrn(date(2026, 9, 8), 0)
        self.assertEqual((s.denni_prescas_minuty, s.denni_nedostatek_minuty), (0, 0))

    def test_den_bez_uzavreneho_bloku_se_nezapocita(self):
        s = _souhrn(date(2026, 9, 9), -480, hrube=0)
        self.assertFalse(s.je_zapocitan)
        self.assertEqual((s.denni_prescas_minuty, s.denni_nedostatek_minuty), (0, 0))


class RozdeleniNaTydnyTests(SimpleTestCase):
    def test_tydenni_a_mesicni_soucty(self):
        souhrny = [
            _souhrn(date(2026, 9, 7), 45),
            _souhrn(date(2026, 9, 8), -90),
            _souhrn(date(2026, 9, 9), -480, hrube=0),  # jen otevřený blok
            _souhrn(date(2026, 9, 10), -30),
        ]
        tydny = rozdel_na_tydny(souhrny, 2026, 9)
        self.assertEqual(len(tydny), 1)
        tyden = tydny[0]
        self.assertEqual((tyden.cislo, tyden.od, tyden.do), (37, date(2026, 9, 7), date(2026, 9, 13)))
        self.assertEqual((tyden.bilance.prescas, tyden.bilance.nedostatek, tyden.bilance.bilance), (45, 120, -75))
        celkem = secti(souhrny)
        self.assertEqual((celkem.prescas, celkem.nedostatek, celkem.bilance), (45, 120, -75))
        self.assertEqual(format_minut(celkem.bilance, se_znamenkem=True), "−1h 15min")

    def test_tyden_zasahujici_do_sousedniho_mesice_je_orezany(self):
        # 1. 9. 2026 je úterý ISO týdne 36 (pondělí 31. 8.); 30. 9. je středa týdne 40 (do 4. 10.)
        souhrny = [_souhrn(date(2026, 9, 1), 10), _souhrn(date(2026, 9, 30), -20)]
        prvni, posledni = rozdel_na_tydny(souhrny, 2026, 9)
        self.assertEqual((prvni.cislo, prvni.od, prvni.do), (36, date(2026, 9, 1), date(2026, 9, 6)))
        self.assertEqual((posledni.cislo, posledni.od, posledni.do), (40, date(2026, 9, 28), date(2026, 9, 30)))

    def test_iso_tyden_pres_hranici_roku(self):
        # ISO týden 1/2026 začíná v pondělí 29. 12. 2025
        (tyden,) = rozdel_na_tydny([_souhrn(date(2026, 1, 1), 5)], 2026, 1)
        self.assertEqual((tyden.cislo, tyden.od, tyden.do), (1, date(2026, 1, 1), date(2026, 1, 4)))

    def test_prosinec_konci_31_12(self):
        (tyden,) = rozdel_na_tydny([_souhrn(date(2026, 12, 31), 5)], 2026, 12)
        self.assertEqual(tyden.do, date(2026, 12, 31))

    def test_mesic_bez_zaznamu(self):
        self.assertEqual(rozdel_na_tydny([], 2026, 9), [])
        self.assertEqual((secti([]).prescas, secti([]).nedostatek), (0, 0))

    def test_zamestnanec_jen_s_nedostatkem(self):
        celkem = secti([_souhrn(date(2026, 9, 7), -30), _souhrn(date(2026, 9, 8), -60)])
        self.assertEqual((celkem.prescas, celkem.nedostatek, celkem.bilance), (0, 90, -90))


class PrehledMesiceViewTests(TestCase):
    """Issue #34 — Výkaz ukazuje přesčas a nedostatek zvlášť, se souhrny po týdnech."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.client = Client()
        self.client.force_login(self.employee.user)
        # Po 7.9. (+45), Út 8.9. (-90), rozpracovaný den 9.9. (bez uzavřeného bloku), Čt 10.9. (-30)
        WorkdaySummary.objects.create(
            employee=self.employee, datum=date(2026, 9, 7),
            hrube_minuty=525, odpracovane_minuty=525, prescos_minuty=45,
        )
        WorkdaySummary.objects.create(
            employee=self.employee, datum=date(2026, 9, 8),
            hrube_minuty=390, odpracovane_minuty=390, prescos_minuty=-90,
        )
        WorkdaySummary.objects.create(
            employee=self.employee, datum=date(2026, 9, 9),
            hrube_minuty=0, odpracovane_minuty=0, prescos_minuty=-480,
        )
        WorkdaySummary.objects.create(
            employee=self.employee, datum=date(2026, 9, 10),
            hrube_minuty=450, odpracovane_minuty=450, prescos_minuty=-30,
        )

    def test_tydenni_a_mesicni_souhrny_a_zadne_zaporne_hodiny(self):
        response = self.client.get(reverse("timetracking:prehled_mesice"), {"rok": 2026, "mesic": 9})
        self.assertEqual(response.status_code, 200)

        (tyden,) = response.context["tydny"]
        self.assertEqual(tyden.cislo, 37)
        self.assertEqual((tyden.bilance.prescas, tyden.bilance.nedostatek), (45, 120))

        celkem = response.context["celkem"]
        self.assertEqual((celkem.prescas, celkem.nedostatek, celkem.bilance), (45, 120, -75))

        obsah = response.content.decode("utf-8")
        self.assertNotIn("-2h", obsah)
        self.assertNotIn("-1h", obsah)
        self.assertIn("Týden 37", obsah)
        self.assertIn("Bilance", obsah)

    def test_rozpracovany_den_nema_prescas_ani_nedostatek(self):
        response = self.client.get(reverse("timetracking:prehled_mesice"), {"rok": 2026, "mesic": 9})
        (tyden,) = response.context["tydny"]
        rozpracovany = next(s for s in tyden.souhrny if s.datum == date(2026, 9, 9))
        self.assertFalse(rozpracovany.je_zapocitan)
        self.assertEqual((rozpracovany.denni_prescas_minuty, rozpracovany.denni_nedostatek_minuty), (0, 0))


class DashboardOtevrenyBlokTests(TestCase):
    """Issue #34 — den jen s otevřeným blokem se na dashboardu neukazuje jako nedostatek."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.client = Client()
        self.client.force_login(self.employee.user)
        self.dnes = timezone.localdate()
        WorkdaySummary.objects.create(
            employee=self.employee, datum=self.dnes,
            hrube_minuty=0, odpracovane_minuty=0, prescos_minuty=-480,
        )

    def test_dnesni_karta_ukazuje_pomlcku_misto_zaporneho_nedostatku(self):
        response = self.client.get(reverse("timetracking:dashboard"))
        self.assertEqual(response.status_code, 200)
        obsah = response.content.decode("utf-8")
        self.assertNotIn("8h 0min", obsah)
        self.assertNotIn("text-danger", obsah)


class DashboardSvatekZvyrazneniTests(TestCase):
    """Issue #36 — svátek v tabulce posledních záznamů musí řádek zešednout (byl typo je_saint)."""

    def test_svatek_ma_tridu_table_secondary(self):
        employee = vytvor_zamestnance()
        client = Client()
        client.force_login(employee.user)
        WorkdaySummary.objects.create(
            employee=employee, datum=timezone.localdate() - timedelta(days=1),
            hrube_minuty=0, odpracovane_minuty=0, prescos_minuty=0,
            je_svatek=True, je_vikend=False,
        )
        response = client.get(reverse("timetracking:dashboard"))
        self.assertContains(response, 'class="table-secondary"')


class OdpracovanoFormatovaniTests(TestCase):
    """Odpracováno musí ukazovat hodiny a minuty ("Xh Ymin"), ne zbytky ladicího kódu
    jako "8h 470" (widthratio zaokrouhlené hodiny + syrové minuty vedle sebe)."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.client = Client()
        self.client.force_login(self.employee.user)
        self.dnes = timezone.localdate()
        WorkdaySummary.objects.create(
            employee=self.employee, datum=self.dnes,
            hrube_minuty=470, odpracovane_minuty=470, prescos_minuty=-10,
        )
        WorkdaySummary.objects.create(
            employee=self.employee, datum=self.dnes - timedelta(days=1),
            hrube_minuty=470, odpracovane_minuty=470, prescos_minuty=-10,
        )

    def test_dashboard_ukazuje_hodiny_a_minuty_ne_zbytky_ladiciho_kodu(self):
        response = self.client.get(reverse("timetracking:dashboard"))
        obsah = response.content.decode("utf-8")
        self.assertIn("7h 50min", obsah)
        self.assertNotIn("8h 470", obsah)
        self.assertNotIn("470</td>", obsah)

    def test_vykaz_ukazuje_hodiny_a_minuty(self):
        response = self.client.get(
            reverse("timetracking:prehled_mesice"),
            {"rok": self.dnes.year, "mesic": self.dnes.month},
        )
        obsah = response.content.decode("utf-8")
        self.assertIn("7h 50min", obsah)
        self.assertNotIn("8h 470", obsah)


class CasAkciDochazkyTests(TestCase):
    """Issue #39 — Příchod/Odchod/Start/Návrat z pohybu jdou zaznamenat na dřívější
    (dnešní) čas přes nepovinné pole 'cas', s výchozím chováním beze změny."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        self.client = Client()
        self.client.force_login(self.employee.user)

    @staticmethod
    def _cas_pred(minuty):
        """Vrátí (řetězec 'HH:MM' pro POST, očekávaný aware datetime). Očekávaný čas
        je oříznutý na celé minuty stejně jako to udělá server (strptime("%H:%M") dá
        time() bez vteřin) — srovnání pak jde na assertEqual, ne na assertAlmostEqual
        s rizikem flaky testu z oříznutí vteřin + latence mezi voláním a assertem."""
        cil = timezone.localtime(timezone.now() - timedelta(minutes=minuty))
        oriznuto = cil.replace(second=0, microsecond=0)
        return oriznuto.strftime("%H:%M"), oriznuto

    def test_clock_in_bez_cas_pouzije_ted(self):
        pred = timezone.now()
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        self.assertGreaterEqual(session.zacatek, pred)

    def test_skryte_pole_cas_nema_predvyplnenou_hodnotu(self):
        """Regrese: pole s časem nesmí mít server-side předvyplněnou hodnotu (např.
        {% now %}) — i skryté (d-none) pole se s formulářem vždy odešle, takže by
        obyčejné kliknutí na akci potichu poslalo čas z načtení stránky místo 'teď'.
        Hledá <input …> tagy s name="cas" bez ohledu na pořadí atributů, aby test
        nebyl závislý na přesném znění řádku v šabloně."""
        response = self.client.get(reverse("timetracking:dashboard"))
        obsah = response.content.decode("utf-8")
        cas_inputy = re.findall(r"<input\b[^>]*\bname=\"cas\"[^>]*>", obsah)
        self.assertTrue(cas_inputy, "V dashboardu chybí pole <input name=\"cas\">.")
        for tag in cas_inputy:
            self.assertNotIn("value=", tag)

    def test_clock_in_s_cas_pouzije_zvoleny_cas(self):
        cas_str, ocekavano = self._cas_pred(30)
        self.client.post(reverse("timetracking:clock_in"), {"cas": cas_str})
        session = WorkSession.objects.get(employee=self.employee)
        self.assertEqual(session.zacatek, ocekavano)

    def test_clock_in_s_neplatnym_casem_nic_nevytvori(self):
        response = self.client.post(
            reverse("timetracking:clock_in"), {"cas": "nesmysl"}, follow=True
        )
        self.assertFalse(WorkSession.objects.filter(employee=self.employee).exists())
        self.assertContains(response, "Neplatný čas.", status_code=200)

    def test_clock_in_s_budoucim_casem_je_odmitnut(self):
        cas_v_budoucnosti = timezone.localtime(
            timezone.now() + timedelta(minutes=30)
        ).strftime("%H:%M")
        response = self.client.post(
            reverse("timetracking:clock_in"), {"cas": cas_v_budoucnosti}, follow=True
        )
        self.assertFalse(WorkSession.objects.filter(employee=self.employee).exists())
        self.assertContains(response, "Čas nemůže být v budoucnosti.", status_code=200)

    def test_clock_in_s_prekryvajicim_casem_zahlasi_chybu_neni_500(self):
        WorkSession.objects.create(
            employee=self.employee,
            zacatek=timezone.now() - timedelta(hours=2),
            konec=timezone.now() - timedelta(minutes=10),
        )
        cas_str, _ = self._cas_pred(60)
        response = self.client.post(
            reverse("timetracking:clock_in"), {"cas": cas_str}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkSession.objects.filter(employee=self.employee).count(), 1)
        response = self.client.get(response.url)
        self.assertContains(response, "překrývá")

    def test_clock_out_s_casem_pred_zacatkem_zahlasi_chybu(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(minutes=10),
        )
        cas_str, _ = self._cas_pred(20)
        response = self.client.post(
            reverse("timetracking:clock_out"), {"cas": cas_str}
        )
        session.refresh_from_db()
        self.assertIsNone(session.konec)
        response = self.client.get(response.url)
        self.assertContains(response, "Konec musí být po začátku.")

    def test_clock_out_s_platnym_casem_ho_pouzije(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=1),
        )
        cas_str, ocekavano = self._cas_pred(10)
        self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertEqual(session.konec, ocekavano)

    def test_clock_out_s_casem_pred_koncem_uz_uzavreneho_pohybu_zahlasi_chybu(self):
        """Odchod nesmí zkrátit blok pod konec pohybu, který v něm už platně proběhl
        (jinak by WorkdaySummary.prepocitej() počítal nesmyslné/záporné odpracované minuty)."""
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=2),
        )
        Pohyb.objects.create(
            work_session=session, typ=self.typ,
            zacatek=timezone.now() - timedelta(minutes=40),
            konec=timezone.now() - timedelta(minutes=20),
        )
        cas_str, _ = self._cas_pred(30)  # 30 min zpátky, tj. před koncem pohybu (20 min zpátky)
        response = self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertIsNone(session.konec)
        response = self.client.get(response.url)
        self.assertContains(response, "Konec bloku nemůže být dřív, než skončil pohyb, který v něm proběhl.")

    def test_clock_out_bez_cas_funguje_i_pro_blok_ktery_nezacal_dnes(self):
        """Regrese: kontrola shodného dne se smí týkat jen výslovně zadaného času —
        obyčejné jednoklikové Odchod (bez 'Změnit čas') musí fungovat i pro session
        otevřenou před dneškem (typicky přes půlnoc), stejně jako dosud."""
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(days=2),
        )
        self.client.post(reverse("timetracking:clock_out"))
        session.refresh_from_db()
        self.assertIsNotNone(session.konec)

    def test_return_pohyb_bez_cas_funguje_i_pro_pohyb_ktery_nezacal_dnes(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(days=2),
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ, zacatek=timezone.now() - timedelta(days=2),
        )
        self.client.post(reverse("timetracking:return_pohyb"))
        pohyb.refresh_from_db()
        self.assertIsNotNone(pohyb.konec)

    def test_clock_out_s_casem_pro_blok_ktery_nezacal_dnes_zahlasi_chybu(self):
        """Pole nese jen čas, ne datum — pro blok otevřený před dneškem (např. zapomenutý
        odchod z minulého dne, viz close_open_sessions) by se jinak konec tiše datoval
        na dnešek, místo aby uživatele nasměroval na Opravit záznam."""
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(days=2),
        )
        cas_str, _ = self._cas_pred(30)
        response = self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertIsNone(session.konec)
        response = self.client.get(response.url)
        self.assertContains(response, "Opravit záznam")

    def test_return_pohyb_s_casem_pro_pohyb_ktery_nezacal_dnes_zahlasi_chybu(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(days=2),
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ, zacatek=timezone.now() - timedelta(days=2),
        )
        cas_str, _ = self._cas_pred(30)
        response = self.client.post(reverse("timetracking:return_pohyb"), {"cas": cas_str})
        pohyb.refresh_from_db()
        self.assertIsNone(pohyb.konec)
        response = self.client.get(response.url)
        self.assertContains(response, "Doplnit pohyb")

    def test_start_pohyb_s_platnym_casem_ho_pouzije(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=1),
        )
        cas_str, ocekavano = self._cas_pred(5)
        self.client.post(
            reverse("timetracking:start_pohyb"),
            {"typ_id": self.typ.pk, "cas": cas_str},
        )
        pohyb = Pohyb.objects.get(work_session=session)
        self.assertEqual(pohyb.zacatek, ocekavano)

    def test_start_pohyb_s_casem_pred_zacatkem_bloku_zahlasi_chybu_neni_500(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(minutes=5),
        )
        cas_str, _ = self._cas_pred(30)
        response = self.client.post(
            reverse("timetracking:start_pohyb"),
            {"typ_id": self.typ.pk, "cas": cas_str},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Pohyb.objects.filter(work_session=session).exists())
        response = self.client.get(response.url)
        self.assertContains(response, "nemůže začít před začátkem pracovního bloku")

    def test_return_pohyb_s_platnym_casem_ho_pouzije(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=1),
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ, zacatek=timezone.now() - timedelta(minutes=20),
        )
        cas_str, ocekavano = self._cas_pred(5)
        self.client.post(reverse("timetracking:return_pohyb"), {"cas": cas_str})
        pohyb.refresh_from_db()
        self.assertEqual(pohyb.konec, ocekavano)

    def test_return_pohyb_s_casem_pred_zacatkem_pohybu_zahlasi_chybu_neni_500(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=timezone.now() - timedelta(hours=1),
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ, zacatek=timezone.now() - timedelta(minutes=20),
        )
        cas_str, _ = self._cas_pred(30)
        response = self.client.post(
            reverse("timetracking:return_pohyb"), {"cas": cas_str}
        )
        self.assertEqual(response.status_code, 302)
        pohyb.refresh_from_db()
        self.assertIsNone(pohyb.konec)
        response = self.client.get(response.url)
        self.assertContains(response, "Konec pohybu musí být po jeho začátku.")


class StejnaMinutaJakoNavazujiciZaznamTests(TestCase):
    """Bug: rychlé akce (Odchod/Start pohybu/Návrat) zamítaly platný zápis, když
    uživatel přes 'Změnit čas' zadal stejnou minutu, ve které vznikl navazující
    záznam (ten má z timezone.now() plnou přesnost na mikrosekundy, kdežto pole
    'cas' nese jen HH:MM) — minutové oříznutí pak vypadalo jako čas těsně PŘED
    ním a WorkSession/Pohyb.clean() to zamítly jako neplatné pořadí."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        self.client = Client()
        self.client.force_login(self.employee.user)

    def test_odchod_se_stejnym_zadanym_casem_jako_prichod_projde(self):
        """Přísnější varianta: i Příchod byl zadán přes 'cas' (tedy má stejné
        minutové oříznutí jako Odchod) — časy jsou pak přesně stejné, ne jen
        ve stejné minutě, takže dorovnání musí zabrat i na '<=', ne jen '<'."""
        cas_str = timezone.localtime(timezone.now()).strftime("%H:%M")
        self.client.post(reverse("timetracking:clock_in"), {"cas": cas_str})
        session = WorkSession.objects.get(employee=self.employee)
        self.assertEqual(session.zacatek.second, 0)
        self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertIsNotNone(session.konec)
        self.assertGreater(session.konec, session.zacatek)

    def test_odchod_ve_stejne_minute_jako_prichod_projde(self):
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        cas_str = timezone.localtime(session.zacatek).strftime("%H:%M")
        self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertIsNotNone(session.konec)
        self.assertGreater(session.konec, session.zacatek)

    def test_odchod_5_minut_pred_prichodem_je_odmitnut(self):
        """Regrese naopak: dorovnání na stejnou minutu nesmí rozvolnit kontrolu
        pro čas, který je opravdu (o víc než minutu) dřív."""
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        drivejsi = (timezone.localtime(session.zacatek) - timedelta(minutes=5)).strftime("%H:%M")
        response = self.client.post(
            reverse("timetracking:clock_out"), {"cas": drivejsi}, follow=True
        )
        session.refresh_from_db()
        self.assertIsNone(session.konec)
        self.assertContains(response, "Konec musí být po začátku.")

    def test_start_pohybu_ve_stejne_minute_jako_prichod_projde(self):
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        cas_str = timezone.localtime(session.zacatek).strftime("%H:%M")
        self.client.post(
            reverse("timetracking:start_pohyb"), {"typ_id": self.typ.pk, "cas": cas_str}
        )
        self.assertTrue(
            Pohyb.objects.filter(work_session=session, konec__isnull=True).exists()
        )

    def test_navrat_ve_stejne_minute_jako_start_pohybu_projde(self):
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        self.client.post(
            reverse("timetracking:start_pohyb"),
            {"typ_id": self.typ.pk, "cas": timezone.localtime(session.zacatek).strftime("%H:%M")},
        )
        pohyb = Pohyb.objects.get(work_session=session)
        cas_str = timezone.localtime(pohyb.zacatek).strftime("%H:%M")
        self.client.post(reverse("timetracking:return_pohyb"), {"cas": cas_str})
        pohyb.refresh_from_db()
        self.assertIsNotNone(pohyb.konec)
        self.assertGreater(pohyb.konec, pohyb.zacatek)

    def test_odchod_ve_stejne_minute_jako_navrat_z_pohybu_projde(self):
        """Kryje i druhou (méně přímou) cestu ke stejné chybě — WorkSession.clean()
        porovnává Odchod i s koncem posledního pohybu v bloku, ne jen s příchodem."""
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        self.client.post(
            reverse("timetracking:start_pohyb"),
            {"typ_id": self.typ.pk, "cas": timezone.localtime(session.zacatek).strftime("%H:%M")},
        )
        pohyb = Pohyb.objects.get(work_session=session)
        self.client.post(
            reverse("timetracking:return_pohyb"),
            {"cas": timezone.localtime(pohyb.zacatek).strftime("%H:%M")},
        )
        pohyb.refresh_from_db()
        cas_str = timezone.localtime(pohyb.konec).strftime("%H:%M")
        self.client.post(reverse("timetracking:clock_out"), {"cas": cas_str})
        session.refresh_from_db()
        self.assertIsNotNone(session.konec)
        self.assertGreaterEqual(session.konec, pohyb.konec)

    def test_druhy_pohyb_ve_stejne_minute_jako_konec_prvniho_projde(self):
        """Kryje třetí cestu ke stejné chybě — Pohyb.clean() u druhého pohybu ve
        stejném bloku kontroluje překryv s koncem toho předchozího, ne jen se
        začátkem bloku."""
        self.client.post(reverse("timetracking:clock_in"))
        session = WorkSession.objects.get(employee=self.employee)
        self.client.post(
            reverse("timetracking:start_pohyb"),
            {"typ_id": self.typ.pk, "cas": timezone.localtime(session.zacatek).strftime("%H:%M")},
        )
        prvni_pohyb = Pohyb.objects.get(work_session=session)
        self.client.post(
            reverse("timetracking:return_pohyb"),
            {"cas": timezone.localtime(prvni_pohyb.zacatek).strftime("%H:%M")},
        )
        prvni_pohyb.refresh_from_db()
        cas_str = timezone.localtime(prvni_pohyb.konec).strftime("%H:%M")
        self.client.post(
            reverse("timetracking:start_pohyb"), {"typ_id": self.typ.pk, "cas": cas_str}
        )
        druhy_pohyb = Pohyb.objects.filter(
            work_session=session, konec__isnull=True
        ).exclude(pk=prvni_pohyb.pk).first()
        self.assertIsNotNone(druhy_pohyb)
        self.assertGreater(druhy_pohyb.zacatek, prvni_pohyb.konec)


class MistniCasOpravFormularuAStrTests(TestCase):
    """Issue #41 — WorkSessionOpravitForm/PohybRucneForm i WorkSession/Pohyb.__str__
    musí zobrazovat skutečný lokální (Europe/Prague) čas, ne uložený UTC bez
    konverze. Kryje zimní (CET, +1h) i letní (CEST, +2h) offset, aby oprava
    nebyla nahodile natvrdo napsaná jen pro jeden z nich."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ = TypPohybu.objects.create(
            nazev="Oběd", zkratka="OB", zapocitava_se_do_pracovni_doby=False,
        )
        # 12:00 UTC v lednu = 13:00 CET (+1h), v červnu = 14:00 CEST (+2h).
        self.zacatek_cet_utc = datetime(2026, 1, 15, 12, 0, tzinfo=dt_timezone.utc)
        self.konec_cet_utc = datetime(2026, 1, 15, 14, 30, tzinfo=dt_timezone.utc)
        self.zacatek_cest_utc = datetime(2026, 6, 15, 12, 0, tzinfo=dt_timezone.utc)
        self.konec_cest_utc = datetime(2026, 6, 15, 14, 30, tzinfo=dt_timezone.utc)

    def test_oprava_formular_predvyplni_mistni_cas_cet(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cet_utc, konec=self.konec_cet_utc,
        )
        form = WorkSessionOpravitForm(instance=session)
        self.assertEqual(form.initial["zacatek"], "2026-01-15T13:00")
        self.assertEqual(form.initial["konec"], "2026-01-15T15:30")

    def test_oprava_formular_predvyplni_mistni_cas_cest(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cest_utc, konec=self.konec_cest_utc,
        )
        form = WorkSessionOpravitForm(instance=session)
        self.assertEqual(form.initial["zacatek"], "2026-06-15T14:00")
        self.assertEqual(form.initial["konec"], "2026-06-15T16:30")

    def test_oprava_formular_beze_zmeny_neposune_ulozeny_cas(self):
        """Regrese: pokud uživatel formulář jen znovu odešle beze změny předvyplněných
        polí, uložený UTC čas se nesmí posunout o časový offset."""
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cet_utc, konec=self.konec_cet_utc,
        )
        form = WorkSessionOpravitForm(instance=session)
        data = {
            "zacatek": form.initial["zacatek"],
            "konec": form.initial["konec"],
            "poznamka": "",
        }
        znovu_odeslany = WorkSessionOpravitForm(data=data, instance=session)
        self.assertTrue(znovu_odeslany.is_valid(), znovu_odeslany.errors)
        ulozeny = znovu_odeslany.save()
        self.assertEqual(ulozeny.zacatek, self.zacatek_cet_utc)
        self.assertEqual(ulozeny.konec, self.konec_cet_utc)

    def test_pohyb_rucne_form_predvyplni_mistni_cas(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cest_utc,
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ,
            zacatek=self.zacatek_cest_utc, konec=self.konec_cest_utc,
        )
        form = PohybRucneForm(instance=pohyb, employee=self.employee)
        self.assertEqual(form.initial["zacatek"], "2026-06-15T14:00")
        self.assertEqual(form.initial["konec"], "2026-06-15T16:30")

    def test_worksession_str_pouziva_mistni_cas_cet(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cet_utc, konec=self.konec_cet_utc,
        )
        self.assertIn("15.01.2026 13:00 – 15:30", str(session))

    def test_pohyb_str_pouziva_mistni_cas_cest(self):
        session = WorkSession.objects.create(
            employee=self.employee, zacatek=self.zacatek_cest_utc,
        )
        pohyb = Pohyb.objects.create(
            work_session=session, typ=self.typ,
            zacatek=self.zacatek_cest_utc, konec=self.konec_cest_utc,
        )
        self.assertIn("15.06.2026 14:00 – 16:30", str(pohyb))


class ScheduleCloseOpenSessionsTests(TestCase):
    """Issue #49 — close_open_sessions je zaregistrovaný jako nightly Celery Beat
    úloha (migrace 0006) a jeho task obal skutečně volá management příkaz."""

    def test_periodictask_je_zaregistrovana_migraci(self):
        """Migrace 0006 se aplikuje i na testovací DB (Django migruje testovací
        DB od nuly), takže úloha tu musí existovat bez jakéhokoliv setUp."""
        ulohy = PeriodicTask.objects.filter(task="timetracking.tasks.close_open_sessions")
        self.assertEqual(ulohy.count(), 1)
        uloha = ulohy.get()
        self.assertTrue(uloha.enabled)
        self.assertEqual(uloha.crontab.hour, "2")
        self.assertEqual(uloha.crontab.minute, "0")
        self.assertEqual(uloha.crontab.timezone.key, "Europe/Prague")

    def test_task_oznaci_stary_otevreny_blok(self):
        employee = vytvor_zamestnance()
        stara_session = WorkSession.objects.create(
            employee=employee, zacatek=timezone.now() - timedelta(hours=20),
        )
        close_open_sessions_task()  # přímé volání, ne .delay() — bez brokeru
        stara_session.refresh_from_db()
        self.assertTrue(stara_session.poznamka.startswith("[AUTOMATICKY]"))
        self.assertFalse(stara_session.opraveno)

    def test_task_neoznaci_cerstvy_otevreny_blok(self):
        employee = vytvor_zamestnance()
        cerstva_session = WorkSession.objects.create(
            employee=employee, zacatek=timezone.now() - timedelta(hours=1),
        )
        close_open_sessions_task()
        cerstva_session.refresh_from_db()
        self.assertEqual(cerstva_session.poznamka, "")


class CloseOpenSessionsOznaceniTests(TestCase):
    """Issue #55 — close_open_sessions vypisuje místní (ne UTC) čas a stejný
    neopravený záznam neoznačuje znovu při každém dalším běhu."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        self.typ = TypPohybu.objects.create(nazev="Oběd", zkratka="OB")
        self.session = WorkSession.objects.create(
            employee=self.employee,
            zacatek=(timezone.now() - timedelta(hours=20)).replace(second=0, microsecond=0),
            poznamka="vlastní poznámka",
        )

    @staticmethod
    def _spust():
        out = StringIO()
        call_command("close_open_sessions", stdout=out)
        return out.getvalue()

    def test_druhy_beh_session_neoznaci_znovu(self):
        self._spust()
        self._spust()
        self.session.refresh_from_db()
        self.assertEqual(self.session.poznamka.count("[AUTOMATICKY]"), 1)
        self.assertTrue(self.session.poznamka.endswith("vlastní poznámka"))

    def test_druhy_beh_pohyb_neoznaci_znovu(self):
        pohyb = Pohyb.objects.create(
            work_session=self.session, typ=self.typ,
            zacatek=self.session.zacatek + timedelta(hours=1),
        )
        self._spust()
        self._spust()
        pohyb.refresh_from_db()
        self.assertEqual(pohyb.poznamka.count("[AUTOMATICKY]"), 1)

    def test_druhy_beh_vypise_drive_oznacenou_session_jako_cekajici(self):
        self._spust()
        vystup = self._spust()
        self.assertIn("stále čeká na opravu", vystup)
        self.assertIn("Žádné nové otevřené sessions k označení.", vystup)

    def test_vypis_pouziva_mistni_cas_ne_utc(self):
        vystup = self._spust()
        mistni = timezone.localtime(self.session.zacatek).strftime("%d.%m.%Y %H:%M")
        utc = self.session.zacatek.astimezone(dt_timezone.utc).strftime("%d.%m.%Y %H:%M")
        self.assertIn(mistni, vystup)
        self.assertNotIn(utc, vystup)


class OpravaZapomenutehoOdchoduTests(TestCase):
    """Issue #57 — otevřené bloky/pohyby z předchozích dnů jsou vidět a opravitelné
    z přehledu, výkazu a přehledu Odbor; opravovat smí vlastník, is_staff a vedoucí
    v rozsahu spravovani_zamestnanci()."""

    def setUp(self):
        self.employee = vytvor_zamestnance()
        oddeleni = self.employee.oddeleni
        self.kolega = self._zamestnanec_v(oddeleni, "kolega@example.com", "0002")
        self.vedouci = self._zamestnanec_v(oddeleni, "vedouci@example.com", "0003")
        self.vedouci.funkce = Funkce.objects.get(kod=Funkce.VEDOUCI_ODDELENI)
        self.vedouci.save()
        self.cizi_vedouci = vytvor_zamestnance("cizi@example.com", "0004")
        self.cizi_vedouci.funkce = Funkce.objects.get(kod=Funkce.VEDOUCI_ODDELENI)
        self.cizi_vedouci.save()

        self.vcera = timezone.localdate() - timedelta(days=1)
        self.typ = TypPohybu.objects.create(nazev="Oběd", zkratka="OB")
        self.stary = WorkSession.objects.create(
            employee=self.employee, zacatek=self._cas(self.vcera, 10, 0),
            poznamka=ZNACKA_SESSION + "moje poznámka",
        )

    def _zamestnanec_v(self, oddeleni, email, osobni_cislo):
        user = User.objects.create_user(username=email, email=email, password="x",
                                        first_name="T", last_name=osobni_cislo)
        return Employee.objects.create(user=user, osobni_cislo=osobni_cislo, oddeleni=oddeleni,
                                       typ_uvazku=self.employee.typ_uvazku,
                                       datum_nastupu=timezone.localdate())

    @staticmethod
    def _cas(datum, hodina, minuta):
        return timezone.make_aware(datetime.combine(datum, time(hodina, minuta)))

    def _klient(self, employee):
        c = Client()
        c.force_login(employee.user)
        return c

    def _url_opravy(self):
        return reverse("timetracking:opravit_session", args=[self.stary.pk])

    # --- výběr záznamů ---

    def test_k_oprave_jen_otevrene_z_predchozich_dnu(self):
        WorkSession.objects.create(employee=self.kolega, zacatek=timezone.now() - timedelta(hours=1))
        WorkSession.objects.create(
            employee=self.kolega, zacatek=self._cas(self.vcera, 8, 0), konec=self._cas(self.vcera, 9, 0),
        )
        pohyb = Pohyb.objects.create(work_session=self.stary, typ=self.typ, zacatek=self._cas(self.vcera, 11, 0))
        zaznamy = zaznamy_k_oprave([self.employee, self.kolega])
        self.assertEqual([z["url"] for z in zaznamy], [
            self._url_opravy(), reverse("timetracking:opravit_pohyb", args=[pohyb.pk]),
        ])
        self.assertTrue(zaznamy[0]["oznaceno"])

    # --- přehled ---

    def test_prehled_stary_blok_nabidne_opravu_a_skryje_odchod(self):
        obsah = self._klient(self.employee).get(reverse("timetracking:dashboard")).content.decode()
        self.assertIn("Zapomenutý odchod", obsah)
        self.assertIn(self._url_opravy(), obsah)
        self.assertIn(f"{self.vcera.day}. {self.vcera.month}. {self.vcera.year}", obsah)
        self.assertNotIn(reverse("timetracking:clock_out"), obsah)
        self.assertNotIn(reverse("timetracking:start_pohyb"), obsah)

    def test_prehled_stary_blok_s_otevrenym_pohybem_odkaze_na_opravu_pohybu(self):
        pohyb = Pohyb.objects.create(work_session=self.stary, typ=self.typ, zacatek=self._cas(self.vcera, 11, 0))
        obsah = self._klient(self.employee).get(reverse("timetracking:dashboard")).content.decode()
        self.assertIn(reverse("timetracking:opravit_pohyb", args=[pohyb.pk]), obsah)
        self.assertNotIn(reverse("timetracking:return_pohyb"), obsah)

    def test_prehled_dnesni_blok_beze_zmeny(self):
        WorkSession.objects.create(employee=self.kolega, zacatek=timezone.now() - timedelta(minutes=30))
        obsah = self._klient(self.kolega).get(reverse("timetracking:dashboard")).content.decode()
        self.assertIn(reverse("timetracking:clock_out"), obsah)
        self.assertNotIn("Zapomenutý odchod", obsah)

    # --- výkaz a Odbor ---

    def test_vykaz_zobrazi_sekci_jen_kdyz_je_co_opravit(self):
        obsah = self._klient(self.employee).get(reverse("timetracking:prehled_mesice")).content.decode()
        self.assertIn("Záznamy k opravě", obsah)
        self.assertIn(self._url_opravy(), obsah)
        obsah_kolegy = self._klient(self.kolega).get(reverse("timetracking:prehled_mesice")).content.decode()
        self.assertNotIn("Záznamy k opravě", obsah_kolegy)

    def test_odbor_ukaze_zaznamy_jen_v_rozsahu_spravy(self):
        url = reverse("reports:prehled_tymu")
        self.assertIn(self._url_opravy(), self._klient(self.vedouci).get(url).content.decode())
        self.assertNotIn(self._url_opravy(), self._klient(self.cizi_vedouci).get(url).content.decode())
        self.assertNotIn("Záznamy k opravě v týmu", self._klient(self.kolega).get(url).content.decode())

    # --- oprávnění ---

    def test_opravneni_k_oprave_bloku(self):
        self.assertEqual(self._klient(self.employee).get(self._url_opravy()).status_code, 200)
        self.assertEqual(self._klient(self.vedouci).get(self._url_opravy()).status_code, 200)
        self.assertEqual(self._klient(self.kolega).get(self._url_opravy()).status_code, 403)
        self.assertEqual(self._klient(self.cizi_vedouci).get(self._url_opravy()).status_code, 403)

    def test_opravneni_k_oprave_pohybu(self):
        pohyb = Pohyb.objects.create(work_session=self.stary, typ=self.typ, zacatek=self._cas(self.vcera, 11, 0))
        url = reverse("timetracking:opravit_pohyb", args=[pohyb.pk])
        self.assertEqual(self._klient(self.vedouci).get(url).status_code, 200)
        self.assertEqual(self._klient(self.kolega).get(url).status_code, 403)
        self.assertEqual(self._klient(self.cizi_vedouci).get(url).status_code, 403)

    # --- uložení opravy ---

    def _data_bloku(self, konec, next_url):
        return {
            "zacatek": f"{self.vcera:%Y-%m-%d}T10:00",
            "konec": f"{self.vcera:%Y-%m-%d}T{konec}",
            "poznamka": self.stary.poznamka,
            "next": next_url,
        }

    def test_vedouci_ulozi_opravu_a_vrati_se_na_next(self):
        odpoved = self._klient(self.vedouci).post(
            self._url_opravy(), self._data_bloku("15:45", reverse("reports:prehled_tymu")),
        )
        self.assertRedirects(odpoved, reverse("reports:prehled_tymu"), fetch_redirect_response=False)
        self.stary.refresh_from_db()
        self.assertEqual(self.stary.konec, self._cas(self.vcera, 15, 45))
        self.assertTrue(self.stary.opraveno)
        self.assertEqual(self.stary.poznamka, "moje poznámka")

    def test_next_mimo_web_se_ignoruje(self):
        odpoved = self._klient(self.employee).post(
            self._url_opravy(), self._data_bloku("15:45", "https://evil.example/"),
        )
        self.assertRedirects(odpoved, reverse("timetracking:dashboard"), fetch_redirect_response=False)

    def test_nejdriv_pohyb_pak_blok(self):
        pohyb = Pohyb.objects.create(
            work_session=self.stary, typ=self.typ, zacatek=self._cas(self.vcera, 11, 0),
            poznamka=ZNACKA_POHYB,
        )
        klient = self._klient(self.employee)
        klient.post(self._url_opravy(), self._data_bloku("15:45", ""))
        self.stary.refresh_from_db()
        self.assertIsNone(self.stary.konec)  # blok s otevřeným pohybem uzavřít nejde

        klient.post(reverse("timetracking:opravit_pohyb", args=[pohyb.pk]), {
            "zacatek": f"{self.vcera:%Y-%m-%d}T11:00", "konec": f"{self.vcera:%Y-%m-%d}T12:00",
            "poznamka": pohyb.poznamka,
        })
        pohyb.refresh_from_db()
        self.assertEqual(pohyb.konec, self._cas(self.vcera, 12, 0))
        self.assertEqual(pohyb.poznamka, "")

        klient.post(self._url_opravy(), self._data_bloku("15:45", ""))
        self.stary.refresh_from_db()
        self.assertEqual(self.stary.konec, self._cas(self.vcera, 15, 45))
