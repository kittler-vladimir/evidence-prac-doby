from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Employee, Sekce, Odbor, Oddeleni, TypUvazku, CasovyBlokUvazku
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
