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
        fields = ["status"]
