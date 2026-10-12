from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.utils import timezone

from .models import TypStavu, ZadostOStav, ZadostOZruseni, ZustatekStavu
from .forms import SamoschvaleniForm, ZadostOStavForm, ZamitnutiForm, ZruseniForm


@login_required
def moje_zadosti(request):
    """Přehled vlastních žádostí a záznamů stavu."""
    if not hasattr(request.user, "employee"):
        messages.info(request, "Tato stránka je dostupná jen pro zaměstnance s profilem.")
        return redirect("accounts:home")
    employee = request.user.employee
    zadosti = ZadostOStav.objects.filter(
        employee=employee
    ).select_related("typ").order_by("-vytvoreno")

    rok = timezone.localdate().year
    dnes = timezone.localdate()
    zustatky = list(
        ZustatekStavu.objects.filter(employee=employee, rok=rok).select_related("typ")
    )

    # Zobrazit i virtuální (dosud nezaložený) zůstatek pro globálně nárokované
    # typy stavu (např. indispoziční volno, dovolená), na které má zaměstnanec
    # nárok už teď, i když zatím nepodal žádnou žádost.
    existujici_typy = {z.typ_id for z in zustatky}
    globalne_narokovane = TypStavu.objects.filter(aktivni=True).filter(
        models.Q(je_indispozicni_volno=True) | models.Q(je_dovolena=True)
    )
    for typ in globalne_narokovane:
        if typ.pk not in existujici_typy:
            zustatky.append(ZustatekStavu(
                employee=employee, rok=rok, typ=typ,
                narok_hodin=typ.vychozi_narok(dnes), cerpano_hodin=0,
            ))

    return render(request, "leaves/moje_zadosti.html", {
        "zadosti": zadosti,
        "zustatky": zustatky,
    })


@login_required
def nova_zadost(request):
    """Zaměstnanec podá novou žádost o stav, nebo si stav rovnou zaznamená."""
    employee = request.user.employee

    if request.method == "POST":
        form = ZadostOStavForm(request.POST, employee=employee)
        if form.is_valid():
            zadost = form.save(commit=False)
            zadost.employee = employee
            zadost.save()
            if zadost.typ.vyzaduje_schvaleni:
                messages.success(request, "Žádost byla odeslána ke schválení.")
            else:
                messages.success(request, "Záznam byl uložen.")
            return redirect("leaves:moje_zadosti")
    else:
        form = ZadostOStavForm(employee=employee)

    return render(request, "leaves/nova_zadost.html", {"form": form})


@login_required
def ke_schvaleni(request):
    """Manažer vidí žádosti čekající na jeho schválení; admin (is_staff) vidí a schvaluje všechny."""
    zadosti = ZadostOStav.objects.filter(
        stav=ZadostOStav.Stav.CEKA,
        typ__vyzaduje_schvaleni=True,
    ).select_related("employee__user", "typ")

    zruseni = ZadostOZruseni.objects.filter(
        stav=ZadostOZruseni.Stav.CEKA,
    ).select_related("zadost__employee__user", "zadost__typ")

    if not request.user.is_staff:
        zadosti = zadosti.filter(schvalovatele=request.user.employee)
        zruseni = zruseni.filter(schvalovatel=request.user.employee)

    return render(request, "leaves/ke_schvaleni.html", {
        "zadosti": zadosti,
        "zruseni": zruseni,
    })


