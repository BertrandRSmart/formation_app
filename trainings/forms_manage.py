from django import forms
from .models import Participant, Registration


class SessionSearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(attrs={"placeholder": "Référence de session…"})
    )


class ParticipantForm(forms.ModelForm):
    class Meta:
        model = Participant
        fields = ["client", "first_name", "last_name", "email", "company_service", "referrer"]


class RegistrationMiniForm(forms.ModelForm):
    class Meta:
        model = Registration
        fields = [
            "status",
            "is_free",
            "canceled_at",
            "billing_rate_percent",
        ]
        widgets = {
            "status": forms.Select(attrs={"class": "fm-select"}),
            "is_free": forms.CheckboxInput(attrs={"class": "fm-check"}),
            "canceled_at": forms.DateInput(attrs={"type": "date", "class": "fm-input"}),
            "billing_rate_percent": forms.Select(attrs={"class": "fm-select"}),
        }

    def clean(self):
        cleaned = super().clean()

        status = cleaned.get("status")
        is_free = cleaned.get("is_free")
        canceled_at = cleaned.get("canceled_at")

        # Si offert, on garde 100% mais le montant sera forcé à 0 côté modèle
        # Si annulé sans date, le modèle mettra la date du jour automatiquement
        # Si non annulé, on vide la date ici pour garder une donnée propre
        if status != "CANCELED":
            cleaned["canceled_at"] = None

        # Optionnel : si offert + annulé, on laisse faire le modèle
        return cleaned