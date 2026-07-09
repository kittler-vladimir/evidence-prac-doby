from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    Employee, HistoriePrislusenosti, Oddeleni, Odbor, Sekce, TypUvazku,
)
from leaves.models import TypStavu, ZadostOStav, ZustatekStavu
from timetracking.models import WorkSession, WorkdaySummary

User = get_user_model()


def _vytvor_zamestnance(email, osobni_cislo, oddeleni, typ_uvazku):
    user = User.objects.create_user(
        username=email, email=email, password="testpass123",
        first_name="Test", last_name="Zaměstnanec",
    )
    return Employee.objects.create(
        user=user, osobni_cislo=osobni_cislo, oddeleni=oddeleni,
        typ_uvazku=typ_uvazku, datum_nastupu=date(2020, 1, 1),
    )


class SmazaniZamestnanceZUzivateleTests(TestCase):
    """Issue #14 — smazání zaměstnance se vším všudy z Uživatelů v adminu."""

    def setUp(self):
        sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        odbor = Odbor.objects.create(sekce=sekce, nazev="Odbor", kod="O1")
        self.oddeleni = Oddeleni.objects.create(odbor=odbor, nazev="Oddělení", kod="OD1")
        typ_uvazku = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=8, hodiny_tyydne=40,
        )

        self.employee = _vytvor_zamestnance(
            "zamestnanec@example.com", "0001", self.oddeleni, typ_uvazku
        )
        self.oddeleni.vedouci = self.employee
        self.oddeleni.save()

        zacatek = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        self.session = WorkSession.objects.create(
            employee=self.employee, zacatek=zacatek, konec=zacatek + timedelta(hours=8),
        )

        self.typ_stavu = TypStavu.objects.create(
            nazev="Dovolená", zkratka="DOV", vyzaduje_schvaleni=True,
        )
        self.zustatek = ZustatekStavu.objects.create(
            employee=self.employee, rok=2026, typ=self.typ_stavu, narok_hodin=160,
        )
        self.historie = HistoriePrislusenosti.objects.create(
            employee=self.employee, oddeleni=self.oddeleni, datum_od=date(2020, 1, 1),
        )

        # Kolega, jehož žádost schvaluje mazaný zaměstnanec — ověřuje, že
        # se schvalovatele u CIZÍ žádosti jen vynuluje (SET_NULL), místo
        # aby smazání spadlo na ProtectedError nebo smazalo žádost kolegy.
        self.kolega = _vytvor_zamestnance(
            "kolega@example.com", "0002", self.oddeleni, typ_uvazku
        )
        self.zadost_kolegy = ZadostOStav.objects.create(
            employee=self.kolega, typ=self.typ_stavu,
            datum_od=date(2026, 8, 3), datum_do=date(2026, 8, 3),
            schvalovatele=self.employee,
        )

        self.admin_user = User.objects.create_superuser(
            username="admin@example.com", email="admin@example.com", password="testpass123",
        )
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_smazani_uzivatele_kaskadove_smaze_vsechno(self):
        user_id = self.employee.user_id
        employee_id = self.employee.pk
        session_id = self.session.pk
        self.assertTrue(WorkdaySummary.objects.filter(employee_id=employee_id).exists())

        url = reverse("admin:accounts_user_delete", args=[user_id])
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)

        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(Employee.objects.filter(pk=employee_id).exists())
        self.assertFalse(WorkSession.objects.filter(pk=session_id).exists())
        self.assertFalse(WorkdaySummary.objects.filter(employee_id=employee_id).exists())
        self.assertFalse(ZustatekStavu.objects.filter(employee_id=employee_id).exists())
        self.assertFalse(HistoriePrislusenosti.objects.filter(employee_id=employee_id).exists())

        self.oddeleni.refresh_from_db()
        self.assertIsNone(self.oddeleni.vedouci)

        # Kolegova žádost přežije, jen bez schvalovatele.
        self.zadost_kolegy.refresh_from_db()
        self.assertIsNone(self.zadost_kolegy.schvalovatele)

    def test_hromadne_smazani_pres_delete_selected_akci(self):
        user_id = self.employee.user_id
        employee_id = self.employee.pk

        url = reverse("admin:accounts_user_changelist")
        response = self.client.post(url, {
            "action": "delete_selected",
            "_selected_action": [user_id],
            "post": "yes",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertFalse(Employee.objects.filter(pk=employee_id).exists())

    def test_primy_pristup_na_workdaysummary_zustava_zakazan(self):
        souhrn = WorkdaySummary.objects.get(employee=self.employee)
        url = reverse("admin:timetracking_workdaysummary_delete", args=[souhrn.pk])
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(WorkdaySummary.objects.filter(pk=souhrn.pk).exists())


class FunkceSynchronizaceTests(TestCase):
    """Issue #16 — Employee.funkce se synchronizuje s vedouci a je unikátní na jednotku."""

    def setUp(self):
        self.sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        self.odbor = Odbor.objects.create(sekce=self.sekce, nazev="Odbor", kod="O1")
        self.oddeleni_a = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddělení A", kod="OA")
        self.oddeleni_b = Oddeleni.objects.create(odbor=self.odbor, nazev="Oddělení B", kod="OB")
        self.typ_uvazku = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=8, hodiny_tyydne=40,
        )
        self.a = _vytvor_zamestnance("a@example.com", "A1", self.oddeleni_a, self.typ_uvazku)
        self.d = _vytvor_zamestnance("d@example.com", "D1", self.oddeleni_a, self.typ_uvazku)

    def test_prirazeni_funkce_nastavi_vedouciho_a_nahradi_predchoziho_drzitele(self):
        self.a.funkce = Employee.FunkceChoices.VEDOUCI_ODDELENI
        self.a.save()
        self.oddeleni_a.refresh_from_db()
        self.assertEqual(self.oddeleni_a.vedouci_id, self.a.pk)

        self.d.funkce = Employee.FunkceChoices.VEDOUCI_ODDELENI
        self.d.save()
        self.oddeleni_a.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(self.oddeleni_a.vedouci_id, self.d.pk)
        self.assertEqual(self.a.funkce, "")

    def test_presun_zamestnance_vymaze_funkci_a_stareho_vedouciho(self):
        self.a.funkce = Employee.FunkceChoices.VEDOUCI_ODDELENI
        self.a.save()

        self.a.oddeleni = self.oddeleni_b
        self.a.save(update_fields=["oddeleni"])

        self.a.refresh_from_db()
        self.oddeleni_a.refresh_from_db()
        self.assertEqual(self.a.funkce, "")
        self.assertIsNone(self.oddeleni_a.vedouci_id)

    def test_soucasna_zmena_oddeleni_a_funkce_se_neprepise(self):
        """Přesun + rovnou přiřazení nové funkce v jednom save() se nesmí ztratit."""
        self.a.funkce = Employee.FunkceChoices.VEDOUCI_ODDELENI
        self.a.save()

        self.a.oddeleni = self.oddeleni_b
        self.a.funkce = Employee.FunkceChoices.REDITEL_ODBORU
        self.a.save()

        self.a.refresh_from_db()
        self.odbor.refresh_from_db()
        self.assertEqual(self.a.funkce, Employee.FunkceChoices.REDITEL_ODBORU)
        self.assertEqual(self.odbor.vedouci_id, self.a.pk)


class FunkceScopovaneSpravaZamestnancuTests(TestCase):
    """Issue #16 — vedoucí oddělení smí spravovat jen zaměstnance vlastního oddělení."""

    def setUp(self):
        self.sekce = Sekce.objects.create(nazev="Sekce", kod="S1")
        self.odbor = Odbor.objects.create(sekce=self.sekce, nazev="Odbor", kod="O1")
        odbor = self.odbor
        self.oddeleni_it = Oddeleni.objects.create(odbor=odbor, nazev="IT", kod="IT")
        self.oddeleni_hr = Oddeleni.objects.create(odbor=odbor, nazev="HR", kod="HR")
        typ_uvazku = TypUvazku.objects.create(
            nazev="Plný úvazek", hodiny_denne=8, hodiny_tyydne=40,
        )

        self.a = _vytvor_zamestnance("vedouci-a@example.com", "A1", self.oddeleni_it, typ_uvazku)
        self.a.funkce = Employee.FunkceChoices.VEDOUCI_ODDELENI
        self.a.save()

        self.b = _vytvor_zamestnance("b@example.com", "B1", self.oddeleni_it, typ_uvazku)
        self.c = _vytvor_zamestnance("c@example.com", "C1", self.oddeleni_hr, typ_uvazku)

        self.client = Client()
        self.client.force_login(self.a.user)

    def test_vedouci_vidi_a_edituje_zamestnance_vlastniho_oddeleni(self):
        seznam = self.client.get(reverse("accounts:seznam_zamestnancu"))
        self.assertEqual(seznam.status_code, 200)
        videni = {z.pk for z in seznam.context["zamestnanci"]}
        self.assertEqual(videni, {self.a.pk, self.b.pk})

        edit = self.client.get(reverse("accounts:upravit_zamestnance", args=[self.b.pk]))
        self.assertEqual(edit.status_code, 200)

    def test_vedouci_nema_pristup_k_zamestnanci_mimo_oddeleni(self):
        edit = self.client.get(reverse("accounts:upravit_zamestnance", args=[self.c.pk]))
        self.assertEqual(edit.status_code, 404)

    def test_radovy_zamestnanec_nema_pristup_ke_sprave(self):
        client = Client()
        client.force_login(self.b.user)
        response = client.get(reverse("accounts:seznam_zamestnancu"))
        self.assertEqual(response.status_code, 302)

    def test_reditel_sekce_ma_jen_readonly_prehled(self):
        reditel = _vytvor_zamestnance(
            "reditel@example.com", "R1", self.oddeleni_it,
            self.a.typ_uvazku,
        )
        reditel.funkce = Employee.FunkceChoices.REDITEL_SEKCE
        reditel.save()
        client = Client()
        client.force_login(reditel.user)

        prehled = client.get(reverse("accounts:prehled_sekce"))
        self.assertEqual(prehled.status_code, 200)

        seznam = client.get(reverse("accounts:seznam_zamestnancu"))
        self.assertEqual(seznam.status_code, 302)

    def test_staff_s_vlastnim_zamestnaneckym_profilem_vidi_celou_sekci(self):
        """Regrese: is_staff nesmí být omezen na vlastní sekci jen proto, že má i Employee profil."""
        jina_sekce = Sekce.objects.create(nazev="Jina sekce", kod="S2")
        jiny_odbor = Odbor.objects.create(sekce=jina_sekce, nazev="Jiny odbor", kod="O2")

        staff_user = self.a.user
        staff_user.is_staff = True
        staff_user.save()
        client = Client()
        client.force_login(staff_user)

        prehled = client.get(reverse("accounts:prehled_sekce"))
        self.assertEqual(prehled.status_code, 200)
        videne_odbory = set(prehled.context["odbory"])
        self.assertIn(jiny_odbor, videne_odbory)

    def test_vedouci_oddeleni_nema_pristup_k_presunu(self):
        presun = self.client.get(reverse("accounts:presunout_zamestnance", args=[self.b.pk]))
        self.assertEqual(presun.status_code, 302)

    def test_reditel_odboru_muze_presunout_zamestnance_mezi_oddelenimi(self):
        reditel = _vytvor_zamestnance(
            "reditel-o@example.com", "RO1", self.oddeleni_it, self.a.typ_uvazku,
        )
        reditel.funkce = Employee.FunkceChoices.REDITEL_ODBORU
        reditel.save()
        client = Client()
        client.force_login(reditel.user)

        presun_get = client.get(reverse("accounts:presunout_zamestnance", args=[self.b.pk]))
        self.assertEqual(presun_get.status_code, 200)
        moznosti = {o.pk for o in presun_get.context["form"].fields["oddeleni"].queryset}
        self.assertEqual(moznosti, {self.oddeleni_it.pk, self.oddeleni_hr.pk})
