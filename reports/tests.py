from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Employee, Oddeleni, Odbor, Sekce, TypUvazku
from leaves.models import TypDovolene, ZadostODovolenou
from timetracking.models import WorkSession
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

        self.oddeleni_a.vedouci = self.zam_a
        self.oddeleni_a.save()

        self.typ_dovolena = TypDovolene.objects.create(
            nazev="Dovolena", zkratka="DOV", odecita_ze_zustatku=True,
            kategorie_pro_prehled=TypDovolene.KategoriePrehled.DOVOLENA,
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
        ZadostODovolenou.objects.create(
            employee=self.zam_b, typ=self.typ_dovolena,
            datum_od=dnes, datum_do=dnes, stav=ZadostODovolenou.Stav.SCHVALENO,
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

    def test_schvalena_zadost_bez_pritomnosti_ukaze_kategorii_absence(self):
        dnes = timezone.localdate()
        ZadostODovolenou.objects.create(
            employee=self.zam_b, typ=self.typ_dovolena,
            datum_od=dnes, datum_do=dnes, stav=ZadostODovolenou.Stav.SCHVALENO,
        )
        stav = stav_zamestnance(self.zam_b, dnes)
        self.assertEqual(stav.kod, TypDovolene.KategoriePrehled.DOVOLENA)

    def test_radovy_zamestnanec_vidi_cely_svuj_odbor(self):
        self._prihlas(self.zam_b, "b@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        videni = {r["employee"].pk for r in response.context["radky"]}
        self.assertEqual(videni, {self.zam_a.pk, self.zam_b.pk})

    def test_vedouci_oddeleni_vidi_jen_sve_oddeleni(self):
        self._prihlas(self.zam_a, "a@example.com")

        response = self.client.get(reverse("reports:prehled_pritomnosti"))
        self.assertEqual(response.status_code, 200)
        videni = {r["employee"].pk for r in response.context["radky"]}
        self.assertEqual(videni, {self.zam_a.pk})

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
