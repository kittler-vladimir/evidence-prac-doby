from django.contrib import admin
from .models import TypDovolene, ZustatekDovolene, ZadostODovolenou


@admin.register(TypDovolene)
class TypDovoleneAdmin(admin.ModelAdmin):
    list_display = ["zkratka", "nazev", "odecita_ze_zustatku", "aktivni"]
    list_editable = ["aktivni"]


@admin.register(ZustatekDovolene)
class ZustatekDovoleneAdmin(admin.ModelAdmin):
    list_display = ["employee", "rok", "narok_hodin", "cerpano_hodin", "zbyvajici_hodin"]
    list_filter = ["rok"]
    search_fields = ["employee__user__last_name", "employee__osobni_cislo"]


@admin.register(ZadostODovolenou)
class ZadostODovolenoAdmin(admin.ModelAdmin):
    list_display = [
        "employee", "typ", "datum_od", "datum_do",
        "pocet_hodin", "stav", "schvalovatele", "schvaleno_kym"
    ]
    list_filter = ["stav", "typ"]
    search_fields = ["employee__user__last_name"]
    date_hierarchy = "datum_od"
    readonly_fields = ["pocet_hodin", "vytvoreno", "upraveno"]
