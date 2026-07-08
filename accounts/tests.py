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
