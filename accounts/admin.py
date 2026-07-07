from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, Employee, Sekce, Odbor, Oddeleni, TypUvazku, HistoriePrislusenosti
from .holidays_model import Zeme, StatniSvatek


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["email", "first_name", "last_name", "is_staff", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {"fields": []}),
    )


@admin.register(TypUvazku)
class TypUvazkuAdmin(admin.ModelAdmin):
    list_display = ["nazev", "hodiny_denne", "hodiny_tyydne", "aktivni"]
    list_editable = ["aktivni"]


@admin.register(Sekce)
class SekceAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev", "vedouci", "aktivni"]
    search_fields = ["nazev", "kod"]


@admin.register(Odbor)
class OdborAdmin(admin.ModelAdmin):
    list_display = ["kod", "nazev", "sekce", "vedouci", "aktivni"]
    list_filter = ["sekce"]
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
    list_display = ["osobni_cislo", "jmeno", "oddeleni", "typ_uvazku", "datum_nastupu", "aktivni"]
    list_filter = ["aktivni", "oddeleni__odbor__sekce", "typ_uvazku"]
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
