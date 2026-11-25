from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee, Funkce, Oddeleni, Odbor, Sekce, TypUvazku
from leaves.models import TypStavu, ZadostOStav
from timetracking.models import Pohyb, TypPohybu, WorkSession, WorkdaySummary
from reports.detail import dny_zamestnance
from reports.services import NEPRITOMEN, PRITOMEN, stav_zamestnance

User = get_user_model()


class PrehledPritomnostiTestCase(TestCase):
    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        self.odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni_a = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddeleni A", kod="OA")
        self.oddeleni_b = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddeleni B", kod="OB")
        self.uvazek = TypUvazku.objects.create(
            nazev="Plny uvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )

        self.zam_a = self._vytvor_zamestnance("a@example.com", "Alena", "Adamova", self.oddeleni_a, "1")
        self.zam_b = self._vytvor_zamestnance("b@example.com", "Bedrich", "Bily", self.oddeleni_b, "2")

        self.zam_a.funkce = Funkce.objects.get(kod=Funkce.VEDOUCI_ODDELENI)
        self.zam_a.save()

        self.typ_dovolena = TypStavu.objects.create(
            nazev="Dovolena", zkratka="DOV", odecita_ze_zustatku=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA,
            barva="#FFC107",
        )
        self.typ_home_office = TypStavu.objects.create(
            nazev="Home office", zkratka="HO",
            odecita_ze_zustatku=False, je_pritomnost=True,
            vyzaduje_schvaleni=False, barva="#6610F2",
        )

    def _vytvor_zamestnance(self, email, first, last, oddeleni, cislo):
        user = User.objects.create_user(
            username=email, email=email, first_name=first, last_name=last,
        )
        return Employee.objects.create(
            user=user, osobni_cislo=cislo, oddeleni=oddeleni,
            typ_uvazku=self.uvazek, datum_nastupu=date(2020, 1, 1),
        )

    def _prihlas(self, employee, email):
        employee.user.set_password("test12345")
        employee.user.save()
        self.assertTrue(self.client.login(username=email, password="test12345"))

    def test_pritomnost_ma_prednost_pred_schvalenou_absenci(self):
        dnes = timezone.localdate()
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=self.typ_dovolena,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        WorkSession.objects.create(
            employee=self.zam_b,
            zacatek=timezone.now().replace(hour=8, minute=0, second=0, microsecond=0),
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, PRITOMEN)

    def test_bez_pritomnosti_a_bez_zadosti_je_nepritomen(self):
        stav = stav_zamestnance(self.zam_b, timezone.localdate())
        self.assertEqual(stav.kod, NEPRITOMEN)

    def test_schvalena_zadost_bez_pritomnosti_ukaze_typ_stavu(self):
        dnes = timezone.localdate()
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=self.typ_dovolena,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, self.typ_dovolena.zkratka)
        self.assertEqual(stav.popisek, self.typ_dovolena.nazev)
        self.assertEqual(stav.barva, self.typ_dovolena.barva)

    def test_home_office_ma_prednost_pred_pritomen(self):
        """Home office (je_pritomnost=True) se zobrazí i když existuje WorkSession."""
        dnes = timezone.localdate()
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=self.typ_home_office,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        WorkSession.objects.create(
            employee=self.zam_b,
            zacatek=timezone.now().replace(hour=8, minute=0, second=0, microsecond=0),
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, self.typ_home_office.zkratka)

    def test_home_office_se_zobrazi_i_bez_worksession(self):
        dnes = timezone.localdate()
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=self.typ_home_office,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, self.typ_home_office.zkratka)

    def test_novy_typ_zalozeny_jen_v_testu_funguje_bez_zasahu_do_kodu(self):
        """Nový TypStavu (bez odkazu na jakýkoli enum) se v přehledu zobrazí správně."""
        dnes = timezone.localdate()
        typ_sjezd = TypStavu.objects.create(
            nazev="Sjezd", zkratka="SJ",
            odecita_ze_zustatku=False, je_pritomnost=False,
            vyzaduje_schvaleni=False, barva="#123456",
        )
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=typ_sjezd,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, "SJ")
        self.assertEqual(stav.popisek, "Sjezd")
        self.assertEqual(stav.barva, "#123456")

    @staticmethod
    def _videni_zamestnanci(response):
        """Zploští non-staff `skupiny` ({'oddeleni', 'radky'}) na set ID zaměstnanců."""
        videni = set()
        for skupina in response.context["skupiny"]:
            for radek in skupina["radky"]:
                videni.add(radek["employee"].pk)
        return videni

    def test_radovy_zamestnanec_vidi_cely_svuj_odbor(self):
        self._prihlas(self.zam_b, "b@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._videni_zamestnanci(response), {self.zam_a.pk, self.zam_b.pk})

    def test_vedouci_oddeleni_vidi_cely_odbor_kdyz_je_priznak_zapnuty(self):
        """Zapnutý Odbor.zamestnanci_vidi_cely_odbor (výchozí) platí i pro vedoucí oddělení —
        v read-only přehledech nejsou omezeni jen na svou CRUD správu (vlastní oddělení)."""
        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._videni_zamestnanci(response), {self.zam_a.pk, self.zam_b.pk})

    def test_vedouci_oddeleni_vidi_jen_sve_oddeleni_kdyz_je_priznak_vypnuty(self):
        self.odbor.zamestnanci_vidi_cely_odbor = False
        self.odbor.save()
        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._videni_zamestnanci(response), {self.zam_a.pk})

    def test_legenda_ma_stejnou_barvu_jako_stav_zamestnance(self):
        dnes = timezone.localdate()
        ZadostOStav.objects.create(
            employee=self.zam_b, typ=self.typ_dovolena,
            datum_od=dnes, datum_do=dnes, stav=ZadostOStav.Stav.SCHVALENO,
        )
        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        legenda = {p["stav"].kod: p["stav"] for p in response.context["pocty"]}
        self.assertEqual(legenda[self.typ_dovolena.zkratka].barva, self.typ_dovolena.barva)
        # badge s barvou dovolené se vykreslí 2× — v legendě a u řádku zaměstnance
        self.assertContains(response, f"background-color: {self.typ_dovolena.barva};", count=2)

    def _nastav_kontakty(self):
        self.zam_a.telefon = "+420 123 456 789"
        self.zam_a.save()
        # zam_b zůstává bez telefonu

    def test_pritomnost_zobrazuje_email_a_telefon_jako_odkazy(self):
        """Issue #106 — plochý přehled (non-staff) ukazuje e-mail jako mailto: odkaz a telefon jako prostý
        text (bez tel: odkazu), prázdný telefon jako pomlčku."""
        self._nastav_kontakty()
        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>E-mail</th><th>Telefon</th>", count=2)  # 2 oddělení
        self.assertContains(response, '<a href="mailto:a@example.com">a@example.com</a>', html=True)
        self.assertContains(response, "<td>+420 123 456 789</td>", html=True)
        self.assertContains(response, '<a href="mailto:b@example.com">b@example.com</a>', html=True)
        self.assertContains(response, "<td>—</td>", count=1)
        self.assertNotContains(response, "tel:")

    def test_pritomnost_hierarchicke_zobrazeni_ma_stejne_sloupce(self):
        self._nastav_kontakty()
        admin = User.objects.create_user(
            username="admin@example.com", email="admin@example.com", password="test12345", is_staff=True,
        )
        Employee.objects.create(
            user=admin, osobni_cislo="9", oddeleni=self.oddeleni_a,
            typ_uvazku=self.uvazek, datum_nastupu=date(2020, 1, 1),
        )
        self.assertTrue(self.client.login(username="admin@example.com", password="test12345"))

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>E-mail</th><th>Telefon</th>", count=2)
        self.assertContains(response, "<td>+420 123 456 789</td>", html=True)
        self.assertContains(response, '<a href="mailto:b@example.com">b@example.com</a>', html=True)
        self.assertNotContains(response, "tel:")

    def test_prehled_tymu_sdili_stejny_rozsah_jako_pritomnost(self):
        """Issue #28 — Odbor (prehled_tymu) musí ukazovat stejný okruh lidí jako
        Přítomnost (viditelni_zamestnanci), ne jen CRUD-spravované podřízené."""
        self._prihlas(self.zam_b, "b@example.com")

        response = self.client.get(reverse("reports:prehled_tymu"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._videni_zamestnanci(response), {self.zam_a.pk, self.zam_b.pk})

    def test_vyhledani_najde_zamestnance_mimo_vlastni_odbor(self):
        jina_sekce = Sekce.objects.create(nazev="Jina sekce", kod="S2")
        jiny_odbor = Odbor.objects.create(sekce=jina_sekce, nazev="Jiny odbor", kod="O2")
        jine_oddeleni = Oddeleni.objects.create(odbor=jiny_odbor, nazev="Jine oddeleni", kod="OC")
        zam_c = self._vytvor_zamestnance("c@example.com", "Cyril", "Cerny", jine_oddeleni, "3")

        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:vyhledat_zamestnance"), {"q": "Cerny"})
        self.assertEqual(response.status_code, 200)
        vysledky = {v["employee"].pk for v in response.context["vysledky"]}
        self.assertEqual(vysledky, {zam_c.pk})

    def test_prazdny_dotaz_nevraci_zadne_vysledky(self):
        self._prihlas(self.zam_a, "a@example.com")
        response = self.client.get(reverse("reports:vyhledat_zamestnance"))
        self.assertEqual(response.context["vysledky"], [])


class PrehledTymuAExportBilanceTestCase(TestCase):
    """Issue #34 — Odbor a XLSX export ukazují přesčas/nedostatek zvlášť, bez záporných hodin."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S3")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O3")
        oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddeleni", kod="OD3")
        uvazek = TypUvazku.objects.create(
            nazev="Plny uvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        user = User.objects.create_user(
            username="d@example.com", email="d@example.com",
            first_name="Dana", last_name="Dvorakova", password="test12345",
        )
        self.zam = Employee.objects.create(
            user=user, osobni_cislo="4", oddeleni=oddeleni,
            typ_uvazku=uvazek, datum_nastupu=date(2020, 1, 1),
        )
        # Po 7.9. (+45), Út 8.9. (-90), rozpracovaný den 9.9. (bez uzavřeného bloku)
        WorkdaySummary.objects.create(
            employee=self.zam, datum=date(2026, 9, 7),
            hrube_minuty=525, odpracovane_minuty=525, prescos_minuty=45,
        )
        WorkdaySummary.objects.create(
            employee=self.zam, datum=date(2026, 9, 8),
            hrube_minuty=390, odpracovane_minuty=390, prescos_minuty=-90,
        )
        WorkdaySummary.objects.create(
            employee=self.zam, datum=date(2026, 9, 9),
            hrube_minuty=0, odpracovane_minuty=0, prescos_minuty=-480,
        )
        self.client = Client()
        user.set_password("test12345")
        user.save()
        self.assertTrue(self.client.login(username="d@example.com", password="test12345"))

    def test_odbor_ukazuje_prescas_a_nedostatek_zvlast_bez_zapornych_hodin(self):
        response = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 9})
        self.assertEqual(response.status_code, 200)
        obsah = response.content.decode("utf-8")
        self.assertNotIn("-2h", obsah)
        self.assertNotIn("-1h", obsah)
        self.assertIn("Nedostatek", obsah)

        (skupina,) = response.context["skupiny"]
        (radek,) = skupina["radky"]
        self.assertEqual((radek["prescas_minuty"], radek["nedostatek_minuty"]), (45, 90))

    def test_odbor_ukazuje_bilanci_se_znamenkem(self):
        # Issue #63 — sloupec Bilance vedle Přesčas/Nedostatek, se skutečným
        # znaménkem "−" (stejný formát jako Výkaz a XLSX export), ne syrové
        # záporné číslo z issue #34.
        response = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 9})

        (skupina,) = response.context["skupiny"]
        (radek,) = skupina["radky"]
        self.assertEqual(radek["bilance_minuty"], 45 - 90)

        obsah = response.content.decode("utf-8")
        self.assertIn("Bilance", obsah)
        self.assertIn("−0h 45min", obsah)
        self.assertNotIn("-0h 45min", obsah)
        self.assertNotIn("-45min", obsah)

    def test_export_xlsx_ma_tydenni_a_mesicni_souhrn_bez_zapornych_hodin(self):
        import openpyxl
        from io import BytesIO

        response = self.client.get(reverse("reports:export_xlsx"), {"rok": 2026, "mesic": 9})
        self.assertEqual(response.status_code, 200)

        wb = openpyxl.load_workbook(BytesIO(response.content))
        ws = wb.active
        hlavicka = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(
            hlavicka,
            ["Datum", "Den", "Odpracováno", "Přesčas", "Nedostatek", "Svátek/Víkend", "Bilance", "Nepřítomnost"],
        )

        popisky = [row[0].value for row in ws.iter_rows(min_row=2) if row[0].value]
        tydenni_radky = [p for p in popisky if p and p.startswith("Týden")]
        self.assertEqual(len(tydenni_radky), 1)
        self.assertIn("Celkem za měsíc", popisky)

        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str):
                    self.assertNotIn("-2h", cell.value)

        radek_mesic = next(r for r in ws.iter_rows(min_row=2) if r[0].value == "Celkem za měsíc")
        self.assertEqual(radek_mesic[3].value, "0h 45min")   # Přesčas
        self.assertEqual(radek_mesic[4].value, "1h 30min")   # Nedostatek
        self.assertEqual(radek_mesic[6].value, "−0h 45min")  # Bilance


class VyberMesiceOdborAExportTestCase(TestCase):
    """Issue #87 — Odbor zachová filtr při změně měsíce, export snese neplatné parametry."""

    def setUp(self):
        from unittest import mock

        self.sekce = Sekce.objects.create(nazev="Sekce", kod="S9")
        odbor = Odbor.objects.create(sekce=self.sekce, nazev="Odbor", kod="O9")
        oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddeleni", kod="OD9")
        uvazek = TypUvazku.objects.create(
            nazev="Plny uvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        user = User.objects.create_user(
            username="admin9@example.com", email="admin9@example.com",
            first_name="Adam", last_name="Admin", is_staff=True,
        )
        self.zam = Employee.objects.create(
            user=user, osobni_cislo="9", oddeleni=oddeleni,
            typ_uvazku=uvazek, datum_nastupu=date(2020, 1, 1),
        )
        WorkdaySummary.objects.create(
            employee=self.zam, datum=date(2026, 9, 7),
            hrube_minuty=525, odpracovane_minuty=525, prescos_minuty=45,
        )
        self.client.force_login(user)
        patcher = mock.patch(
            "timetracking.obdobi.timezone.localdate", return_value=date(2026, 10, 7),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_odbor_zachova_filtr_v_odkazech_na_jiny_mesic(self):
        odpoved = self.client.get(
            reverse("reports:prehled_tymu"), {"sekce": self.sekce.pk, "rok": 2026, "mesic": 10},
        )
        self.assertEqual(odpoved.status_code, 200)
        self.assertContains(odpoved, f"?sekce={self.sekce.pk}&amp;rok=2026&amp;mesic=9")
        # formulář výběru měsíce nese filtr jako skrytý parametr
        self.assertContains(odpoved, f'<input type="hidden" name="sekce" value="{self.sekce.pk}">')
        self.assertContains(odpoved, "Přehled odboru – Říjen 2026")

    def test_odbor_ukaze_zvoleny_mesic_a_neplatny_nespadne(self):
        odpoved = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 9})
        self.assertContains(odpoved, "Přehled odboru – Září 2026")
        odpoved = self.client.get(reverse("reports:prehled_tymu"), {"rok": "x", "mesic": 99})
        self.assertEqual(odpoved.status_code, 200)
        self.assertContains(odpoved, "Přehled odboru – Říjen 2026")

    def test_export_pouzije_zvoleny_mesic_a_toleruje_neplatne_parametry(self):
        import openpyxl
        from io import BytesIO

        odpoved = self.client.get(reverse("reports:export_xlsx"), {"rok": 2026, "mesic": 9})
        self.assertEqual(odpoved.status_code, 200)
        self.assertEqual(openpyxl.load_workbook(BytesIO(odpoved.content)).active.title, "Výkaz 09-2026")

        odpoved = self.client.get(reverse("reports:export_xlsx"), {"rok": "abc", "mesic": "13"})
        self.assertEqual(odpoved.status_code, 200)
        self.assertEqual(openpyxl.load_workbook(BytesIO(odpoved.content)).active.title, "Výkaz 10-2026")


class NepritomnostiOdborAExportTestCase(TestCase):
    """Issue #117 — Odbor má sloupce nepřítomností podle typu, XLSX sloupec a souhrn."""

    def setUp(self):
        from timetracking.tests import vytvor_nepritomnosti_rijna_2026, vytvor_zamestnance

        self.zam = vytvor_zamestnance("n117@example.com", "0117")
        self.typy = vytvor_nepritomnosti_rijna_2026(self.zam)
        self.client = Client()
        self.client.force_login(self.zam.user)

    def test_odbor_ma_sloupce_jen_pro_pouzite_typy_a_hodnoty_po_zamestnanci(self):
        response = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10})
        self.assertEqual(response.status_code, 200)

        # Použité typy: dovolená, nemoc, home office (přítomnost až nakonec); nepoužité typy ne.
        self.assertEqual(
            [t.zkratka for t in response.context["sloupce_nepritomnosti"]], ["DOV", "NEM", "HOT"],
        )
        (skupina,) = response.context["skupiny"]
        (radek,) = skupina["radky"]
        bunky = [(b.dny, b.minuty) for b in radek["bunky_nepritomnosti"]]
        self.assertEqual(bunky, [(2, 1110), (1, 480), (1, 480)])

        obsah = response.content.decode("utf-8")
        self.assertIn("18h 30min", obsah)
        self.assertIn("HOT (přítomnost)", obsah)
        self.assertNotIn("OČR", obsah)

    def test_odbor_bez_nepritomnosti_nema_sloupce_navic(self):
        ZadostOStav.objects.all().delete()
        response = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sloupce_nepritomnosti"], [])
        self.assertNotContains(response, "Dnů")

    def test_export_xlsx_ma_sloupec_nepritomnost_a_souhrn(self):
        import openpyxl
        from io import BytesIO

        response = self.client.get(reverse("reports:export_xlsx"), {"rok": 2026, "mesic": 10})
        self.assertEqual(response.status_code, 200)
        ws = openpyxl.load_workbook(BytesIO(response.content)).active

        hlavicka = [c.value for c in ws[1]]
        # Dosavadních 7 sloupců beze změny, Nepřítomnost je za nimi.
        self.assertEqual(
            hlavicka,
            ["Datum", "Den", "Odpracováno", "Přesčas", "Nedostatek", "Svátek/Víkend", "Bilance", "Nepřítomnost"],
        )
        podle_data = {r[0].value: r[7].value for r in ws.iter_rows(min_row=2) if r[0].value}
        self.assertEqual(podle_data["12.10.2026"], "DOV 8h 0min")
        self.assertEqual(podle_data["14.10.2026"], "HOT 8h 0min (přítomnost)")
        self.assertEqual(podle_data["15.10.2026"], "NEM 8h 0min")
        self.assertEqual(podle_data["16.10.2026"], "DOV 2h 30min")
        self.assertIsNone(podle_data["19.10.2026"])  # čekající žádost

        radky = {r[0].value: (r[1].value, r[2].value) for r in ws.iter_rows(min_row=2) if r[0].value}
        self.assertEqual(radky["DOV – Dovolená"], (2, "18h 30min"))
        self.assertEqual(radky["NEM – Nemoc"], (1, "8h 0min"))
        self.assertEqual(radky["OČR – Ošetřování člena rodiny"], ("—", "—"))
        self.assertEqual(radky["HOT – Home office test"], (1, "8h 0min"))
        popisky = [r[0].value for r in ws.iter_rows(min_row=2) if r[0].value]
        self.assertLess(popisky.index("Celkem za měsíc"), popisky.index("Nepřítomnosti za měsíc"))
        self.assertLess(popisky.index("Nepřítomnosti za měsíc"), popisky.index("Přítomnost mimo pracoviště"))

        # Bilance se nezměnila: jediný souhrn je 16. 10. (−30 min).
        celkem = next(r for r in ws.iter_rows(min_row=2) if r[0].value == "Celkem za měsíc")
        self.assertEqual((celkem[3].value, celkem[4].value, celkem[6].value),
                         ("0h 0min", "0h 30min", "−0h 30min"))

    def _xlsx_listu(self):
        import openpyxl
        from io import BytesIO

        response = self.client.get(reverse("reports:export_xlsx"), {"rok": 2026, "mesic": 10})
        return openpyxl.load_workbook(BytesIO(response.content)).active

    def test_export_ma_tydenni_radek_i_pro_tyden_jen_s_nepritomnosti(self):
        # Stejné týdny jako ve Výkazu: týden 42 má řádky jen díky dovolené/nemoci, bez docházky.
        # Bez souhrnů by `zvolene_obdobi` bral za nejstarší měsíc ten dnešní, proto datum pevně.
        from unittest import mock

        patcher = mock.patch(
            "timetracking.obdobi.timezone.localdate", return_value=date(2026, 10, 27),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        WorkdaySummary.objects.all().delete()
        popisky = [r[0].value for r in self._xlsx_listu().iter_rows(min_row=2) if r[0].value]
        self.assertTrue(any(p.startswith("Týden 42") for p in popisky))

    def test_typ_jen_s_hodinovou_zadosti_ma_ve_dnech_pomlcku(self):
        ZadostOStav.objects.filter(typ=self.typy["dovolena"], cas_od__isnull=True).delete()
        response = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10})
        (skupina,) = response.context["skupiny"]
        (radek,) = skupina["radky"]
        dov = radek["bunky_nepritomnosti"][0]
        self.assertEqual((dov.typ.zkratka, dov.dny, dov.minuty), ("DOV", 0, 150))
        self.assertNotContains(response, "<td>0</td>", html=True)

        radky = {r[0].value: (r[1].value, r[2].value) for r in self._xlsx_listu().iter_rows(min_row=2) if r[0].value}
        self.assertEqual(radky["DOV – Dovolená"], ("—", "2h 30min"))


