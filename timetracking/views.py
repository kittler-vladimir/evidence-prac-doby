from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.http import HttpResponseForbidden

from .models import WorkSession, WorkdaySummary
from .forms import WorkSessionOpravitForm, WorkSessionRucneForm


@login_required
def dashboard(request):
    """Hlavní stránka — aktuální stav + dnešní souhrn."""
    employee = request.user.employee
    dnes = timezone.localdate()

    aktivni_session = WorkSession.objects.filter(
        employee=employee, konec__isnull=True
    ).first()

    souhrn = WorkdaySummary.objects.filter(employee=employee, datum=dnes).first()

    posledni_tydny = WorkdaySummary.objects.filter(employee=employee).order_by("-datum")[:14]

    context = {
        "employee": employee,
        "aktivni_session": aktivni_session,
        "souhrn": souhrn,
        "posledni_tydny": posledni_tydny,
        "dnes": dnes,
    }
    return render(request, "timetracking/dashboard.html", context)


@login_required
def clock_in(request):
    """Zahájí nový pracovní blok."""
    if request.method != "POST":
        return redirect("timetracking:dashboard")

    employee = request.user.employee

    # Kontrola, zda již není aktivní session
    if WorkSession.objects.filter(employee=employee, konec__isnull=True).exists():
        messages.warning(request, "Již jste přihlášen/a. Nejprve se odhlaste.")
        return redirect("timetracking:dashboard")

    WorkSession.objects.create(
        employee=employee,
        zacatek=timezone.now(),
        zdroj=WorkSession.Zdroj.PRICHOD,
    )
    messages.success(request, "Příchod zaznamenán.")
    return redirect("timetracking:dashboard")


@login_required
def clock_out(request):
    """Ukončí aktivní pracovní blok."""
    if request.method != "POST":
        return redirect("timetracking:dashboard")

    employee = request.user.employee
    session = WorkSession.objects.filter(
        employee=employee, konec__isnull=True
    ).first()

    if not session:
        messages.warning(request, "Nemáte aktivní příchod.")
        return redirect("timetracking:dashboard")

    session.konec = timezone.now()
    session.save()
    messages.success(request, "Odchod zaznamenán.")
    return redirect("timetracking:dashboard")


@login_required
def prehled_mesice(request):
    """Měsíční přehled odpracované doby."""
    employee = request.user.employee
    dnes = timezone.localdate()

    rok = int(request.GET.get("rok", dnes.year))
    mesic = int(request.GET.get("mesic", dnes.month))

    souhrny = WorkdaySummary.objects.filter(
        employee=employee,
        datum__year=rok,
        datum__month=mesic,
    ).order_by("datum")

    celkem_odpr = sum(s.odpracovane_minuty for s in souhrny)
    celkem_prescos = sum(s.prescos_minuty for s in souhrny)

    context = {
        "souhrny": souhrny,
        "rok": rok,
        "mesic": mesic,
        "celkem_odpr": celkem_odpr,
        "celkem_prescos": celkem_prescos,
    }
    return render(request, "timetracking/prehled_mesice.html", context)


@login_required
def opravit_session(request, pk):
    """Zaměstnanec doplní zapomenutý odchod nebo opraví časy."""
    session = get_object_or_404(WorkSession, pk=pk)

    # Zaměstnanec může opravovat jen své záznamy; manager/admin vše
    if session.employee.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden()

    if request.method == "POST":
        form = WorkSessionOpravitForm(request.POST, instance=session)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.opraveno = True
            obj.zdroj = WorkSession.Zdroj.RUCNI
            obj.save()
            messages.success(request, "Záznam byl opraven.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkSessionOpravitForm(instance=session)

    return render(request, "timetracking/opravit_session.html", {"form": form, "session": session})


@login_required
def pridat_session(request):
    """Ruční přidání pracovního bloku (zpětně)."""
    employee = request.user.employee

    if request.method == "POST":
        form = WorkSessionRucneForm(request.POST, employee=employee)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.employee = employee
            obj.zdroj = WorkSession.Zdroj.RUCNI
            obj.opraveno = True
            obj.save()
            messages.success(request, "Záznam byl přidán.")
            return redirect("timetracking:dashboard")
    else:
        form = WorkSessionRucneForm(employee=employee)

    return render(request, "timetracking/pridat_session.html", {"form": form})
