from django import forms
from django.forms import formset_factory

from .models import Session, Participant


class BulkRegistrationForm(forms.Form):
    session = forms.ModelChoiceField(
        queryset=Session.objects.order_by("-start_date"),
        label="Session",
    )

    existing_participants = forms.ModelMultipleChoiceField(
        queryset=Participant.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": "30"}),
        label="Participants existants",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        session = None
        sid = self.data.get("session") or self.initial.get("session")

        if sid:
            try:
                session = Session.objects.select_related("client").get(pk=sid)
            except Session.DoesNotExist:
                session = None

        if session:
            self.fields["existing_participants"].queryset = (
                Participant.objects.filter(client=session.client)
                .order_by("last_name", "first_name")
            )
        else:
            self.fields["existing_participants"].queryset = Participant.objects.none()


class NewParticipantForm(forms.Form):
    first_name = forms.CharField(required=False, label="Prénom")
    last_name = forms.CharField(required=False, label="Nom")
    email = forms.EmailField(required=False, label="Email")
    company_service = forms.CharField(required=False, label="Service")

    def clean(self):
        data = super().clean()

        # Ligne complètement vide -> OK (on ignore)
        if not any([
            data.get("first_name"),
            data.get("last_name"),
            data.get("email"),
            data.get("company_service"),
        ]):
            return data

        # Ligne partiellement remplie -> on exige prénom + nom + email
        if not (data.get("first_name") and data.get("last_name") and data.get("email")):
            raise forms.ValidationError(
                "Pour créer un participant, renseigne au minimum prénom, nom et email."
            )

        return data


NewParticipantFormSet = formset_factory(NewParticipantForm, extra=25, can_delete=False)

# Bouton +Nouveau page Suivi paiements Mercure

from django import forms
from .models import MercureInvoice, MercureContract


class MercureInvoiceForm(forms.ModelForm):
    class Meta:
        model = MercureInvoice
        fields = ["session", "trainer", "reference", "amount_ht", "received_date", "paid_date", "status", "document_path", "notes"]
        widgets = {
            "received_date": forms.DateInput(attrs={"type": "date"}),
            "paid_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


class MercureContractForm(forms.ModelForm):
    class Meta:
        model = MercureContract
        fields = ["session", "trainer", "status", "sent_date", "signed_date", "notes"]
        widgets = {
            "sent_date": forms.DateInput(attrs={"type": "date"}),
            "signed_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
