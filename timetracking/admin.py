from django.contrib import admin
from .models import WorkSession, WorkdaySummary


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = ["employee", "zacatek", "konec", "trvani_minut", "zdroj", "opraveno"]
    list_filter = ["zdroj", "opraveno", "employee__oddeleni"]
    search_fields = ["employee__user__last_name", "employee__osobni_cislo"]
    date_hierarchy = "zacatek"
    readonly_fields = ["vytvoreno", "upraveno"]


@admin.register(WorkdaySummary)
class WorkdaySummaryAdmin(admin.ModelAdmin):
    list_display = ["employee", "datum", "odpracovane_minuty", "prescos_minuty", "je_svatek"]
    list_filter = ["je_svatek", "je_vikend"]
    date_hierarchy = "datum"
    search_fields = ["employee__user__last_name"]
    readonly_fields = [
        "hrube_minuty", "prestavka_minuty", "odpracovane_minuty", "prescos_minuty"
    ]