def _cas(rok, mesic, den, hodina, minuta=0):
    return timezone.make_aware(datetime(rok, mesic, den, hodina, minuta))


class DetailZamestnanceOdboruTestCase(TestCase):
    """Issue #123 — admin detail zaměstnance z přehledu Odbor."""

    def setUp(self):
        from timetracking.tests import vytvor_nepritomnosti_rijna_2026, vytvor_zamestnance

        self.zam = vytvor_zamestnance("d123@example.com", "0123")
        self.typy = vytvor_nepritomnosti_rijna_2026(self.zam)
        self.lekar = TypPohybu.objects.create(
            nazev="Lékař", zkratka="LEK", zapocitani_pruzna=TypPohybu.Zapocitani.JADRO,
        )
        # Po 5. 10.: Odchod + Příchod u lékaře místo pohybu (mezera 9:42–13:15)
        WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 5, 7, 18), konec=_cas(2026, 10, 5, 9, 42),
        )
        WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 5, 13, 15), konec=_cas(2026, 10, 5, 16, 28),
        )
        # Út 6. 10.: celý den s pohybem Lékař 10:00–11:00
        blok = WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 6, 7, 33), konec=_cas(2026, 10, 6, 16, 53),
        )
        Pohyb.objects.create(
            work_session=blok, typ=self.lekar,
            zacatek=_cas(2026, 10, 6, 10), konec=_cas(2026, 10, 6, 11),
        )
        self.admin = User.objects.create_user(
            username="admin123@example.com", email="admin123@example.com",
            password="test12345", is_staff=True,
        )
        self.client.force_login(self.admin)
        self.url = reverse("reports:detail_zamestnance", args=[self.zam.pk])

    def _den(self, odpoved, den):
        (nalezeny,) = [d for d in odpoved.context["dny"] if d.datum == den]
        return nalezeny

    def test_detail_ukazuje_bloky_mezeru_pohyb_stavy_a_souhrn(self):
        odpoved = self.client.get(self.url, {"rok": 2026, "mesic": 10})
        self.assertEqual(odpoved.status_code, 200)

        pondeli = self._den(odpoved, date(2026, 10, 5))
        self.assertEqual(len(pondeli.bloky), 2)
        self.assertIsNone(pondeli.bloky[0].mezera_pred)
        mezera = pondeli.bloky[1].mezera_pred
        self.assertEqual(
            (timezone.localtime(mezera.od).strftime("%H:%M"),
             timezone.localtime(mezera.do).strftime("%H:%M"), mezera.minuty),
            ("09:42", "13:15", 213),
        )
        self.assertContains(odpoved, "mezera 09:42–13:15 (3h 33min)")
        self.assertEqual(pondeli.souhrn, WorkdaySummary.objects.get(employee=self.zam, datum=date(2026, 10, 5)))

        utery = self._den(odpoved, date(2026, 10, 6))
        (pohyb,) = utery.pohyby
        self.assertEqual(pohyb.pohyb.typ, self.lekar)
        self.assertEqual(pohyb.zapocitani, TypPohybu.Zapocitani.JADRO)
        self.assertContains(odpoved, "Jen v jádrové době")
        self.assertContains(odpoved, "Lékař")

        # stavy z nepritomnosti_za_mesic: dovolená Po–Út 12.–13. 10.
        (dovolena,) = self._den(odpoved, date(2026, 10, 12)).nepritomnosti
        self.assertEqual(dovolena.typ, self.typy["dovolena"])

    def test_mesicni_soucet_se_shoduje_s_radkem_v_odboru(self):
        detail = self.client.get(self.url, {"rok": 2026, "mesic": 10})
        odbor = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10})
        radky = [
            r
            for s in odbor.context["skupiny"] for o in s["odbory"]
            for og in o["oddeleni_skupiny"] for r in og["radky"]
            if r["employee"] == self.zam
        ]
        (radek,) = radky
        self.assertEqual(detail.context["celkem"].prescas, radek["prescas_minuty"])
        self.assertEqual(detail.context["celkem"].nedostatek, radek["nedostatek_minuty"])
        self.assertEqual(detail.context["celkem"].bilance, radek["bilance_minuty"])
        self.assertEqual(
            detail.context["celkem_odpr"], radek["odpracovano_h"] * 60 + radek["odpracovano_m"],
        )
        self.assertGreater(detail.context["celkem_odpr"], 0)

    def test_odkaz_v_odboru_je_jen_pro_staff_a_nese_obdobi_a_filtr(self):
        sekce_pk = self.zam.oddeleni.odbor.sekce.pk
        odbor = self.client.get(
            reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10, "sekce": sekce_pk},
        )
        self.assertContains(odbor, f'href="{self.url}?sekce={sekce_pk}&amp;rok=2026&amp;mesic=10"')

        self.client.force_login(self.zam.user)
        odbor = self.client.get(reverse("reports:prehled_tymu"), {"rok": 2026, "mesic": 10})
        self.assertEqual(odbor.status_code, 200)
        self.assertContains(odbor, self.zam.jmeno)
        self.assertNotContains(odbor, self.url)

    def test_ne_staff_dostane_403_i_na_vlastni_detail(self):
        self.client.force_login(self.zam.user)
        self.assertEqual(self.client.get(self.url, {"rok": 2026, "mesic": 10}).status_code, 403)

    def test_anonym_je_presmerovan_na_prihlaseni(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_neexistujici_zamestnanec_je_404(self):
        odpoved = self.client.get(reverse("reports:detail_zamestnance", args=[999999]))
        self.assertEqual(odpoved.status_code, 404)

    def test_neplatne_obdobi_spadne_na_aktualni_mesic(self):
        odpoved = self.client.get(self.url, {"rok": "x", "mesic": 99})
        self.assertEqual(odpoved.status_code, 200)
        dnes = timezone.localdate()
        self.assertEqual((odpoved.context["obdobi"].rok, odpoved.context["obdobi"].mesic), (dnes.year, dnes.month))

    def test_zpet_na_odbor_zachova_mesic_a_filtr(self):
        odpoved = self.client.get(self.url, {"rok": 2026, "mesic": 10, "odbor": 7})
        self.assertEqual(
            odpoved.context["url_odboru"], reverse("reports:prehled_tymu") + "?odbor=7&rok=2026&mesic=10",
        )
        self.assertContains(odpoved, '<input type="hidden" name="odbor" value="7">')

    def test_mesic_bez_zaznamu_ukaze_prazdny_stav(self):
        from timetracking.tests import vytvor_zamestnance

        prazdny = vytvor_zamestnance("prazdny123@example.com", "0124")
        odpoved = self.client.get(
            reverse("reports:detail_zamestnance", args=[prazdny.pk]), {"rok": 2026, "mesic": 10},
        )
        self.assertEqual(odpoved.status_code, 200)
        self.assertEqual(odpoved.context["dny"], [])
        self.assertContains(odpoved, "V tomto měsíci nejsou žádné záznamy.")

    def test_otevreny_blok_z_minulosti_je_k_oprave(self):
        WorkSession.objects.create(employee=self.zam, zacatek=_cas(2026, 10, 7, 8))
        odpoved = self.client.get(self.url, {"rok": 2026, "mesic": 10})
        (blok,) = self._den(odpoved, date(2026, 10, 7)).bloky
        self.assertTrue(blok.k_oprave)
        self.assertFalse(blok.probiha)
        self.assertContains(odpoved, "bez odchodu")

    def test_mezera_jedne_minuty_neni_mezera(self):
        """Stejné pravidlo jako WorkdaySummary.prepocitej(): konec 11:17, začátek 11:18 je jeden blok."""
        WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 8, 8), konec=_cas(2026, 10, 8, 11, 17),
        )
        WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 8, 11, 18), konec=_cas(2026, 10, 8, 12),
        )
        WorkSession.objects.create(
            employee=self.zam, zacatek=_cas(2026, 10, 8, 12, 2), konec=_cas(2026, 10, 8, 16),
        )
        (den,) = [d for d in dny_zamestnance(self.zam, 2026, 10) if d.datum == date(2026, 10, 8)]
        self.assertEqual([b.mezera_pred for b in den.bloky][:2], [None, None])
        self.assertEqual(den.bloky[2].mezera_pred.minuty, 2)

    def test_pocet_dotazu_nezavisi_na_poctu_dni(self):
        def dotazy():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.url, {"rok": 2026, "mesic": 10})
            return len(ctx)

        pred = dotazy()
        for den in range(19, 24):
            blok = WorkSession.objects.create(
                employee=self.zam, zacatek=_cas(2026, 10, den, 8), konec=_cas(2026, 10, den, 16),
            )
            Pohyb.objects.create(
                work_session=blok, typ=self.lekar,
                zacatek=_cas(2026, 10, den, 10), konec=_cas(2026, 10, den, 11),
            )
        self.assertEqual(dotazy(), pred)
