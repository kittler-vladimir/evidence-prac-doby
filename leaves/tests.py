from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.holidays_model import StatniSvatek, Zeme
from accounts.models import CasovyBlokUvazku, Employee, Oddeleni, Odbor, Sekce, TypUvazku
from leaves.forms import ZadostOStavForm
from leaves.models import (
    NarokDovolene,
    NarokIndispozicnihoVolna,
    TypStavu,
    ZadostOStav,
    ZustatekStavu,
)

from timetracking.models import WorkdaySummary, WorkSession

User = get_user_model()


class IndispozicniVolnoTestCase(TestCase):
    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        self.plny_uvazek = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        self.poloviny_uvazek = TypUvazku.objects.create(
            nazev="Poloviční úvazek", hodiny_denne=Decimal("4.00"), hodiny_tyydne=Decimal("20.00")
        )

        user = User.objects.create_user(
            username="jan@example.com", email="jan@example.com",
            first_name="Jan", last_name="Novák",
        )
        self.employee = Employee.objects.create(
            user=user, osobni_cislo="1", oddeleni=self.oddeleni,
            typ_uvazku=self.plny_uvazek, datum_nastupu=date(2020, 1, 1),
        )

        user2 = User.objects.create_user(
            username="eva@example.com", email="eva@example.com",
            first_name="Eva", last_name="Malá",
        )
        self.part_time_employee = Employee.objects.create(
            user=user2, osobni_cislo="2", oddeleni=self.oddeleni,
            typ_uvazku=self.poloviny_uvazek, datum_nastupu=date(2020, 1, 1),
        )

        self.typ_iv = TypStavu.objects.create(
            nazev="Indispoziční volno", zkratka="IV",
            odecita_ze_zustatku=True, je_indispozicni_volno=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        NarokIndispozicnihoVolna.objects.create(hodin=Decimal("40.00"), platne_od=date(2026, 1, 1))

    def _zadost(self, employee, datum_od, datum_do):
        zadost = ZadostOStav(
            employee=employee, typ=self.typ_iv, datum_od=datum_od, datum_do=datum_do,
        )
        zadost.save()
        return zadost

    def test_schvaleni_zalozi_zustatek_s_globalnim_narokem(self):
        """GIVEN aktivní nárok 40h WHEN je schválena jednodenní žádost THEN vznikne zůstatek 40h/8h čerpáno."""
        zadost = self._zadost(self.employee, date(2026, 7, 6), date(2026, 7, 6))
        zadost.schval(self.employee)

        zustatek = ZustatekStavu.objects.get(
            employee=self.employee, rok=2026, typ=self.typ_iv
        )
        self.assertEqual(zustatek.narok_hodin, Decimal("40.00"))
        self.assertEqual(zustatek.cerpano_hodin, Decimal("8.00"))
        self.assertEqual(zustatek.zbyvajici_hodin, Decimal("32.00"))

    def test_zadost_presahujici_zustatek_je_odmitnuta_validaci(self):
        # 40h nároku, ale žádost o 6 pracovních dní (48h) přesahuje limit
        form = ZadostOStavForm(
            data={
                "typ": self.typ_iv.pk,
                "datum_od": "2026-07-06",
                "datum_do": "2026-07-13",
                "poznamka_zamestnance": "",
            },
            employee=self.employee,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Nedostatečný zůstatek", str(form.errors))

    def test_zmena_naroku_neovlivni_jiz_vytvoreny_zustatek(self):
        zadost = self._zadost(self.employee, date(2026, 7, 6), date(2026, 7, 6))
        zadost.schval(self.employee)

        # Admin uprostřed roku zvýší globální nárok na 48h
        NarokIndispozicnihoVolna.objects.create(hodin=Decimal("48.00"), platne_od=date(2026, 8, 1))

        zustatek = ZustatekStavu.objects.get(
            employee=self.employee, rok=2026, typ=self.typ_iv
        )
        self.assertEqual(zustatek.narok_hodin, Decimal("40.00"))

    def test_flat_narok_bez_ohledu_na_uvazek(self):
        """Zaměstnanec s polovičním úvazkem má stejný roční nárok 40h jako na plný úvazek."""
        zadost = self._zadost(self.part_time_employee, date(2026, 7, 6), date(2026, 7, 6))
        zadost.schval(self.part_time_employee)

        zustatek = ZustatekStavu.objects.get(
            employee=self.part_time_employee, rok=2026, typ=self.typ_iv
        )
        self.assertEqual(zustatek.narok_hodin, Decimal("40.00"))
        # Jeden den u poloviního úvazku stojí jen 4h, ne 8h
        self.assertEqual(zustatek.cerpano_hodin, Decimal("4.00"))

    def test_schvaleni_bez_nastaveneho_naroku_je_odmitnuto(self):
        """Bez jakéhokoli aktivního NarokIndispozicnihoVolna se žádost neschválí a nevznikne 0h zůstatek."""
        NarokIndispozicnihoVolna.objects.all().delete()
        zadost = self._zadost(self.employee, date(2026, 7, 6), date(2026, 7, 6))

        with self.assertRaises(ValidationError):
            zadost.schval(self.employee)

        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)
        self.assertFalse(
            ZustatekStavu.objects.filter(
                employee=self.employee, rok=2026, typ=self.typ_iv
            ).exists()
        )

    def test_moje_zadosti_zobrazi_virtualni_zustatek_bez_zadosti(self):
        """Zaměstnanec vidí nárok na IV, i když zatím nepodal žádnou žádost."""
        self.employee.user.set_password("test12345")
        self.employee.user.save()
        self.assertTrue(
            self.client.login(username="jan@example.com", password="test12345")
        )

        response = self.client.get(reverse("leaves:moje_zadosti"))
        self.assertEqual(response.status_code, 200)

        zustatky = response.context["zustatky"]
        iv_zustatek = next(z for z in zustatky if z.typ_id == self.typ_iv.pk)
        self.assertEqual(iv_zustatek.narok_hodin, Decimal("40.00"))
        self.assertIsNone(iv_zustatek.pk)

    def test_kategorie_pro_prehled_musi_odpovidat_je_indispozicni_volno(self):
        """Typ s je_indispozicni_volno=True musí mít kategorii INDISPOZICNI_VOLNO a naopak."""
        nesouhlasny = TypStavu(
            nazev="Nesouhlasny typ", zkratka="NS",
            je_indispozicni_volno=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.JINA,
        )
        with self.assertRaises(ValidationError):
            nesouhlasny.full_clean()

        opacne_nesouhlasny = TypStavu(
            nazev="Opacne nesouhlasny", zkratka="ON",
            je_indispozicni_volno=False,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        with self.assertRaises(ValidationError):
            opacne_nesouhlasny.full_clean()


class SamoZaznamTestCase(TestCase):
    """Typy s vyzaduje_schvaleni=False (nemoc, OČR, služební volno, home office)
    se zaznamenávají samy zaměstnancem, bez schvalování vedoucím."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        self.uvazek = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        user = User.objects.create_user(
            username="petr@example.com", email="petr@example.com",
            first_name="Petr", last_name="Pilny",
        )
        self.employee = Employee.objects.create(
            user=user, osobni_cislo="1", oddeleni=self.oddeleni,
            typ_uvazku=self.uvazek, datum_nastupu=date(2020, 1, 1),
        )

        self.typ_home_office = TypStavu.objects.create(
            nazev="Home office", zkratka="HO",
            odecita_ze_zustatku=False, je_pritomnost=True,
            vyzaduje_schvaleni=False, barva="#6610F2",
        )
        self.typ_dovolena = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV",
            odecita_ze_zustatku=True, vyzaduje_schvaleni=True,
        )

    def test_samo_zaznam_je_ihned_schvaleny_bez_schvalovatele(self):
        zadost = ZadostOStav(
            employee=self.employee, typ=self.typ_home_office,
            datum_od=date(2026, 7, 6), datum_do=date(2026, 7, 6),
        )
        zadost.save()

        self.assertEqual(zadost.stav, ZadostOStav.Stav.SCHVALENO)
        self.assertIsNone(zadost.schvalovatele)
        self.assertIsNotNone(zadost.schvaleno_kdy)
        self.assertGreater(zadost.pocet_hodin, 0)

    def test_zadost_vyzadujici_schvaleni_zustava_cekajici_a_ma_schvalovatele(self):
        zadost = ZadostOStav(
            employee=self.employee, typ=self.typ_dovolena,
            datum_od=date(2026, 7, 6), datum_do=date(2026, 7, 6),
        )
        zadost.save()

        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)

    def test_ke_schvaleni_neobsahuje_samo_zaznamy(self):
        """Fronta ke schválení vidí jen typy vyzadujici_schvaleni=True."""
        self.oddeleni.vedouci = self.employee
        self.oddeleni.save()

        ZadostOStav.objects.create(
            employee=self.employee, typ=self.typ_home_office,
            datum_od=date(2026, 7, 6), datum_do=date(2026, 7, 6),
            schvalovatele=self.employee,
        )
        zadost_dovolena = ZadostOStav.objects.create(
            employee=self.employee, typ=self.typ_dovolena,
            datum_od=date(2026, 7, 7), datum_do=date(2026, 7, 7),
            schvalovatele=self.employee,
        )

        self.employee.user.set_password("test12345")
        self.employee.user.save()
        self.assertTrue(self.client.login(username="petr@example.com", password="test12345"))

        response = self.client.get(reverse("leaves:ke_schvaleni"))
        self.assertEqual(response.status_code, 200)
        zadosti = list(response.context["zadosti"])
        self.assertEqual(zadosti, [zadost_dovolena])


class ObnovRocniNarokyTests(TestCase):
    """Indispoziční volno se při ročním obnovení NEPŘEVÁDÍ (žádný zbytek z
    minulého roku) — nový zůstatek se rovnou nastaví na aktuální nárokovou
    hodnotu z NarokIndispozicnihoVolna. Dovolená naproti tomu zbytek převádí
    a k němu připočítává nový roční nárok."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        typ_uvazku = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        user = User.objects.create_user(
            username="jan@example.com", email="jan@example.com",
            first_name="Jan", last_name="Novák",
        )
        self.employee = Employee.objects.create(
            user=user, osobni_cislo="1", oddeleni=oddeleni,
            typ_uvazku=typ_uvazku, datum_nastupu=date(2020, 1, 1),
        )

        self.typ_iv = TypStavu.objects.create(
            nazev="Indispoziční volno", zkratka="IV",
            odecita_ze_zustatku=True, je_indispozicni_volno=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        self.typ_dov = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV",
            odecita_ze_zustatku=True, je_dovolena=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA,
        )

        NarokIndispozicnihoVolna.objects.create(hodin=Decimal("50.00"), platne_od=date(2020, 1, 1))
        NarokDovolene.objects.create(hodin=Decimal("160.00"), platne_od=date(2020, 1, 1))

        ZustatekStavu.objects.create(
            employee=self.employee, rok=2025, typ=self.typ_iv,
            narok_hodin=Decimal("40.00"), cerpano_hodin=Decimal("15.00"),
        )
        ZustatekStavu.objects.create(
            employee=self.employee, rok=2025, typ=self.typ_dov,
            narok_hodin=Decimal("160.00"), cerpano_hodin=Decimal("100.00"),
        )

    def test_indispozicni_volno_se_nastavi_na_narokovou_hodnotu_bez_prevodu_zbytku(self):
        call_command("obnov_rocni_naroky", rok=2026)
        zustatek = ZustatekStavu.objects.get(employee=self.employee, rok=2026, typ=self.typ_iv)
        # Loňský zbytek byl 40-15=25h. Nový nárok musí být přesně 50h (aktuální
        # NarokIndispozicnihoVolna), ne 25h (jen zbytek) ani 75h (zbytek + nárok).
        self.assertEqual(zustatek.narok_hodin, Decimal("50.00"))

    def test_dovolena_prevede_zbytek_a_pricte_novy_rocni_narok(self):
        call_command("obnov_rocni_naroky", rok=2026)
        zustatek = ZustatekStavu.objects.get(employee=self.employee, rok=2026, typ=self.typ_dov)
        # Loňský zbytek 160-100=60h + nový roční nárok 160h = 220h.
        self.assertEqual(zustatek.narok_hodin, Decimal("220.00"))

    def test_je_idempotentni_neprepise_uz_existujici_zustatek(self):
        ZustatekStavu.objects.create(
            employee=self.employee, rok=2026, typ=self.typ_iv,
            narok_hodin=Decimal("99.00"),
        )
        call_command("obnov_rocni_naroky", rok=2026)
        zustatek = ZustatekStavu.objects.get(employee=self.employee, rok=2026, typ=self.typ_iv)
        self.assertEqual(zustatek.narok_hodin, Decimal("99.00"))


class ZustatkyNovehoZamestnanceTests(TestCase):
    """Nový aktivní zaměstnanec dostane hned zůstatky stavů na letošní rok, bez ohledu
    na to, jestli už běžel příkaz obnov_rocni_naroky."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        self.typ_uvazku = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00")
        )
        self.typ_iv = TypStavu.objects.create(
            nazev="Indispoziční volno", zkratka="IV",
            odecita_ze_zustatku=True, je_indispozicni_volno=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        self.typ_dov = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV",
            odecita_ze_zustatku=True, je_dovolena=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA,
        )
        self.typ_nemoc = TypStavu.objects.create(
            nazev="Nemoc", zkratka="NEM", odecita_ze_zustatku=False, vyzaduje_schvaleni=False,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.NEMOC,
        )
        self.dnes = timezone.localdate()
        NarokIndispozicnihoVolna.objects.create(hodin=Decimal("50.00"), platne_od=date(2020, 1, 1))
        NarokDovolene.objects.create(hodin=Decimal("160.00"), platne_od=date(2020, 1, 1))

    def _zamestnanec(self, cislo, **kwargs):
        user = User.objects.create_user(
            username=f"z{cislo}@example.com", email=f"z{cislo}@example.com",
            first_name="Jan", last_name=f"Novák{cislo}",
        )
        return Employee.objects.create(
            user=user, osobni_cislo=cislo, oddeleni=self.oddeleni,
            typ_uvazku=self.typ_uvazku, datum_nastupu=date(2020, 1, 1), **kwargs,
        )

    def _odecitajici_typy(self):
        return TypStavu.objects.filter(odecita_ze_zustatku=True, aktivni=True).values_list("pk", flat=True)

    def test_novy_zamestnanec_dostane_zustatky_odecitajicich_typu(self):
        employee = self._zamestnanec("1")
        zustatky = {
            z.typ_id: z.narok_hodin
            for z in ZustatekStavu.objects.filter(employee=employee, rok=self.dnes.year)
        }
        self.assertEqual(zustatky[self.typ_iv.pk], Decimal("50.00"))
        self.assertEqual(zustatky[self.typ_dov.pk], Decimal("160.00"))
        self.assertNotIn(self.typ_nemoc.pk, zustatky)
        # Přesně jeden zůstatek na každý aktivní typ odečítající ze zůstatku
        # (migrace mohou nasadit i další typy než ty z setUp).
        self.assertEqual(set(zustatky), set(self._odecitajici_typy()))

    def test_neaktivni_zamestnanec_zustatky_nedostane(self):
        employee = self._zamestnanec("1", aktivni=False)
        self.assertFalse(ZustatekStavu.objects.filter(employee=employee).exists())

    def test_neaktivni_typ_stavu_se_preskoci(self):
        self.typ_dov.aktivni = False
        self.typ_dov.save()
        employee = self._zamestnanec("1")
        self.assertFalse(ZustatekStavu.objects.filter(employee=employee, typ=self.typ_dov).exists())
        self.assertTrue(ZustatekStavu.objects.filter(employee=employee, typ=self.typ_iv).exists())

    def test_dalsi_ulozeni_zamestnance_zustatky_nezmeni_ani_nezduplikuje(self):
        employee = self._zamestnanec("1")
        zustatek = ZustatekStavu.objects.get(employee=employee, rok=self.dnes.year, typ=self.typ_iv)
        zustatek.cerpano_hodin = Decimal("10.00")
        zustatek.save()
        employee.save()
        self.assertEqual(
            ZustatekStavu.objects.filter(employee=employee).count(), len(self._odecitajici_typy())
        )
        zustatek.refresh_from_db()
        self.assertEqual(zustatek.cerpano_hodin, Decimal("10.00"))

    def test_obnov_rocni_naroky_po_zalozeni_zamestnance_nic_nedoplni(self):
        employee = self._zamestnanec("1")
        pred = ZustatekStavu.objects.filter(employee=employee).count()
        call_command("obnov_rocni_naroky", rok=self.dnes.year)
        self.assertEqual(ZustatekStavu.objects.filter(employee=employee).count(), pred)
        self.assertEqual(pred, len(self._odecitajici_typy()))


class HodinyZadostiPodleTypuUvazkuTests(TestCase):
    """Issue #74 — hodiny žádosti: u pevné pracovní doby čistá doba bloků daného dne
    (stejná norma jako ve Výkazu, #72), u pružné hodiny_denne každý den Po–Pá."""

    PONDELI = date(2026, 10, 5)  # po 5. – pá 9. 10. 2026 bez státního svátku

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        self.typ_uvazku = TypUvazku.objects.create(
            nazev="Pevná", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00"),
            druh_pracovni_doby=TypUvazku.DruhPracovniDoby.PEVNA,
        )
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.typ_uvazku, blok_od="07:30", blok_do="16:15",
            pondeli=True, utery=True, streda=True, ctvrtek=True,
        )
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.typ_uvazku, blok_od="07:30", blok_do="15:00", patek=True,
        )
        user = User.objects.create_user(
            username="pevny@example.com", email="pevny@example.com",
            first_name="Pevný", last_name="Zaměstnanec",
        )
        self.employee = Employee.objects.create(
            user=user, osobni_cislo="1", oddeleni=oddeleni,
            typ_uvazku=self.typ_uvazku, datum_nastupu=date(2020, 1, 1),
        )
        self.typ_stavu = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV", odecita_ze_zustatku=True, vyzaduje_schvaleni=True,
        )

    def _hodiny(self, od, do):
        zadost = ZadostOStav(
            employee=self.employee, typ=self.typ_stavu, datum_od=od, datum_do=do,
        )
        zadost.vypocitej_hodiny()
        return zadost.pocet_hodin

    def test_pevna_cely_tyden_je_40_hodin(self):
        self.assertEqual(
            self._hodiny(self.PONDELI, self.PONDELI + timedelta(days=4)), Decimal("40.00")
        )

    def test_pevna_jeden_patek_je_7_hodin_a_pondeli_8_25(self):
        self.assertEqual(self._hodiny(date(2026, 10, 9), date(2026, 10, 9)), Decimal("7.00"))
        self.assertEqual(self._hodiny(self.PONDELI, self.PONDELI), Decimal("8.25"))

    def test_pevna_svatek_se_preskoci(self):
        StatniSvatek.objects.create(datum=date(2026, 10, 9), nazev="Svátek", zeme=self._zeme())
        self.assertEqual(
            self._hodiny(self.PONDELI, self.PONDELI + timedelta(days=4)), Decimal("33.00")
        )

    def test_pevna_den_bez_bloku_je_nula(self):
        self.typ_uvazku.casove_bloky.filter(patek=True).delete()
        self.assertEqual(self._hodiny(date(2026, 10, 9), date(2026, 10, 9)), Decimal("0.00"))

    def test_zadost_pres_vikend_pocita_jen_pracovni_dny(self):
        self.assertEqual(self._hodiny(date(2026, 10, 9), date(2026, 10, 12)), Decimal("15.25"))

    def test_pruzna_ma_kazdy_den_hodiny_denne(self):
        self.typ_uvazku.druh_pracovni_doby = TypUvazku.DruhPracovniDoby.PRUZNA
        self.typ_uvazku.save()
        self.assertEqual(self._hodiny(date(2026, 10, 9), date(2026, 10, 9)), Decimal("8.00"))
        self.assertEqual(
            self._hodiny(self.PONDELI, self.PONDELI + timedelta(days=4)), Decimal("40.00")
        )

    def test_ulozena_zadost_pouzije_nove_hodiny(self):
        zadost = ZadostOStav.objects.create(
            employee=self.employee, typ=self.typ_stavu,
            datum_od=date(2026, 10, 9), datum_do=date(2026, 10, 9),
        )
        zadost.refresh_from_db()
        self.assertEqual(zadost.pocet_hodin, Decimal("7.00"))

    @staticmethod
    def _zeme():
        from accounts.holidays_model import Zeme
        return Zeme.objects.get_or_create(kod="CZ", defaults={"nazev": "Česko"})[0]


