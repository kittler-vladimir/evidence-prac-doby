from django import forms
from .models import ZadostODovolenou, TypDovolene, ZustatekDovolene


class ZadostODovolenoForm(forms.ModelForm):
    class Meta:
        model = ZadostODovolenou
        fields = ["typ", "datum_od", "datum_do", "poznamka_zamestnance"]
        widgets = {
            "datum_od": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "datum_do": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        self.fields["typ"].queryset = TypDovolene.objects.filter(aktivni=True)

    def clean(self):
        cleaned = super().clean()
        datum_od = cleaned.get("datum_od")
        datum_do = cleaned.get("datum_do")

        if datum_od and datum_do:
            if datum_do < datum_od:
                raise forms.ValidationError("Datum do musí být po datu od.")

            # Kontrola dostatku zůstatku
            typ = cleaned.get("typ")
            if typ and typ.odecita_ze_zustatku and self.employee:
                rok = datum_od.year
                zustatek = ZustatekDovolene.objects.filter(
                    employee=self.employee, rok=rok, typ=typ
                ).first()

                # Spočítat hodiny
                temp = ZadostODovolenou(
                    employee=self.employee,
                    datum_od=datum_od,
                    datum_do=datum_do,
                )
                temp.vypocitej_hodiny()

                if zustatek:
                    zbyva = zustatek.zbyvajici_hodin
                elif typ.je_indispozicni_volno:
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


class ZamitnutiForm(forms.Form):
    poznamka = forms.CharField(
        label="Důvod zamítnutí",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )
