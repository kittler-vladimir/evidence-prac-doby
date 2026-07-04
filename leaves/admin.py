from django.contrib import admin
from .models import (
    TypStavu,
    NarokIndispozicnihoVolna,
    ZustatekStavu,
    ZadostOStav,
)


@admin.register(TypStavu)
class TypStavuAdmin(admin.ModelAdmin):
    list_display = [
        "zkratka", "nazev", "je_pritomnost", "vyzaduje_schvaleni",
        "odecita_ze_zustatku", "je_indispozicni_volno",
        "kategorie_pro_prehled", "aktivni",
    ]
    list_editable = ["aktivni"]
    list_filter = ["kategorie_pro_prehled", "je_pritomnost", "vyzaduje_schvaleni"]


@admin.register(NarokIndispozicnihoVolna)
class NarokIndispozicnihoVolnaAdmin(admin.ModelAdmin):
    list_display = ["platne_od", "hodin"]
    ordering = ["-platne_od"]


@admin.register(ZustatekStavu)
class ZustatekStavuAdmin(admin.ModelAdmin):
    list_display = ["employee", "rok", "typ", "narok_hodin", "cerpano_hodin", "zbyvajici_hodin"]
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
    readonly_fields = ["pocet_hodin", "vytvoreno", "upraveno"]
