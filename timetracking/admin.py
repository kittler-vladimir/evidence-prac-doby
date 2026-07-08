from django.contrib import admin
from .models import WorkSession, WorkdaySummary, TypPohybu, Pohyb


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = ["employee", "zacatek", "konec", "trvani_minut", "zdroj", "opraveno"]
    list_filter = ["zdroj", "opraveno", "employee__oddeleni"]
    search_fields = ["employee__user__last_name", "employee__osobni_cislo"]
    date_hierarchy = "zacatek"
    readonly_fields = ["vytvoreno", "upraveno"]


@admin.register(TypPohybu)
class TypPohybuAdmin(admin.ModelAdmin):
    list_display = [
        "zkratka",
        "nazev",
        "zapocitava_se_do_pracovni_doby",
        "zobrazuje_se_na_pracovisti",
        "zapocitava_se_u_pruzne_pracovni_doby",
        "aktivni",
    ]
    list_editable = ["aktivni"]


@admin.register(Pohyb)
class PohybAdmin(admin.ModelAdmin):
    list_display = ["employee", "typ", "zacatek", "konec", "trvani_minut"]
    list_filter = ["typ"]
    search_fields = ["work_session__employee__user__last_name", "work_session__employee__osobni_cislo"]
    date_hierarchy = "zacatek"
    readonly_fields = ["vytvoreno", "upraveno"]

    @admin.display(description="zaměstnanec")
    def employee(self, obj):
        return obj.employee


@admin.register(WorkdaySummary)
class WorkdaySummaryAdmin(admin.ModelAdmin):
    """
    WorkdaySummary se nikdy nezapisuje ručně — je to odvozený souhrn
    přepočítaný signálem z WorkSession (viz WorkdaySummary.prepocitej()).
    Admin proto slouží jen k náhledu, ne k zápisu; oprava se dělá na
    WorkSession, odkud se souhrn přepočítá znovu.
    """

    list_display = ["employee", "datum", "odpracovane_minuty", "prescos_minuty", "je_svatek"]
    list_filter = ["je_svatek", "je_vikend"]
    date_hierarchy = "datum"
    search_fields = ["employee__user__last_name"]
    readonly_fields = [
        "employee", "datum", "hrube_minuty", "prestavka_minuty", "pohyby_minuty",
        "odpracovane_minuty", "prescos_minuty", "je_svatek", "je_vikend",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Přímé mazání na téhle stránce zůstává zakázané (viz docstring
        # výše). Ale při mazání zaměstnance/uživatele (kaskáda přes
        # on_delete=CASCADE) admin před potvrzením ověřuje tohle
        # oprávnění pro každý zasažený model — bez výjimky by to smazání
        # zaměstnance úplně znemožnilo. Povolíme ho tedy všude kromě
        # vlastních stránek WorkdaySummary (changelist/delete/...).
        opts = self.model._meta
        match = request.resolver_match
        if match and match.url_name and match.url_name.startswith(
            f"{opts.app_label}_{opts.model_name}_"
        ):
            return False
        return super().has_delete_permission(request, obj)
