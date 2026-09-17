from collections import Counter
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.shortcuts import render, redirect
from django.utils import timezone
from django.http import HttpResponse

from accounts.models import Employee, Odbor, Oddeleni, Sekce, viditelni_zamestnanci
from timetracking.models import WorkdaySummary
from .services import NEPRITOMEN, PRITOMEN, stavy_zamestnancu

DELKA_VYHLEDAVACIHO_DOTAZU = 2
LIMIT_VYSLEDKU_VYHLEDAVANI = 50


def je_admin_nebo_vedouci(user):
    return user.is_staff or hasattr(user, "employee")


def _pk_z_get(request, nazev):
    """Vrátí platné celočíselné ID z GET parametru, jinak None (chybný/chybějící vstup = 'vše')."""
    hodnota = request.GET.get(nazev, "")
    return int(hodnota) if hodnota.isdigit() else None


# Dotřídění podle ID kvůli neunikátnímu názvu Sekce/Odbor/Oddeleni — bez něj
# by se při shodném názvu dvou různých jednotek jejich zaměstnanci mohli
# proplíst a rozbít seskupování v _seskup_hierarchicky/_seskup_podle_oddeleni,
# které předpokládá, že řádky téže jednotky jsou v seznamu vždy za sebou.
SERAZENI_PODLE_HIERARCHIE = (
    "oddeleni__odbor__sekce__nazev", "oddeleni__odbor__sekce_id",
    "oddeleni__odbor__nazev", "oddeleni__odbor_id",
    "oddeleni__nazev", "oddeleni_id",
    "user__last_name", "user__first_name",
)


def _filtr_podle_hierarchie(request, zamestnanci):
    """Pro is_staff uživatele aplikuje kaskádový sekce/odbor/oddeleni GET filtr na queryset
    a vrátí (zúžený queryset, filtr-dict pro šablonu). Pro ostatní vrátí (queryset, None) —
    filtr je dostupný jen adminům, ostatní vidí svůj rozsah celý."""
    if not request.user.is_staff:
        return zamestnanci, None

    sekce_id = _pk_z_get(request, "sekce")
    odbor_id = _pk_z_get(request, "odbor")
    oddeleni_id = _pk_z_get(request, "oddeleni")

    if oddeleni_id:
        zamestnanci = zamestnanci.filter(oddeleni_id=oddeleni_id)
    elif odbor_id:
        zamestnanci = zamestnanci.filter(oddeleni__odbor_id=odbor_id)
    elif sekce_id:
        zamestnanci = zamestnanci.filter(oddeleni__odbor__sekce_id=sekce_id)

    odbor_options = Odbor.objects.filter(aktivni=True)
    if sekce_id:
        odbor_options = odbor_options.filter(sekce_id=sekce_id)
    oddeleni_options = Oddeleni.objects.filter(aktivni=True)
    if odbor_id:
        oddeleni_options = oddeleni_options.filter(odbor_id=odbor_id)
    elif sekce_id:
        oddeleni_options = oddeleni_options.filter(odbor__sekce_id=sekce_id)

    filtr = {
        "sekce_id": sekce_id,
        "odbor_id": odbor_id,
        "oddeleni_id": oddeleni_id,
        "sekce_options": Sekce.objects.filter(aktivni=True),
        "odbor_options": odbor_options,
        "oddeleni_options": oddeleni_options,
    }
    return zamestnanci, filtr


def _seskup_podle_oddeleni(radky):
    """[{'oddeleni': Oddeleni, 'radky': [...]}] v pořadí, ve kterém přišly (queryset je už seřazený)."""
    skupiny = []
    posledni_id = None
    for r in radky:
        oddeleni = r["employee"].oddeleni
        if oddeleni.pk != posledni_id:
            skupiny.append({"oddeleni": oddeleni, "radky": []})
            posledni_id = oddeleni.pk
        skupiny[-1]["radky"].append(r)
    return skupiny


