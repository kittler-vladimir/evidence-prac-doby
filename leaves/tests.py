from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Employee, Oddeleni, Odbor, Sekce, TypUvazku
from leaves.forms import ZadostODovolenoForm
from leaves.models import (
    NarokIndispozicnihoVolna,
    TypDovolene,
    ZadostODovolenou,
    ZustatekDovolene,
)

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

        self.typ_iv = TypDovolene.objects.create(
            nazev="Indispoziční volno", zkratka="IV",
            odecita_ze_zustatku=True, je_indispozicni_volno=True,
            kategorie_pro_prehled=TypDovolene.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        NarokIndispozicnihoVolna.objects.create(hodin=Decimal("40.00"), platne_od=date(2026, 1, 1))

    def _zadost(self, employee, datum_od, datum_do):
        zadost = ZadostODovolenou(
            employee=employee, typ=self.typ_iv, datum_od=datum_od, datum_do=datum_do,
        )
        zadost.save()
        return zadost

    def test_schvaleni_zalozi_zustatek_s_globalnim_narokem(self):
        """GIVEN aktivní nárok 40h WHEN je schválena jednodenní žádost THEN vznikne zůstatek 40h/8h čerpáno."""
        zadost = self._zadost(self.employee, date(2026, 7, 6), date(2026, 7, 6))
        zadost.schval(self.employee)

        zustatek = ZustatekDovolene.objects.get(
            employee=self.employee, rok=2026, typ=self.typ_iv
        )
        self.assertEqual(zustatek.narok_hodin, Decimal("40.00"))
        self.assertEqual(zustatek.cerpano_hodin, Decimal("8.00"))
        self.assertEqual(zustatek.zbyvajici_hodin, Decimal("32.00"))

    def test_zadost_presahujici_zustatek_je_odmitnuta_validaci(self):
        # 40h nároku, ale žádost o 6 pracovních dní (48h) přesahuje limit
        form = ZadostODovolenoForm(
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

        zustatek = ZustatekDovolene.objects.get(
            employee=self.employee, rok=2026, typ=self.typ_iv
        )
        self.assertEqual(zustatek.narok_hodin, Decimal("40.00"))

    def test_flat_narok_bez_ohledu_na_uvazek(self):
        """Zaměstnanec s polovičním úvazkem má stejný roční nárok 40h jako na plný úvazek."""
        zadost = self._zadost(self.part_time_employee, date(2026, 7, 6), date(2026, 7, 6))
        zadost.schval(self.part_time_employee)

        zustatek = ZustatekDovolene.objects.get(
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
        self.assertEqual(zadost.stav, ZadostODovolenou.Stav.CEKA)
        self.assertFalse(
            ZustatekDovolene.objects.filter(
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
        nesouhlasny = TypDovolene(
            nazev="Nesouhlasny typ", zkratka="NS",
            je_indispozicni_volno=True,
            kategorie_pro_prehled=TypDovolene.KategoriePrehled.JINA,
        )
        with self.assertRaises(ValidationError):
            nesouhlasny.full_clean()

        opacne_nesouhlasny = TypDovolene(
            nazev="Opacne nesouhlasny", zkratka="ON",
            je_indispozicni_volno=False,
            kategorie_pro_prehled=TypDovolene.KategoriePrehled.INDISPOZICNI_VOLNO,
        )
        with self.assertRaises(ValidationError):
            opacne_nesouhlasny.full_clean()
