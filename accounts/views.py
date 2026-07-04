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
# Administrace zaměstnanců (pouze admin)
# ---------------------------------------------------------------------------

def je_admin(user):
    return user.is_staff


@login_required
@user_passes_test(je_admin)
def seznam_zamestnancu(request):
    zamestnanci = Employee.objects.select_related(
        "user", "oddeleni__odbor__sekce", "typ_uvazku"
    ).filter(aktivni=True).order_by("oddeleni", "user__last_name")

    return render(request, "accounts/seznam_zamestnancu.html", {
        "zamestnanci": zamestnanci,
    })


@login_required
@user_passes_test(je_admin)
def pridat_zamestnance(request):
    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Zaměstnanec byl přidán.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = EmployeeCreateForm()

    return render(request, "accounts/zamestnanec_form.html", {
        "form": form, "titulek": "Přidat zaměstnance"
    })


@login_required
@user_passes_test(je_admin)
def upravit_zamestnance(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == "POST":
        form = EmployeeUpdateForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, "Zaměstnanec byl upraven.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = EmployeeUpdateForm(instance=employee)

    return render(request, "accounts/zamestnanec_form.html", {
        "form": form, "titulek": f"Upravit – {employee.jmeno}"
    })


@login_required
@user_passes_test(je_admin)
def presunout_zamestnance(request, pk):
    """Admin přesune zaměstnance do jiného oddělení."""
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == "POST":
        form = PresunutiForm(request.POST, employee=employee, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"{employee.jmeno} byl/a přesunut/a.")
            return redirect("accounts:seznam_zamestnancu")
    else:
        form = PresunutiForm(employee=employee, user=request.user)

    return render(request, "accounts/presunout.html", {
        "form": form, "employee": employee
    })