@login_required
def detail_zadosti(request, pk):
    """Detail žádosti + akce schválení/zamítnutí."""
    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = getattr(request.user, "employee", None)

    # Přístup: vlastní žádost, nebo schvalovatel, nebo admin
    je_schvalovatel = zadost.schvalovatele == employee
    je_vlastni = zadost.employee == employee
    if not (je_vlastni or je_schvalovatel or request.user.is_staff):
        return HttpResponseForbidden()

    zamitnutí_form = None
    if je_schvalovatel and zadost.stav == ZadostOStav.Stav.CEKA:
        zamitnutí_form = ZamitnutiForm()

    samoschvaleni_form = None
    if zadost.muze_schvalit_sam(employee):
        samoschvaleni_form = SamoschvaleniForm()

    zustatek = None
    if zadost.typ.odecita_ze_zustatku:
        rok = zadost.datum_od.year
        zustatek = ZustatekStavu.objects.filter(
            employee=zadost.employee, rok=rok, typ=zadost.typ
        ).first()
        if not zustatek:
            zustatek = ZustatekStavu(
                employee=zadost.employee, rok=rok, typ=zadost.typ,
                narok_hodin=zadost.typ.vychozi_narok(zadost.datum_od), cerpano_hodin=0,
            )

    # Zrušení schválené žádosti (#100, #103) — nabídka jen vlastníkovi, i u už proběhlé
    # žádosti, pokud nečeká jiná žádost o zrušení.
    cekajici_zruseni = zadost.cekajici_zruseni() if je_vlastni else None
    muze_zrusit = bool(
        je_vlastni
        and zadost.stav == ZadostOStav.Stav.SCHVALENO
        and not cekajici_zruseni
    )
    zruseni_samoschvaleni_form = None
    if cekajici_zruseni and cekajici_zruseni.muze_schvalit_sam(employee):
        zruseni_samoschvaleni_form = SamoschvaleniForm()

    return render(request, "leaves/detail_zadosti.html", {
        "zadost": zadost,
        "je_schvalovatel": je_schvalovatel,
        "zamitnutí_form": zamitnutí_form,
        "samoschvaleni_form": samoschvaleni_form,
        "zustatek": zustatek,
        "muze_zrusit": muze_zrusit,
        "cekajici_zruseni": cekajici_zruseni,
        "zruseni_samoschvaleni_form": zruseni_samoschvaleni_form,
        "dnes": timezone.localdate(),
    })


