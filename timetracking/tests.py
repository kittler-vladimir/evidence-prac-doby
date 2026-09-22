from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Employee, Sekce, Odbor, Oddeleni, TypUvazku, CasovyBlokUvazku
from timetracking.bilance import format_minut, rozdel_na_tydny, secti
from timetracking.models import WorkSession, WorkdaySummary, TypPohybu, Pohyb


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
