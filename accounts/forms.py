from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Employee, Oddeleni, TypUvazku, HistoriePrislusenosti

User = get_user_model()


class EmployeeCreateForm(forms.Form):
    """Formulář pro přidání nového zaměstnance (User + Employee)."""
    first_name = forms.CharField(label="Jméno", max_length=150)
    last_name = forms.CharField(label="Příjmení", max_length=150)
    email = forms.EmailField(label="E-mail")
    osobni_cislo = forms.CharField(label="Osobní číslo", max_length=20)
    oddeleni = forms.ModelChoiceField(
        label="Oddělení",
        queryset=Oddeleni.objects.filter(aktivni=True),
    )
    typ_uvazku = forms.ModelChoiceField(
        label="Typ úvazku",
        queryset=TypUvazku.objects.filter(aktivni=True),
    )
    datum_nastupu = forms.DateField(
        label="Datum nástupu",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    telefon = forms.CharField(label="Telefon", max_length=20, required=False)

    def __init__(self, *args, oddeleni_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if oddeleni_queryset is not None:
            self.fields["oddeleni"].queryset = oddeleni_queryset

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Uživatel s tímto e-mailem již existuje.")
        return email

    def clean_osobni_cislo(self):
        cislo = self.cleaned_data["osobni_cislo"]
        if Employee.objects.filter(osobni_cislo=cislo).exists():
            raise forms.ValidationError("Toto osobní číslo již existuje.")
        return cislo

    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            username=data["email"],
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            password=User.objects.make_random_password(),
        )
        employee = Employee.objects.create(
            user=user,
            osobni_cislo=data["osobni_cislo"],
            oddeleni=data["oddeleni"],
            typ_uvazku=data["typ_uvazku"],
            datum_nastupu=data["datum_nastupu"],
            telefon=data.get("telefon", ""),
        )
        # TODO: odeslat e-mail s odkazem na nastavení hesla
        return employee


class EmployeeUpdateForm(forms.ModelForm):
    first_name = forms.CharField(label="Jméno", max_length=150)
    last_name = forms.CharField(label="Příjmení", max_length=150)
    telefon = forms.CharField(label="Telefon", max_length=20, required=False)

    class Meta:
        model = Employee
        fields = ["osobni_cislo", "typ_uvazku", "funkce", "datum_nastupu", "datum_ukonceni", "aktivni"]
        widgets = {
            "datum_nastupu": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "datum_ukonceni": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, muze_menit_funkci=True, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["telefon"].initial = self.instance.telefon
        if not muze_menit_funkci:
            del self.fields["funkce"]

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.user.first_name = self.cleaned_data["first_name"]
        employee.user.last_name = self.cleaned_data["last_name"]
        employee.telefon = self.cleaned_data["telefon"]
        if commit:
            employee.user.save()
            employee.save()
        return employee


class ZastupceForm(forms.ModelForm):
    """Formulář, kterým si držitel funkce sám nastaví svého zástupce."""

    class Meta:
        model = Employee
        fields = ["zastupce", "rucne_nepritomen"]

    def __init__(self, *args, principal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.principal = principal or self.instance
        self.fields["zastupce"].queryset = self.principal.moznosti_zastupce()
        self.fields["zastupce"].required = False
        self.fields["zastupce"].label = "Zástupce"
        self.fields["zastupce"].empty_label = "— bez zástupce —"
        self.fields["rucne_nepritomen"].label = (
            "Jsem aktuálně nepřítomen/á (předat schvalování zástupci)"
        )


class PresunutiForm(forms.Form):
    """Formulář pro přesun zaměstnance do jiného oddělení."""
    oddeleni = forms.ModelChoiceField(
        label="Nové oddělení",
        queryset=Oddeleni.objects.filter(aktivni=True),
    )
    datum_od = forms.DateField(
        label="Platné od",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        initial=timezone.localdate,
    )
    poznamka = forms.CharField(label="Poznámka", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, employee=None, user=None, oddeleni_queryset=None, **kwargs):
        self.employee = employee
        self.user = user
        super().__init__(*args, **kwargs)
        if oddeleni_queryset is not None:
            self.fields["oddeleni"].queryset = oddeleni_queryset

    def save(self):
        # Uzavřít stávající historii
        HistoriePrislusenosti.objects.filter(
            employee=self.employee, datum_do__isnull=True
        ).update(datum_do=self.cleaned_data["datum_od"])

        # Zapsat nové zařazení
        HistoriePrislusenosti.objects.create(
            employee=self.employee,
            oddeleni=self.cleaned_data["oddeleni"],
            datum_od=self.cleaned_data["datum_od"],
            poznamka=self.cleaned_data.get("poznamka", ""),
            zmenil=self.user,
        )

        self.employee.oddeleni = self.cleaned_data["oddeleni"]
        self.employee.save(update_fields=["oddeleni"])
        return self.employee
