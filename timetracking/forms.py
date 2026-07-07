from django import forms
from django.db.models import Q
from .models import WorkSession, Pohyb, TypPohybu


class WorkSessionOpravitForm(forms.ModelForm):
    """Formulář pro opravu / doplnění záznamu."""

    class Meta:
        model = WorkSession
        fields = ["zacatek", "konec", "poznamka"]
        widgets = {
            "zacatek": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "konec": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Přizpůsobení formátu pro datetime-local input
        if self.instance.zacatek:
            self.initial["zacatek"] = self.instance.zacatek.strftime("%Y-%m-%dT%H:%M")
        if self.instance.konec:
            self.initial["konec"] = self.instance.konec.strftime("%Y-%m-%dT%H:%M")


class WorkSessionRucneForm(forms.ModelForm):
    """Formulář pro ruční přidání pracovního bloku."""

    class Meta:
        model = WorkSession
        fields = ["zacatek", "konec", "poznamka"]
        widgets = {
            "zacatek": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "konec": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        zacatek = cleaned.get("zacatek")
        konec = cleaned.get("konec")

        if zacatek and konec and konec <= zacatek:
            raise forms.ValidationError("Konec musí být po začátku.")

        # Kontrola překryvu
        if zacatek and konec and self.employee:
            qs = WorkSession.objects.filter(
                employee=self.employee,
                zacatek__lt=konec,
                konec__gt=zacatek,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Tento časový blok se překrývá s existujícím záznamem."
                )
        return cleaned


class PohybRucneForm(forms.ModelForm):
    """Formulář pro zpětné doplnění pohybu do existujícího pracovního bloku."""

    class Meta:
        model = Pohyb
        fields = ["typ", "zacatek", "konec", "poznamka"]
        widgets = {
            "zacatek": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "konec": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        self.fields["typ"].queryset = TypPohybu.objects.filter(aktivni=True)
        if self.instance.zacatek:
            self.initial["zacatek"] = self.instance.zacatek.strftime("%Y-%m-%dT%H:%M")
        if self.instance.konec:
            self.initial["konec"] = self.instance.konec.strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        zacatek = cleaned.get("zacatek")
        konec = cleaned.get("konec")

        if zacatek and konec and konec <= zacatek:
            raise forms.ValidationError("Konec musí být po začátku.")

        if zacatek and self.employee:
            horni_hranice = konec or zacatek
            session = (
                WorkSession.objects.filter(employee=self.employee, zacatek__lte=zacatek)
                .filter(Q(konec__isnull=True) | Q(konec__gte=horni_hranice))
                .order_by("-zacatek")
                .first()
            )
            if not session:
                raise forms.ValidationError(
                    "Pro tento čas nebyl nalezen odpovídající pracovní blok (příchod/odchod)."
                )
            self.instance.work_session = session

        return cleaned
