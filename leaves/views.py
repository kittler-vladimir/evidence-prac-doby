from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.utils import timezone

from .models import ZadostODovolenou, ZustatekDovolene
from .forms import ZadostODovolenoForm, ZamitnutiForm


@login_required
def moje_zadosti(request):
    """Přehled vlastních žádostí o dovolenou."""
    employee = request.user.employee
    zadosti = ZadostODovolenou.objects.filter(employee=employee).order_by("-vytvoreno")

    rok = timezone.localdate().year
    zustatky = ZustatekDovolene.objects.filter(employee=employee, rok=rok).first()

    return render(request, "leaves/moje_zadosti.html", {
        "zadosti": zadosti,
        "zustatky": zustatky,
    })


@login_required
def nova_zadost(request):
    """Zaměstnanec vytvoří novou žádost o dovolenou."""
    employee = request.user.employee

    if request.method == "POST":
        form = ZadostODovolenoForm(request.POST, employee=employee)
        if form.is_valid():
            zadost = form.save(commit=False)
            zadost.employee = employee
            zadost.save()
            messages.success(request, "Žádost byla odeslána ke schválení.")
            return redirect("leaves:moje_zadosti")
    else:
        form = ZadostODovolenoForm(employee=employee)

    return render(request, "leaves/nova_zadost.html", {"form": form})


@login_required
def ke_schvaleni(request):
    """Manažer vidí žádosti čekající na jeho schválení."""
    employee = request.user.employee
    zadosti = ZadostODovolenou.objects.filter(
        schvalovatele=employee,
        stav=ZadostODovolenou.Stav.CEKA,
    ).select_related("employee__user", "typ")

    return render(request, "leaves/ke_schvaleni.html", {"zadosti": zadosti})


@login_required
def detail_zadosti(request, pk):
    """Detail žádosti + akce schválení/zamítnutí."""
    zadost = get_object_or_404(ZadostODovolenou, pk=pk)
    employee = request.user.employee

    # Přístup: vlastní žádost, nebo schvalovatel, nebo admin
    je_schvalovatel = zadost.schvalovatele == employee
    je_vlastni = zadost.employee == employee
    if not (je_vlastni or je_schvalovatel or request.user.is_staff):
        return HttpResponseForbidden()

    zamitnutí_form = None
    if je_schvalovatel and zadost.stav == ZadostODovolenou.Stav.CEKA:
        zamitnutí_form = ZamitnutiForm()

    return render(request, "leaves/detail_zadosti.html", {
        "zadost": zadost,
        "je_schvalovatel": je_schvalovatel,
        "zamitnutí_form": zamitnutí_form,
    })


@login_required
def schvalit(request, pk):
    """Schválení žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostODovolenou, pk=pk)
    employee = request.user.employee

    if zadost.schvalovatele != employee and not request.user.is_staff:
        return HttpResponseForbidden()

    if zadost.stav != ZadostODovolenou.Stav.CEKA:
        messages.warning(request, "Žádost již byla vyřízena.")
        return redirect("leaves:ke_schvaleni")

    zadost.schval(employee)
    messages.success(request, f"Žádost {zadost.employee.jmeno} byla schválena.")
    return redirect("leaves:ke_schvaleni")


@login_required
def zamitnou(request, pk):
    """Zamítnutí žádosti."""
    if request.method != "POST":
        return redirect("leaves:ke_schvaleni")

    zadost = get_object_or_404(ZadostODovolenou, pk=pk)
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

    zadost = get_object_or_404(ZadostODovolenou, pk=pk, employee=request.user.employee)

    if zadost.stav != ZadostODovolenou.Stav.CEKA:
        messages.warning(request, "Lze stornovat pouze čekající žádost.")
        return redirect("leaves:moje_zadosti")

    zadost.stav = ZadostODovolenou.Stav.STORNOVÁNO
    zadost.save()
    messages.success(request, "Žádost byla stornována.")
    return redirect("leaves:moje_zadosti")
