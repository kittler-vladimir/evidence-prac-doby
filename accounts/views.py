from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse_lazy

from .models import Employee, Oddeleni, Odbor, Sekce, TypUvazku
from .forms import EmployeeCreateForm, EmployeeUpdateForm, PresunutiForm


# ---------------------------------------------------------------------------
# Autentizace
# ---------------------------------------------------------------------------

class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"


class LogoutView(auth_views.LogoutView):
    pass


# ---------------------------------------------------------------------------
# Domovská stránka (menu)
# ---------------------------------------------------------------------------

@login_required
def home(request):
    return render(request, "accounts/home.html")


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

@login_required
def profil(request):
    return render(request, "accounts/profil.html", {"employee": request.user.employee})


# ---------------------------------------------------------------------------
# Administrace zaměstnanců (admin, nebo zaměstnanec s funkcí ve své jednotce)
# ---------------------------------------------------------------------------

def je_admin_nebo_spravce(user):
    return user.is_staff or (
        hasattr(user, "employee") and user.employee.muze_spravovat_zamestnance
    )


def je_admin_nebo_presouvatel(user):
    return user.is_staff or (
        hasattr(user, "employee") and user.employee.muze_presouvat_zamestnance
    )


def je_admin_nebo_reditel_sekce(user):
    return user.is_staff or (
        hasattr(user, "employee") and user.employee.je_reditel_sekce
    )


def _rozsah_zamestnancu(user):
    """Queryset zaměstnanců, které smí uživatel spravovat (admin = vše)."""
    if user.is_staff:
        return Employee.objects.filter(aktivni=True)
    if not hasattr(user, "employee"):
        return Employee.objects.none()
    return user.employee.spravovani_zamestnanci().filter(aktivni=True)


def _rozsah_oddeleni(user):
    """Queryset oddělení, mezi kterými smí uživatel zakládat/přesouvat zaměstnance."""
    if user.is_staff:
        return Oddeleni.objects.filter(aktivni=True)
    if not hasattr(user, "employee"):
        return Oddeleni.objects.none()
    return user.employee.spravovana_oddeleni().filter(aktivni=True)


@login_required
@user_passes_test(je_admin_nebo_spravce)
def seznam_zamestnancu(request):
    zamestnanci = _rozsah_zamestnancu(request.user).select_related(
        "user", "oddeleni__odbor__sekce", "typ_uvazku"
    ).order_by("oddeleni", "user__last_name")

    return render(request, "accounts/seznam_zamestnancu.html", {
        "zamestnanci": zamestnanci,
    })


@login_required
@user_passes_test(je_admin_nebo_spravce)
def pridat_zamestnance(request):
    oddeleni_queryset = _rozsah_oddeleni(request.user)

    if request.method == "POST":
        form = EmployeeCreateForm(request.POST, oddeleni_queryset=oddeleni_queryset)
        if form.is_valid():
            form.save()
            messages.success(request, "Zaměstnanec byl přidán.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = EmployeeCreateForm(oddeleni_queryset=oddeleni_queryset)

    return render(request, "accounts/zamestnanec_form.html", {
        "form": form, "titulek": "Přidat zaměstnance"
    })


@login_required
@user_passes_test(je_admin_nebo_spravce)
def upravit_zamestnance(request, pk):
    employee = get_object_or_404(_rozsah_zamestnancu(request.user), pk=pk)
    muze_menit_funkci = request.user.is_staff or (
        hasattr(request.user, "employee") and request.user.employee.muze_menit_funkci
    )

    if request.method == "POST":
        form = EmployeeUpdateForm(
            request.POST, instance=employee, muze_menit_funkci=muze_menit_funkci
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Zaměstnanec byl upraven.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = EmployeeUpdateForm(instance=employee, muze_menit_funkci=muze_menit_funkci)

    return render(request, "accounts/zamestnanec_form.html", {
        "form": form, "titulek": f"Upravit – {employee.jmeno}"
    })


@login_required
@user_passes_test(je_admin_nebo_presouvatel)
def presunout_zamestnance(request, pk):
    """Přesun zaměstnance do jiného oddělení (admin, nebo správce s víc než jedním oddělením)."""
    employee = get_object_or_404(_rozsah_zamestnancu(request.user), pk=pk)
    oddeleni_queryset = _rozsah_oddeleni(request.user)

    if request.method == "POST":
        form = PresunutiForm(
            request.POST, employee=employee, user=request.user,
            oddeleni_queryset=oddeleni_queryset,
        )
        if form.is_valid():
            form.save()
            messages.success(request, f"{employee.jmeno} byl/a přesunut/a.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = PresunutiForm(
            employee=employee, user=request.user, oddeleni_queryset=oddeleni_queryset
        )

    return render(request, "accounts/presunout.html", {
        "form": form, "employee": employee
    })


@login_required
@user_passes_test(je_admin_nebo_reditel_sekce)
def prehled_sekce(request):
    """Read-only přehled vedení sekce pro Ředitele sekce (odbory + jejich vedení)."""
    if request.user.is_staff:
        odbory = Odbor.objects.filter(aktivni=True)
    else:
        sekce = request.user.employee.oddeleni.odbor.sekce
        odbory = Odbor.objects.filter(sekce=sekce, aktivni=True)

    odbory = odbory.select_related("vedouci__user", "sekce").prefetch_related(
        "oddeleni__vedouci__user"
    ).order_by("nazev")

    return render(request, "accounts/prehled_sekce.html", {"odbory": odbory})
