from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    User, Employee, Sekce, Odbor, Oddeleni, TypUvazku, CasovyBlokUvazku,
    HistoriePrislusenosti,
)
from .holidays_model import Zeme, StatniSvatek


class EmployeeInline(admin.StackedInline):
    """
    Umožňuje založit zaměstnance rovnou na stránce uživatele (jedním
    formulářem), místo dvoukrokového postupu „nejdřív uživatel, pak
    zaměstnanec". Mazání zde vypnuto — smazání zaměstnance přes tento
    inline by kaskádově smazalo i jeho docházku a žádosti o stav; k tomu
    slouží samostatná stránka Zaměstnanci.
    """

    model = Employee
    can_delete = False
    max_num = 1
    verbose_name_plural = "zaměstnanec"
    fields = [
        "osobni_cislo", "oddeleni", "typ_uvazku",
        "datum_nastupu", "datum_ukonceni", "telefon", "aktivni",
    ]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "first_name", "last_name", "is_staff", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {"fields": []}),
    )
    inlines = [EmployeeInline]


class CasovyBlokUvazkuFormSet(BaseInlineFormSet):
    """Validuje počet bloků vůči druhu pracovní doby rodičovského typu úvazku."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        aktivni_bloky = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
        ]
        if (
            self.instance.druh_pracovni_doby == TypUvazku.DruhPracovniDoby.PRUZNA
            and len(aktivni_bloky) > 1
        ):
            raise ValidationError(
                "Pružná pracovní doba smí mít jen jeden časový blok (jádrovou dobu)."
            )


class CasovyBlokUvazkuInline(admin.TabularInline):
    model = CasovyBlokUvazku
    formset = CasovyBlokUvazkuFormSet
    extra = 1


@admin.register(TypUvazku)
class TypUvazkuAdmin(admin.ModelAdmin):
    list_display = ["nazev", "hodiny_denne", "hodiny_tyydne", "druh_pracovni_doby", "aktivni"]
    list_filter = ["druh_pracovni_doby"]
    list_editable = ["aktivni"]
    inlines = [CasovyBlokUvazkuInline]


@admin.register(Sekce)
class SekceAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev", "vedouci", "aktivni"]
    search_fields = ["nazev", "kod"]


@admin.register(Odbor)
class OdborAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev", "sekce", "vedouci", "zamestnanci_vidi_cely_odbor", "aktivni"]
    list_filter = ["sekce"]
    list_editable = ["zamestnanci_vidi_cely_odbor"]
    search_fields = ["nazev", "kod"]


@admin.register(Oddeleni)
class OddeleniAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev", "odbor", "vedouci", "aktivni"]
    list_filter = ["odbor__sekce", "odbor"]
    search_fields = ["nazev", "kod"]


class HistorieInline(admin.TabularInline):
    model = HistoriePrislusenosti
    extra = 0
    readonly_fields = ["zmenil"]


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["osobni_cislo", "jmeno", "oddeleni", "funkce", "typ_uvazku", "datum_nastupu", "aktivni"]
    list_filter = ["aktivni", "funkce", "oddeleni__odbor__sekce", "typ_uvazku"]
    search_fields = ["osobni_cislo", "user__first_name", "user__last_name", "user__email"]
    inlines = [HistorieInline]
    raw_id_fields = ["user"]

    def save_formset(self, request, form, formset, change):
        # "zmenil" je readonly (nelze ho zadat ve formuláři), ale u nově
        # založené historie ho musíme dosadit sami — jinak zůstane prázdné,
        # na rozdíl od dedikovaného formuláře v accounts/forms.py.
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, HistoriePrislusenosti) and instance.pk is None:
                instance.zmenil = request.user
            instance.save()
        formset.save_m2m()


@admin.register(Zeme)
class ZemeAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev"]


@admin.register(StatniSvatek)
class StatniSvatekAdmin(admin.ModelAdmin):
    list_display = ["datum", "nazev", "zeme", "firemni"]
    list_filter = ["zeme", "firemni"]
    date_hierarchy = "datum"
    list_editable = ["nazev", "firemni"]
    ordering = ["datum"]
