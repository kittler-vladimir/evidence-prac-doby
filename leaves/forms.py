from django import forms
from .models import ZadostOStav, TypStavu, ZustatekStavu


class ZadostOStavForm(forms.ModelForm):
    class Meta:
        model = ZadostOStav
        fields = ["typ", "datum_od", "cas_od", "datum_do", "cas_do", "poznamka_zamestnance"]
        widgets = {
            "datum_od": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "datum_do": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "cas_od": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "cas_do": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        help_texts = {
            "cas_od": "Jen u žádosti po hodinách — jinak nechte prázdné (celé dny).",
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        typy = TypStavu.objects.filter(aktivni=True)
        self.fields["typ"].queryset = typy
        # Typy, u kterých stránka nabídne čas od–do (viz nova_zadost.html).
        self.typy_po_hodinach = list(
            typy.filter(umoznuje_zadani_po_hodinach=True).values_list("pk", flat=True)
        )
        # Model.clean() hlídá hodinová pravidla (kolize, součet za den) a potřebuje
        # zaměstnance — ten se do formuláře jinak nedostane (nastavuje ho až view).
        if employee is not None:
            self.instance.employee = employee

    def clean(self):
        cleaned = super().clean()
        datum_od = cleaned.get("datum_od")
        datum_do = cleaned.get("datum_do")
        cas_od = cleaned.get("cas_od")
        cas_do = cleaned.get("cas_do")

        # Nekompletní čas hlásí ZadostOStav.clean() — tady by se zůstatek počítal
        # z celých dnů a hláška by byla zavádějící.
        if (cas_od is None) != (cas_do is None):
            return cleaned

        if datum_od and datum_do:
            if datum_do < datum_od:
                raise forms.ValidationError("Datum do musí být po datu od.")

            # Kontrola dostatku zůstatku
            typ = cleaned.get("typ")
            if typ and typ.odecita_ze_zustatku and self.employee:
                rok = datum_od.year
                zustatek = ZustatekStavu.objects.filter(
                    employee=self.employee, rok=rok, typ=typ
                ).first()

                # Spočítat hodiny
                temp = ZadostOStav(
                    employee=self.employee,
                    datum_od=datum_od,
                    datum_do=datum_do,
                    cas_od=cas_od,
                    cas_do=cas_do,
                )
                temp.vypocitej_hodiny()

                if zustatek:
                    zbyva = zustatek.zbyvajici_hodin
                elif typ.je_indispozicni_volno or typ.je_dovolena:
                    # Zůstatek ještě nebyl založen — virtuální nárok z globálního nastavení.
                    zbyva = typ.vychozi_narok(datum_od)
                else:
                    raise forms.ValidationError(
                        f"Pro rok {rok} není nastaven nárok na {typ.nazev.lower()}."
                    )

                if zbyva < temp.pocet_hodin:
                    raise forms.ValidationError(
                        f"Nedostatečný zůstatek. "
                        f"Zbývá {zbyva}h, žádáte {temp.pocet_hodin}h."
                    )

        return cleaned


class SamoschvaleniForm(forms.Form):
    duvod = forms.CharField(
        label="Důvod samoschválení",
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Uveďte důvod samoschválení."},
    )


class ZamitnutiForm(forms.Form):
    poznamka = forms.CharField(
        label="Důvod zamítnutí",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )
