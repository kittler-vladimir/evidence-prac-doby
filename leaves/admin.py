from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import (
    TypStavu,
    NarokIndispozicnihoVolna,
    NarokDovolene,
    ZustatekStavu,
    ZadostOStav,
)


@admin.register(TypStavu)
class TypStavuAdmin(admin.ModelAdmin):
    list_display = [
        "zkratka", "nazev", "je_pritomnost", "vyzaduje_schvaleni",
        "odecita_ze_zustatku", "je_indispozicni_volno", "je_dovolena",
        "kategorie_pro_prehled", "aktivni",
    ]
    list_editable = ["aktivni"]
    list_filter = ["kategorie_pro_prehled", "je_pritomnost", "vyzaduje_schvaleni"]


@admin.register(NarokIndispozicnihoVolna)
class NarokIndispozicnihoVolnaAdmin(admin.ModelAdmin):
    list_display = ["platne_od", "hodin"]
    ordering = ["-platne_od"]


@admin.register(NarokDovolene)
class NarokDovoleneAdmin(admin.ModelAdmin):
    list_display = ["platne_od", "hodin"]
    ordering = ["-platne_od"]


@admin.register(ZustatekStavu)
class ZustatekStavuAdmin(admin.ModelAdmin):
    list_display = ["employee", "rok", "typ", "narok_hodin", "cerpano_hodin", "zbyvajici_hodin"]
    list_editable = ["narok_hodin"]
    list_filter = ["rok", "typ"]
    search_fields = ["employee__user__last_name", "employee__osobni_cislo"]


@admin.register(ZadostOStav)
class ZadostOStavAdmin(admin.ModelAdmin):
    list_display = [
        "employee", "typ", "datum_od", "datum_do",
        "pocet_hodin", "stav", "schvalovatele", "schvaleno_kym"
    ]
    list_filter = ["stav", "typ"]
    search_fields = ["employee__user__last_name"]
    date_hierarchy = "datum_od"
    # "stav" a schvalovací pole se nesmí editovat napřímo — obchází to
    # ZadostOStav.schval()/zamitni() (aktualizace ZustatekStavu.cerpano_hodin).
    # Schvalování/zamítání jde jen přes akce níže.
    readonly_fields = ["pocet_hodin", "stav", "schvaleno_kym", "schvaleno_kdy", "vytvoreno", "upraveno"]
    actions = ["schvalit_zadosti", "zamitnout_zadosti"]

    @admin.action(description=_("Schválit vybrané žádosti"))
    def schvalit_zadosti(self, request, queryset):
        schvalovatel = getattr(request.user, "employee", None)
        pocet = 0
        for zadost in queryset.filter(stav=ZadostOStav.Stav.CEKA):
            try:
                zadost.schval(schvalovatel)
                pocet += 1
            except ValidationError as e:
                self.message_user(request, f"{zadost}: {e.message}", level=messages.ERROR)
        if pocet:
            self.message_user(request, _("Schváleno žádostí: %(pocet)s") % {"pocet": pocet})

    @admin.action(description=_("Zamítnout vybrané žádosti"))
    def zamitnout_zadosti(self, request, queryset):
        schvalovatel = getattr(request.user, "employee", None)
        pocet = 0
        for zadost in queryset.filter(stav=ZadostOStav.Stav.CEKA):
            zadost.zamitni(schvalovatel)
            pocet += 1
        if pocet:
            self.message_user(request, _("Zamítnuto žádostí: %(pocet)s") % {"pocet": pocet})
