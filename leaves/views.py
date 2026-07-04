from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.utils import timezone

from .models import TypStavu, ZadostOStav, ZustatekStavu
from .forms import ZadostOStavForm, ZamitnutiForm


@login_required
def moje_zadosti(request):
    """Přehled vlastních žádostí a záznamů stavu."""
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
    # typy stavu (např. indispoziční volno), na které má zaměstnanec nárok
    # už teď, i když zatím nepodal žádnou žádost.
    existujici_typy = {z.typ_id for z in zustatky}
    for typ in TypStavu.objects.filter(je_indispozicni_volno=True, aktivni=True):
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
    """Manažer vidí žádosti čekající na jeho schválení."""
    employee = request.user.employee
    zadosti = ZadostOStav.objects.filter(
        schvalovatele=employee,
        stav=ZadostOStav.Stav.CEKA,
        typ__vyzaduje_schvaleni=True,
    ).select_related("employee__user", "typ")

    return render(request, "leaves/ke_schvaleni.html", {"zadosti": zadosti})


@login_required
def detail_zadosti(request, pk):
    """Detail žádosti + akce schválení/zamítnutí."""
    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = request.user.employee

    # Přístup: vlastní žádost, nebo schvalovatel, nebo admin
    je_schvalovatel = zadost.schvalovatele == employee
    je_vlastni = zadost.employee == employee
    if not (je_vlastni or je_schvalovatel or request.user.is_staff):
        return HttpResponseForbidden()

    zamitnutí_form = None
    if je_schvalovatel and zadost.stav == ZadostOStav.Stav.CEKA:
        zamitnutí_form = ZamitnutiForm()

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

    return render(request, "leaves/detail_zadosti.html", {
        "zadost": zadost,
        "je_schvalovatel": je_schvalovatel,
        "zamitnutí_form": zamitnutí_form,
        "zustatek": zustatek,
    })


@login_required
def schvalit(request, pk):
    """Schválení žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = request.user.employee

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
def zamitnou(request, pk):
    """Zamítnutí žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostOStav, pk=pk)
    employee = request.user.employee

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

    zadost = get_object_or_404(ZadostOStav, pk=pk, employee=request.user.employee)

    if zadost.stav != ZadostOStav.Stav.CEKA:
        messages.warning(request, "Lze stornovat pouze čekající žádost.")
        return redirect("leaves:moje_zadosti")

    zadost.stav = ZadostOStav.Stav.STORNOVÁNO
    zadost.save()
    messages.success(request, "Žádost byla stornována.")
    return redirect("leaves:moje_zadosti")
