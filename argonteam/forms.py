from django import forms
from .models import OneToOneObjective

class OneToOneObjectiveForm(forms.ModelForm):
    class Meta:
        model = OneToOneObjective
        fields = ["title", "done"]
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "Ex: Finaliser le support de la semaine…",
            }),
        }