def _seskup_hierarchicky(radky):
    """[{'sekce': Sekce, 'odbory': [{'odbor': Odbor, 'oddeleni_skupiny': [...]}]}] — stejný princip
    jako _seskup_podle_oddeleni, jen o dvě úrovně hlouběji."""
    sekce_skupiny = []
    posledni_sekce_id = posledni_odbor_id = posledni_oddeleni_id = None
    for r in radky:
        oddeleni = r["employee"].oddeleni
        odbor = oddeleni.odbor
        sekce = odbor.sekce

        if sekce.pk != posledni_sekce_id:
            sekce_skupiny.append({"sekce": sekce, "odbory": []})
            posledni_sekce_id = sekce.pk
            posledni_odbor_id = None

        if odbor.pk != posledni_odbor_id:
            sekce_skupiny[-1]["odbory"].append({"odbor": odbor, "oddeleni_skupiny": []})
            posledni_odbor_id = odbor.pk
            posledni_oddeleni_id = None

        aktualni_odbor = sekce_skupiny[-1]["odbory"][-1]
        if oddeleni.pk != posledni_oddeleni_id:
            aktualni_odbor["oddeleni_skupiny"].append({"oddeleni": oddeleni, "radky": []})
            posledni_oddeleni_id = oddeleni.pk

        aktualni_odbor["oddeleni_skupiny"][-1]["radky"].append(r)

    return sekce_skupiny


@login_required
def prehled_tymu(request):
    """Vedoucí vidí přehled svého týmu za aktuální měsíc, seskupený podle organizační hierarchie."""
    dnes = timezone.localdate()
    rok = int(request.GET.get("rok", dnes.year))
    mesic = int(request.GET.get("mesic", dnes.month))

    # Zaměstnanci ve správě přihlášeného uživatele
    if request.user.is_staff:
        podrizeni = Employee.objects.filter(aktivni=True)
    elif hasattr(request.user, "employee") and request.user.employee.muze_spravovat_zamestnance:
        podrizeni = request.user.employee.spravovani_zamestnanci().filter(aktivni=True)
    else:
        podrizeni = Employee.objects.none()

    podrizeni, filtr = _filtr_podle_hierarchie(request, podrizeni)
    podrizeni = podrizeni.select_related(
        "user", "typ_uvazku", "oddeleni__odbor__sekce"
    ).order_by(*SERAZENI_PODLE_HIERARCHIE)

    data = []
    for podr in podrizeni:
        souhrny = WorkdaySummary.objects.filter(
            employee=podr, datum__year=rok, datum__month=mesic
        )
        celkem = sum(s.odpracovane_minuty for s in souhrny)
        prescos = sum(s.prescos_minuty for s in souhrny)
        data.append({
            "employee": podr,
            "odpracovano_h": celkem // 60,
            "odpracovano_m": celkem % 60,
            "prescos_h": prescos // 60,
            "prescos_m": prescos % 60,
        })

    skupiny = _seskup_hierarchicky(data) if request.user.is_staff else _seskup_podle_oddeleni(data)

    return render(request, "reports/prehled_tymu.html", {
        "skupiny": skupiny, "filtr": filtr, "rok": rok, "mesic": mesic,
    })