class HodinovaDovolenaTests(TestCase):
    """Issue #82 — dovolená po hodinách (čas od–do)."""

    PONDELI = date(2026, 10, 12)  # po 12. – pá 16. 10. 2026, bez státního svátku
    CTVRTEK = date(2026, 10, 15)
    PATEK = date(2026, 10, 16)
    SOBOTA = date(2026, 10, 17)

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        self.pruzna = TypUvazku.objects.create(
            nazev="Pružná", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00"),
            druh_pracovni_doby=TypUvazku.DruhPracovniDoby.PRUZNA,
        )
        self.pevna = TypUvazku.objects.create(
            nazev="Pevná", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00"),
            druh_pracovni_doby=TypUvazku.DruhPracovniDoby.PEVNA,
        )
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.pevna, blok_od="07:30", blok_do="16:15",
            pondeli=True, utery=True, streda=True, ctvrtek=True,
        )
        CasovyBlokUvazku.objects.create(
            typ_uvazku=self.pevna, blok_od="07:30", blok_do="15:00", patek=True,
        )
        self.emp_pruzna = self._zamestnanec("pruzna@example.com", "1", self.pruzna, oddeleni)
        self.emp_pevna = self._zamestnanec("pevna@example.com", "2", self.pevna, oddeleni)
        self.dovolena = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV", je_dovolena=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA,
            umoznuje_zadani_po_hodinach=True,
        )
        self.nemoc = TypStavu.objects.create(
            nazev="Nemoc", zkratka="NEM", odecita_ze_zustatku=False, vyzaduje_schvaleni=False,
        )
        NarokDovolene.objects.create(hodin=Decimal("160.00"), platne_od=date(2026, 1, 1))

    @staticmethod
    def _zamestnanec(email, cislo, typ_uvazku, oddeleni):
        user = User.objects.create_user(
            username=email, email=email, first_name="Jan", last_name=cislo,
        )
        return Employee.objects.create(
            user=user, osobni_cislo=cislo, oddeleni=oddeleni,
            typ_uvazku=typ_uvazku, datum_nastupu=date(2020, 1, 1),
        )

    def _zadost(self, employee, od, do, cas_od=None, cas_do=None, typ=None):
        return ZadostOStav(
            employee=employee, typ=typ or self.dovolena, datum_od=od, datum_do=do,
            cas_od=cas_od, cas_do=cas_do,
        )

    def _hodiny(self, employee, od, do, cas_od, cas_do):
        zadost = self._zadost(employee, od, do, cas_od, cas_do)
        zadost.vypocitej_hodiny()
        return zadost.pocet_hodin

    def _uloz(self, employee, od, do, cas_od=None, cas_do=None):
        zadost = self._zadost(employee, od, do, cas_od, cas_do)
        zadost.full_clean()
        zadost.save()
        return zadost

    # --- výpočet hodin ---

    def test_pruzna_jeden_den_je_rozdil_od_do(self):
        self.assertEqual(
            self._hodiny(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 30)),
            Decimal("2.50"),
        )

    def test_hodiny_dne_se_omezi_denni_normou(self):
        self.assertEqual(
            self._hodiny(self.emp_pruzna, self.PONDELI, self.PONDELI, time(6, 0), time(18, 0)),
            Decimal("8.00"),
        )

    def test_pevna_jeden_den_je_rozdil_od_do(self):
        self.assertEqual(
            self._hodiny(self.emp_pevna, self.PATEK, self.PATEK, time(13, 0), time(15, 0)),
            Decimal("2.00"),
        )

    def test_pevna_vice_dnu_je_souvisly_interval(self):
        """Čtvrtek 14:00 – pátek 9:00 = 2:15 do konce bloku + 1:30 od začátku bloku."""
        self.assertEqual(
            self._hodiny(self.emp_pevna, self.CTVRTEK, self.PATEK, time(14, 0), time(9, 0)),
            Decimal("3.75"),
        )

    def test_pevna_pres_vikend_prvni_posledni_den_castecne_mezi_nimi_cela_norma(self):
        """Čtvrtek 14:00 – pondělí 9:00: 2:15 (čt) + 7 h (pá, celá norma) + 1:30 (po)."""
        self.assertEqual(
            self._hodiny(self.emp_pevna, self.CTVRTEK, self.PONDELI + timedelta(days=7),
                         time(14, 0), time(9, 0)),
            Decimal("10.75"),
        )

    def test_svatek_uprostred_intervalu_se_preskoci(self):
        zeme = Zeme.objects.create(kod="CZ", nazev="Česko")
        StatniSvatek.objects.create(datum=self.PATEK, nazev="Svátek", zeme=zeme)
        self.assertEqual(
            self._hodiny(self.emp_pevna, self.CTVRTEK, self.PONDELI + timedelta(days=7),
                         time(14, 0), time(9, 0)),
            Decimal("3.75"),
        )

    def test_dny_bez_casu_se_pocitaji_jako_drive(self):
        self.assertEqual(
            self._hodiny(self.emp_pevna, self.PONDELI, self.PONDELI + timedelta(days=4), None, None),
            Decimal("40.00"),
        )

    # --- validace ---

    def test_pruzna_vice_dnu_po_hodinach_je_zamitnuta(self):
        zadost = self._zadost(
            self.emp_pruzna, self.PONDELI, self.PONDELI + timedelta(days=1), time(9, 0), time(11, 0),
        )
        with self.assertRaisesMessage(ValidationError, "jen v rámci jednoho dne"):
            zadost.full_clean()

    def test_jen_jeden_z_casu_je_zamitnut(self):
        zadost = self._zadost(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), None)
        with self.assertRaisesMessage(ValidationError, "čas od i čas do"):
            zadost.full_clean()

    def test_cas_do_musi_byt_po_case_od(self):
        zadost = self._zadost(self.emp_pruzna, self.PONDELI, self.PONDELI, time(11, 0), time(9, 0))
        with self.assertRaisesMessage(ValidationError, "po čase od"):
            zadost.full_clean()

    def test_typ_bez_priznaku_po_hodinach_nelze(self):
        zadost = self._zadost(
            self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0), typ=self.nemoc,
        )
        with self.assertRaisesMessage(ValidationError, "nelze zadat po hodinách"):
            zadost.full_clean()

    def test_hodinova_zadost_jen_na_vikend_je_zamitnuta(self):
        zadost = self._zadost(
            self.emp_pruzna, self.SOBOTA, self.SOBOTA, time(9, 0), time(11, 0),
        )
        with self.assertRaisesMessage(ValidationError, "žádný pracovní den"):
            zadost.full_clean()

    def test_prekryv_s_jinou_hodinovou_zadosti_je_zamitnut(self):
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))
        zadost = self._zadost(self.emp_pruzna, self.PONDELI, self.PONDELI, time(10, 0), time(12, 0))
        with self.assertRaisesMessage(ValidationError, "časově překrývá"):
            zadost.full_clean()

    def test_navazujici_hodinove_zadosti_se_neprekryvaji(self):
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(11, 0), time(12, 0))

    def test_hodinova_zadost_v_dni_s_celodenni_zadosti_je_zamitnuta(self):
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI)
        zadost = self._zadost(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))
        with self.assertRaisesMessage(ValidationError, "časově překrývá"):
            zadost.full_clean()

    def test_celodenni_zadost_v_dni_s_hodinovou_je_zamitnuta(self):
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))
        zadost = self._zadost(self.emp_pruzna, self.PONDELI, self.PONDELI)
        with self.assertRaisesMessage(ValidationError, "časově překrývá"):
            zadost.full_clean()

    def test_dve_celodenni_zadosti_se_dal_nehlidaji(self):
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI)
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI)

    def test_stornovana_zadost_neblokuje(self):
        puvodni = self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))
        puvodni.stav = ZadostOStav.Stav.STORNOVÁNO
        puvodni.save()
        self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 0))

    def test_soucet_za_den_nesmi_prekrocit_normu(self):
        """4:30 + 4:15 = 8:45 > 8:15 (norma pevné doby v pondělí), i když se časy nepřekrývají."""
        self._uloz(self.emp_pevna, self.PONDELI, self.PONDELI, time(7, 30), time(12, 0))
        zadost = self._zadost(self.emp_pevna, self.PONDELI, self.PONDELI, time(12, 0), time(16, 15))
        with self.assertRaisesMessage(ValidationError, "překročil denní normu"):
            zadost.full_clean()

    # --- zůstatek a Výkaz ---

    def test_schvaleni_odecte_hodiny_ze_zustatku(self):
        zadost = self._uloz(self.emp_pruzna, self.PONDELI, self.PONDELI, time(9, 0), time(11, 30))
        self.assertEqual(zadost.pocet_hodin, Decimal("2.50"))
        zadost.schval(self.emp_pevna)
        zustatek = ZustatekStavu.objects.get(employee=self.emp_pruzna, rok=2026, typ=self.dovolena)
        self.assertEqual(zustatek.cerpano_hodin, Decimal("2.50"))

    def test_vicedenni_hodinova_zadost_pevne_doby_odecte_cely_interval(self):
        zadost = self._uloz(self.emp_pevna, self.CTVRTEK, self.PATEK, time(14, 0), time(9, 0))
        zadost.schval(self.emp_pruzna)
        zustatek = ZustatekStavu.objects.get(employee=self.emp_pevna, rok=2026, typ=self.dovolena)
        self.assertEqual(zustatek.cerpano_hodin, Decimal("3.75"))

    def test_schvalena_hodinova_dovolena_se_pocita_do_denni_normy(self):
        den = self.PONDELI
        zacatek = timezone.make_aware(datetime.combine(den, time(8, 0)))
        WorkSession.objects.create(
            employee=self.emp_pruzna, zacatek=zacatek, konec=zacatek + timedelta(hours=6, minutes=30),
        )
        souhrn = WorkdaySummary.objects.get(employee=self.emp_pruzna, datum=den)
        self.assertEqual(souhrn.odpracovane_minuty, 360)  # 6 h 30 min − 30 min přestávka
        self.assertEqual(souhrn.prescos_minuty, -120)

        zadost = self._uloz(self.emp_pruzna, den, den, time(14, 30), time(16, 30))
        souhrn.refresh_from_db()
        self.assertEqual(souhrn.prescos_minuty, -120)  # čekající žádost se nepočítá

        zadost.schval(self.emp_pevna)
        souhrn.refresh_from_db()
        self.assertEqual(souhrn.prescos_minuty, 0)  # 6 h + 2 h dovolené − 8 h normy

    def test_den_bez_hodinove_dovolene_se_nemeni(self):
        den = self.PONDELI
        zacatek = timezone.make_aware(datetime.combine(den, time(8, 0)))
        WorkSession.objects.create(
            employee=self.emp_pruzna, zacatek=zacatek, konec=zacatek + timedelta(hours=8, minutes=30),
        )
        souhrn = WorkdaySummary.objects.get(employee=self.emp_pruzna, datum=den)
        self.assertEqual(souhrn.prescos_minuty, 0)

    # --- formulář ---

    def _formular(self, employee, data):
        zaklad = {"typ": self.dovolena.pk, "datum_od": self.PONDELI, "datum_do": self.PONDELI}
        zaklad.update(data)
        return ZadostOStavForm(zaklad, employee=employee)

    def test_formular_prijme_hodinovou_zadost(self):
        form = self._formular(self.emp_pruzna, {"cas_od": "09:00", "cas_do": "11:30"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_formular_odmitne_nedostatecny_zustatek_pro_hodiny(self):
        ZustatekStavu.objects.create(
            employee=self.emp_pruzna, rok=2026, typ=self.dovolena,
            narok_hodin=Decimal("2.00"),
        )
        form = self._formular(self.emp_pruzna, {"cas_od": "09:00", "cas_do": "11:30"})
        self.assertFalse(form.is_valid())
        self.assertIn("Nedostatečný zůstatek", str(form.errors))

    def test_formular_odmitne_typ_bez_priznaku_s_casem(self):
        form = self._formular(
            self.emp_pruzna, {"typ": self.nemoc.pk, "cas_od": "09:00", "cas_do": "11:00"},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("nelze zadat po hodinách", str(form.errors))

    def test_formular_nabizi_cas_jen_u_typu_s_priznakem(self):
        form = self._formular(self.emp_pruzna, {})
        self.assertEqual(form.typy_po_hodinach, [self.dovolena.pk])

    def test_typ_stavu_ma_priznak_po_hodinach_ve_vychozim_stavu_vypnuty(self):
        self.assertFalse(TypStavu.objects.create(nazev="Jiné", zkratka="J").umoznuje_zadani_po_hodinach)

    # --- stránka nové žádosti ---

    def test_stranka_nove_zadosti_nabizi_pole_cas_od_do(self):
        self.client.force_login(self.emp_pruzna.user)
        odpoved = self.client.get(reverse("leaves:nova_zadost"))
        self.assertEqual(odpoved.status_code, 200)
        self.assertContains(odpoved, 'id="id_cas_od"')
        self.assertContains(odpoved, 'id="typy-po-hodinach"')

    def test_odeslani_hodinove_zadosti_ulozi_cas_a_hodiny(self):
        self.client.force_login(self.emp_pruzna.user)
        odpoved = self.client.post(reverse("leaves:nova_zadost"), {
            "typ": self.dovolena.pk, "datum_od": "2026-10-12", "datum_do": "2026-10-12",
            "cas_od": "09:00", "cas_do": "11:30",
        })
        self.assertEqual(odpoved.status_code, 302)
        zadost = ZadostOStav.objects.get(employee=self.emp_pruzna)
        self.assertEqual((zadost.cas_od, zadost.cas_do), (time(9, 0), time(11, 30)))
        self.assertEqual(zadost.pocet_hodin, Decimal("2.50"))
        self.assertContains(self.client.get(reverse("leaves:moje_zadosti")), "9:00")


class OdkazKeSchvaleniTests(TestCase):
    """Odkaz „Ke schválení“ (menu i úvodní stránka) vidí každý, kdo schvaluje —
    i vedoucí odboru, který nevede žádné oddělení (dřív jen vedoucí oddělení)."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        self.odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddělení", kod="OD1")
        self.vedeni = Oddeleni.objects.create(odbor=self.odbor, nazev="Vedení", kod="OD2")
        typ_uvazku = TypUvazku.objects.create(
            nazev="Plný", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00"),
        )

        def zamestnanec(email, cislo, oddeleni):
            user = User.objects.create_user(
                username=email, email=email, first_name="Jan", last_name=cislo,
            )
            return Employee.objects.create(
                user=user, osobni_cislo=cislo, oddeleni=oddeleni,
                typ_uvazku=typ_uvazku, datum_nastupu=date(2020, 1, 1),
            )

        self.vedouci_oddeleni = zamestnanec("vedouci@example.com", "1", self.oddeleni)
        self.vedouci_odboru = zamestnanec("odbor@example.com", "2", self.vedeni)
        self.zastupce = zamestnanec("zastupce@example.com", "3", self.oddeleni)
        self.radovy = zamestnanec("radovy@example.com", "4", self.oddeleni)
        self.oddeleni.vedouci = self.vedouci_oddeleni
        self.oddeleni.save()
        self.odbor.vedouci = self.vedouci_odboru
        self.odbor.save()
        # Vedoucí odboru nevede žádné oddělení (jeho „vedení“ nemá vedoucího).
        Employee.objects.filter(pk=self.zastupce.pk).update(zastupce=None)
        Employee.objects.filter(pk=self.vedouci_oddeleni.pk).update(zastupce=self.zastupce)

    def _odkaz(self, employee):
        self.client.force_login(employee.user)
        return self.client.get(reverse("accounts:home")).content.decode()

    def test_vedouci_odboru_bez_vlastniho_oddeleni_vidi_odkaz(self):
        self.assertIsNone(self.vedeni.vedouci)
        self.assertIn(reverse("leaves:ke_schvaleni"), self._odkaz(self.vedouci_odboru))

    def test_vedouci_oddeleni_odkaz_vidi(self):
        self.assertIn(reverse("leaves:ke_schvaleni"), self._odkaz(self.vedouci_oddeleni))

    def test_zastupce_vedouciho_odkaz_vidi(self):
        self.assertIn(reverse("leaves:ke_schvaleni"), self._odkaz(self.zastupce))

    def test_radovy_zamestnanec_odkaz_nevidi(self):
        self.assertNotIn(reverse("leaves:ke_schvaleni"), self._odkaz(self.radovy))

    def test_zamestnanec_s_cekajici_zadosti_ke_schvaleni_odkaz_vidi(self):
        typ = TypStavu.objects.create(nazev="Dovolená", zkratka="DOV", je_dovolena=True,
                                      kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA)
        ZadostOStav.objects.create(
            employee=self.vedouci_oddeleni, typ=typ, datum_od=date(2026, 10, 9),
            datum_do=date(2026, 10, 9), schvalovatele=self.radovy,
        )
        self.assertIn(reverse("leaves:ke_schvaleni"), self._odkaz(self.radovy))


class SamoschvaleniZadostiTests(TestCase):
    """#90 — schvalovatel (vedoucí, zástupce) si ve výjimečném případě schválí vlastní
    čekající žádost; povinný důvod, označení v detailu, bez e-mailu."""

    def setUp(self):
        self.sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        self.odbor = Odbor.objects.create(sekce=self.sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddělení", kod="OD1")
        self.vedeni = Oddeleni.objects.create(odbor=self.odbor, nazev="Vedení", kod="OD2")
        self.typ_uvazku = TypUvazku.objects.create(
            nazev="Plný", hodiny_denne=Decimal("8.00"), hodiny_tyydne=Decimal("40.00"),
        )
        self.vedouci = self._zamestnanec("vedouci@example.com", "1", self.oddeleni)
        self.reditel_odboru = self._zamestnanec("odbor@example.com", "2", self.vedeni)
        self.radovy = self._zamestnanec("radovy@example.com", "3", self.oddeleni)
        self.oddeleni.vedouci = self.vedouci
        self.oddeleni.save()
        self.odbor.vedouci = self.reditel_odboru
        self.odbor.save()

        self.typ = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV", je_dovolena=True, odecita_ze_zustatku=True,
            kategorie_pro_prehled=TypStavu.KategoriePrehled.DOVOLENA,
        )
        NarokDovolene.objects.create(hodin=Decimal("160.00"), platne_od=date(2026, 1, 1))

    def _zamestnanec(self, email, cislo, oddeleni):
        user = User.objects.create_user(
            username=email, email=email, first_name="Jan", last_name=cislo,
        )
        return Employee.objects.create(
            user=user, osobni_cislo=cislo, oddeleni=oddeleni,
            typ_uvazku=self.typ_uvazku, datum_nastupu=date(2020, 1, 1),
        )

    def _zadost(self, employee, **kwargs):
        return ZadostOStav.objects.create(
            employee=employee, typ=self.typ,
            datum_od=date(2026, 10, 9), datum_do=date(2026, 10, 9), **kwargs,
        )

    def _schval_sam(self, employee, zadost, duvod="Ředitelka je mimo kancelář"):
        self.client.force_login(employee.user)
        return self.client.post(
            reverse("leaves:schvalit_sam", args=[zadost.pk]), {"duvod": duvod},
        )

    def test_vedouci_oddeleni_si_schvali_vlastni_zadost_s_duvodem(self):
        zadost = self._zadost(self.vedouci)
        self.assertEqual(zadost.schvalovatele, self.reditel_odboru)

        odpoved = self._schval_sam(self.vedouci, zadost)

        self.assertRedirects(odpoved, reverse("leaves:detail_zadosti", args=[zadost.pk]))
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.SCHVALENO)
        self.assertTrue(zadost.samoschvaleno)
        self.assertEqual(zadost.schvaleno_kym, self.vedouci)
        self.assertEqual(zadost.poznamka_schvalovatele, "Ředitelka je mimo kancelář")
        self.assertIsNotNone(zadost.schvaleno_kdy)

    def test_zustatek_se_odecte_prave_jednou(self):
        zadost = self._zadost(self.vedouci)
        self._schval_sam(self.vedouci, zadost)
        self._schval_sam(self.vedouci, zadost)  # druhý pokus: už vyřízeno
        zustatek = ZustatekStavu.objects.get(employee=self.vedouci, rok=2026, typ=self.typ)
        self.assertEqual(zustatek.cerpano_hodin, Decimal("8.00"))

    def test_prazdny_duvod_se_odmitne_a_zadost_zustane_cekajici(self):
        zadost = self._zadost(self.vedouci)
        for duvod in ("", "   "):
            odpoved = self._schval_sam(self.vedouci, zadost, duvod=duvod)
            self.assertEqual(odpoved.status_code, 302)
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)
        self.assertFalse(zadost.samoschvaleno)
        odpoved = self.client.get(reverse("leaves:detail_zadosti", args=[zadost.pk]))
        self.assertContains(odpoved, "Uveďte důvod samoschválení.")

    def test_radovy_zamestnanec_nema_v_detailu_moznost_a_post_je_odmitnut(self):
        zadost = self._zadost(self.radovy)
        self.client.force_login(self.radovy.user)
        odpoved = self.client.get(reverse("leaves:detail_zadosti", args=[zadost.pk]))
        self.assertNotContains(odpoved, "Schválit sám")
        self.assertNotContains(odpoved, reverse("leaves:schvalit_sam", args=[zadost.pk]))

        self.assertEqual(self._schval_sam(self.radovy, zadost).status_code, 403)
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)

    def test_cizi_zadost_si_schvalovatel_timto_neschvali(self):
        zadost = self._zadost(self.radovy)
        self.assertEqual(zadost.schvalovatele, self.vedouci)
        self.assertEqual(self._schval_sam(self.vedouci, zadost).status_code, 403)
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)

    def test_uz_vyrizena_zadost_zustane_beze_zmeny(self):
        zadost = self._zadost(self.vedouci)
        zadost.zamitni(self.reditel_odboru, poznamka="Ne")
        self._schval_sam(self.vedouci, zadost)
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.ZAMITNUTO)
        self.assertFalse(zadost.samoschvaleno)

    def test_reditel_sekce_bez_schvalovatele_se_schvali_sam(self):
        # Odbor bez vedoucího → žádný nadřízený kromě (jeho vlastní) sekce.
        odbor_sekce = Odbor.objects.create(sekce=self.sekce, nazev="Odbor ředitele", kod="O9")
        oddeleni_sekce = Oddeleni.objects.create(odbor=odbor_sekce, nazev="Kabinet", kod="OD9")
        reditel_sekce = self._zamestnanec("sekce@example.com", "9", oddeleni_sekce)
        self.sekce.vedouci = reditel_sekce
        self.sekce.save()
        zadost = self._zadost(reditel_sekce)
        self.assertIsNone(zadost.schvalovatele)

        self._schval_sam(reditel_sekce, zadost)

        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.SCHVALENO)
        self.assertTrue(zadost.samoschvaleno)

    def test_hodinova_zadost_se_schvali_sam_a_odecte_hodiny(self):
        zadost = self._zadost(self.vedouci, cas_od=time(11, 0), cas_do=time(15, 0))
        self._schval_sam(self.vedouci, zadost)
        zustatek = ZustatekStavu.objects.get(employee=self.vedouci, rok=2026, typ=self.typ)
        self.assertEqual(zustatek.cerpano_hodin, Decimal("4.00"))

    def test_zadost_zmizi_nadrizenemu_z_ke_schvaleni(self):
        zadost = self._zadost(self.vedouci)
        adresa = reverse("leaves:detail_zadosti", args=[zadost.pk])
        self.client.force_login(self.reditel_odboru.user)
        self.assertContains(self.client.get(reverse("leaves:ke_schvaleni")), adresa)
        self._schval_sam(self.vedouci, zadost)
        self.client.force_login(self.reditel_odboru.user)
        self.assertNotContains(self.client.get(reverse("leaves:ke_schvaleni")), adresa)

    def test_detail_ukaze_oznaceni_a_duvod_i_nadrizenemu(self):
        zadost = self._zadost(self.vedouci)
        self._schval_sam(self.vedouci, zadost)
        self.client.force_login(self.reditel_odboru.user)
        odpoved = self.client.get(reverse("leaves:detail_zadosti", args=[zadost.pk]))
        self.assertContains(odpoved, "Schváleno vlastní osobou")
        self.assertContains(odpoved, "Důvod samoschválení")
        self.assertContains(odpoved, "Ředitelka je mimo kancelář")

    def test_vedouci_vidi_tlacitko_u_vlastni_cekajici_zadosti(self):
        zadost = self._zadost(self.vedouci)
        self.client.force_login(self.vedouci.user)
        odpoved = self.client.get(reverse("leaves:detail_zadosti", args=[zadost.pk]))
        self.assertContains(odpoved, "Schválit sám")

    def test_samoschvaleni_neposila_email_zadatelovi(self):
        from django.core import mail

        zadost = self._zadost(self.vedouci)
        mail.outbox.clear()
        self._schval_sam(self.vedouci, zadost)
        self.assertEqual(mail.outbox, [])

    def test_normalni_schvaleni_nadrizenym_neni_oznaceno_jako_samoschvaleni(self):
        zadost = self._zadost(self.vedouci)
        self.client.force_login(self.reditel_odboru.user)
        self.client.post(reverse("leaves:schvalit", args=[zadost.pk]))
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.SCHVALENO)
        self.assertFalse(zadost.samoschvaleno)

    def test_get_na_schvalit_sam_nic_neschvali(self):
        zadost = self._zadost(self.vedouci)
        self.client.force_login(self.vedouci.user)
        self.client.get(reverse("leaves:schvalit_sam", args=[zadost.pk]))
        zadost.refresh_from_db()
        self.assertEqual(zadost.stav, ZadostOStav.Stav.CEKA)