@login_required
def schvalit(request, pk):
    """Schválení žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = getattr(request.user, "employee", None)

    if zadost.schvalovatele != employee and not request.user.is_staff:
        return HttpResponseForbidden()

    if zadost.stav != ZadostOStav.Stav.CEKA:
        messages.warning(request, "Žádost již byla vyřízena.")
        return redirect("leaves:ke_schvaleni")

    try:
        zadost.schval(employee)
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("leaves:ke_schvaleni")

    messages.success(request, f"Žádost {zadost.employee.jmeno} byla schválena.")
    return redirect("leaves:ke_schvaleni")


@login_required
def schvalit_sam(request, pk):
    """Schvalovatel ve výjimečném případě schválí vlastní čekající žádost (#90) — povinný
    důvod, žádost se označí jako schválená vlastní osobou."""
    if request.method != "POST":
        return redirect("leaves:detail_zadosti", pk=pk)

    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = getattr(request.user, "employee", None)

    if not (employee and zadost.employee_id == employee.pk and employee.schvaluje_zadosti):
        return HttpResponseForbidden()

    if zadost.stav != ZadostOStav.Stav.CEKA:
        messages.warning(request, "Žádost již byla vyřízena.")
        return redirect("leaves:detail_zadosti", pk=pk)

    if not zadost.muze_schvalit_sam(employee):
        return HttpResponseForbidden()

    form = SamoschvaleniForm(request.POST)
    if not form.is_valid():
        messages.error(request, "; ".join(form.errors["duvod"]))
        return redirect("leaves:detail_zadosti", pk=pk)

    try:
        zadost.schval(employee, samoschvaleno=True, duvod=form.cleaned_data["duvod"])
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("leaves:detail_zadosti", pk=pk)

    messages.success(request, "Žádost byla schválena vlastní osobou.")
    return redirect("leaves:detail_zadosti", pk=pk)


@login_required
def zamitnou(request, pk):
    """Zamítnutí žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = getattr(request.user, "employee", None)

    if zadost.schvalovatele != employee and not request.user.is_staff:
        return HttpResponseForbidden()

    form = ZamitnutiForm(request.POST)
    if form.is_valid():
        zadost.zamitni(employee, poznamka=form.cleaned_data["poznamka"])
        messages.success(request, f"Žádost {zadost.employee.jmeno} byla zamítnuta.")
    return redirect("leaves:ke_schvaleni")


@login_required
def stornovat(request, pk):
    """Zaměstnanec stornuje vlastní čekající žádost."""
    if request.method != "POST":
        return redirect("leaves:moje_zadosti")

    zadost = get_object_or_404(ZadostOStav, pk=pk, employee=getattr(request.user, "employee", None))

    if zadost.stav != ZadostOStav.Stav.CEKA:
        messages.warning(request, "Lze stornovat pouze čekající žádost.")
        return redirect("leaves:moje_zadosti")

    zadost.stav = ZadostOStav.Stav.STORNOVÁNO
    zadost.save()
    messages.success(request, "Žádost byla stornována.")
    return redirect("leaves:moje_zadosti")


def zprava_o_zruseni(vysledek):
    """Zpráva po zrušení schválené žádosti (#100): `vysledek` je vytvořená žádost o zrušení
    (typ se schvalováním), nebo None, když se žádost zrušila hned."""
    if vysledek is None:
        return "Nepřítomnost byla zrušena."
    schvalovatel = vysledek.schvalovatel.jmeno if vysledek.schvalovatel else "administrátor"
    return f"Žádost o zrušení byla odeslána ke schválení ({schvalovatel})."


@login_required
def zrusit(request, pk):
    """Zaměstnanec ruší svou schválenou žádost — celou, nebo jen dnešek (#100). Typ bez
    schvalování se zruší hned, typ se schvalováním jde jako žádost o zrušení."""
    if request.method != "POST":
        return redirect("leaves:detail_zadosti", pk=pk)

    zadost = get_object_or_404(ZadostOStav, pk=pk, employee=getattr(request.user, "employee", None))
    form = ZruseniForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Neplatný rozsah zrušení.")
        return redirect("leaves:detail_zadosti", pk=pk)

    try:
        od, do = zadost.rozsah_zruseni(form.cleaned_data["rozsah"])
        vysledek = zadost.zrus_nepritomnost(od, do, poznamka=form.cleaned_data["poznamka"])
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("leaves:detail_zadosti", pk=pk)

    messages.success(request, zprava_o_zruseni(vysledek))
    return redirect("leaves:moje_zadosti")


def _zruseni_ke_zpracovani(request, pk):
    """Žádost o zrušení pro schvalovatele (nebo admina); None + redirect při neplatném stavu."""
    zruseni = get_object_or_404(ZadostOZruseni, pk=pk)
    employee = getattr(request.user, "employee", None)
    if not request.user.is_staff and (employee is None or zruseni.schvalovatel != employee):
        return None, HttpResponseForbidden()
    if zruseni.stav != ZadostOZruseni.Stav.CEKA:
        messages.warning(request, "Žádost o zrušení již byla vyřízena.")
        return None, redirect("leaves:ke_schvaleni")
    return zruseni, None


@login_required
def schvalit_zruseni(request, pk):
    """Schválení žádosti o zrušení — provede zrušení na původní žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")
    zruseni, odpoved = _zruseni_ke_zpracovani(request, pk)
    if odpoved:
        return odpoved
    try:
        zruseni.schval(getattr(request.user, "employee", None))
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("leaves:ke_schvaleni")
    messages.success(request, f"Zrušení žádosti {zruseni.employee.jmeno} bylo schváleno.")
    return redirect("leaves:ke_schvaleni")


@login_required
def zamitnout_zruseni(request, pk):
    """Zamítnutí žádosti o zrušení — původní žádost zůstane schválená."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")
    zruseni, odpoved = _zruseni_ke_zpracovani(request, pk)
    if odpoved:
        return odpoved
    form = ZamitnutiForm(request.POST)
    if form.is_valid():
        zruseni.zamitni(
            getattr(request.user, "employee", None), poznamka=form.cleaned_data["poznamka"],
        )
        messages.success(request, f"Zrušení žádosti {zruseni.employee.jmeno} bylo zamítnuto.")
    return redirect("leaves:ke_schvaleni")


@login_required
def schvalit_zruseni_sam(request, pk):
    """Schvalovatel ve výjimečném případě schválí zrušení vlastní žádosti (jako #90) —
    povinný důvod."""
    zruseni = get_object_or_404(ZadostOZruseni, pk=pk)
    detail = redirect("leaves:detail_zadosti", pk=zruseni.zadost_id)
    if request.method != "POST":
        return detail

    employee = getattr(request.user, "employee", None)
    if not zruseni.muze_schvalit_sam(employee):
        return HttpResponseForbidden()

    form = SamoschvaleniForm(request.POST)
    if not form.is_valid():
        messages.error(request, "; ".join(form.errors["duvod"]))
        return detail
    try:
        zruseni.schval(employee, samoschvaleno=True, duvod=form.cleaned_data["duvod"])
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return detail
    messages.success(request, "Zrušení bylo schváleno vlastní osobou.")
    return detail