@login_required
def export_xlsx(request):
    """Export měsíčního výkazu do Excelu (openpyxl)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from calendar import monthrange

    if not hasattr(request.user, "employee"):
        messages.info(request, "Tato stránka je dostupná jen pro zaměstnance s profilem.")
        return redirect("accounts:home")
    employee = request.user.employee
    dnes = timezone.localdate()
    rok = int(request.GET.get("rok", dnes.year))
    mesic = int(request.GET.get("mesic", dnes.month))

    souhrny = {
        s.datum: s
        for s in WorkdaySummary.objects.filter(
            employee=employee, datum__year=rok, datum__month=mesic
        )
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Výkaz {mesic:02d}/{rok}"

    # Záhlaví
    hlavicka = ["Datum", "Den", "Odpracováno", "Přesčas", "Svátek/Víkend"]
    for col, text in enumerate(hlavicka, 1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="4A90E2")

    dny_v_mesici = monthrange(rok, mesic)[1]
    from datetime import date
    nazvy_dnu = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

    for den in range(1, dny_v_mesici + 1):
        datum = date(rok, mesic, den)
        souhrn = souhrny.get(datum)
        row = den + 1

        ws.cell(row=row, column=1, value=datum.strftime("%d.%m.%Y"))
        ws.cell(row=row, column=2, value=nazvy_dnu[datum.weekday()])

        if souhrn:
            odpr = f"{souhrn.odpracovane_minuty // 60}h {souhrn.odpracovane_minuty % 60}min"
            prescos = f"{souhrn.prescos_minuty // 60}h {souhrn.prescos_minuty % 60}min"
            poznamka = []
            if souhrn.je_svatek:
                poznamka.append("Svátek")
            if souhrn.je_vikend:
                poznamka.append("Víkend")
            ws.cell(row=row, column=3, value=odpr)
            ws.cell(row=row, column=4, value=prescos)
            ws.cell(row=row, column=5, value=", ".join(poznamka))

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="vykaz_{rok}_{mesic:02d}_{employee.osobni_cislo}.xlsx"'
    )
    wb.save(response)
    return response


def _parsuj_datum(request):
    datum_str = request.GET.get("datum")
    if datum_str:
        try:
            return datetime.strptime(datum_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    return timezone.localdate()


@login_required
def prehled_pritomnosti(request):
    """
    Denní přehled přítomnosti: admin vidí vše, vedoucí oddělení vidí své
    oddělení, ostatní zaměstnanci vidí celý svůj odbor (napříč odděleními).
    """
    datum = _parsuj_datum(request)
    ma_pristup = je_admin_nebo_vedouci(request.user)
    zamestnanci = viditelni_zamestnanci(request.user)

    zamestnanci, filtr = _filtr_podle_hierarchie(request, zamestnanci)

    zamestnanci = list(
        zamestnanci.select_related("user", "oddeleni__odbor__sekce")
        .order_by(*SERAZENI_PODLE_HIERARCHIE)
    )
    stavy = stavy_zamestnancu(zamestnanci, datum)
    radky = [{"employee": zam, "stav": stavy[zam.pk]} for zam in zamestnanci]

    # Kategorie se sestavují dynamicky z toho, co se ten den skutečně
    # vyskytlo — nový TypStavu se tak v souhrnu objeví bez zásahu do kódu.
    # Pořadí se drží prvního výskytu v radky (stabilní), ne abecedně dle
    # zkratky, aby se kategorie neřadily podle náhody v pojmenování.
    pocitadlo = Counter(r["stav"].kod for r in radky)
    popisky_ostatnich = {}
    for r in radky:
        kod = r["stav"].kod
        if kod not in (PRITOMEN, NEPRITOMEN):
            popisky_ostatnich.setdefault(kod, r["stav"].popisek)
    poradi_kategorii = [
        (PRITOMEN, "Přítomen"),
        *popisky_ostatnich.items(),
        (NEPRITOMEN, "Nepřítomen"),
    ]
    pocty = [
        {"popisek": popisek, "pocet": pocitadlo[kod]}
        for kod, popisek in poradi_kategorii
        if pocitadlo[kod]
    ]

    skupiny = _seskup_hierarchicky(radky) if request.user.is_staff else _seskup_podle_oddeleni(radky)

    return render(request, "reports/prehled_pritomnosti.html", {
        "datum": datum,
        "skupiny": skupiny,
        "pocty": pocty,
        "filtr": filtr,
        "ma_pristup": ma_pristup,
    })


@login_required
def vyhledat_zamestnance(request):
    """Vyhledání zaměstnance napříč celou firmou (bez omezení na odbor)."""
    dotaz = request.GET.get("q", "").strip()
    vysledky = []
    zkraceno = False

    if len(dotaz) >= DELKA_VYHLEDAVACIHO_DOTAZU:
        zamestnanci = list(
            Employee.objects.filter(
                Q(user__first_name__icontains=dotaz) | Q(user__last_name__icontains=dotaz),
                aktivni=True,
            ).select_related("user", "oddeleni")[: LIMIT_VYSLEDKU_VYHLEDAVANI + 1]
        )
        zkraceno = len(zamestnanci) > LIMIT_VYSLEDKU_VYHLEDAVANI
        zamestnanci = zamestnanci[:LIMIT_VYSLEDKU_VYHLEDAVANI]

        stavy = stavy_zamestnancu(zamestnanci, timezone.localdate())
        vysledky = [{"employee": zam, "stav": stavy[zam.pk]} for zam in zamestnanci]

    return render(request, "reports/vyhledat_zamestnance.html", {
        "dotaz": dotaz,
        "vysledky": vysledky,
        "zkraceno": zkraceno,
        "min_delka_dotazu": DELKA_VYHLEDAVACIHO_DOTAZU,
    })


@login_required
def reports_urls(request):
    return render(request, "reports/index.html")
