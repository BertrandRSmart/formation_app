from django import forms
from trainings.models import Session
from .models import InternalEvaluation
from .models import StrategicContribution, ContributionKind
from .models import TrainerAlert


class SessionSatisfactionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = ["client_satisfaction"]
        widgets = {
            "client_satisfaction": forms.NumberInput(attrs={"min": 0, "max": 20}),
        }

class InternalEvaluationForm(forms.ModelForm):
    class Meta:
        model = InternalEvaluation
        fields = [
            "trainer",
            "training",          # optionnel
            "evaluated_on",
            "core_score_20",
            "specific_score_10",
            "decision",
            "strengths",
            "improvements",
            "private_note",
        ]
        widgets = {
            "evaluated_on": forms.DateInput(attrs={"type": "date"}),
            "strengths": forms.Textarea(attrs={"rows": 3}),
            "improvements": forms.Textarea(attrs={"rows": 3}),
            "private_note": forms.Textarea(attrs={"rows": 2}),
        }


DEFAULT_POINTS = {
    ContributionKind.CREATE_MODULE: 20,
    ContributionKind.UPDATE_MAJOR: 15,
    ContributionKind.UPDATE_MINOR: 5,
    ContributionKind.MENTORING: 10,
    ContributionKind.INTERNAL_WORKSHOP: 8,
    ContributionKind.PROJECT: 12,
}

class StrategicContributionForm(forms.ModelForm):
    class Meta:
        model = StrategicContribution
        fields = ["trainer", "training", "kind", "points", "date", "description"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        points = cleaned.get("points")
        # Si points vide (ou 0) et kind présent, on met un défaut
        if kind and (points is None or points == 0):
            cleaned["points"] = DEFAULT_POINTS.get(kind, 0)
        return cleaned


class TrainerAlertForm(forms.ModelForm):
    class Meta:
        model = TrainerAlert
        fields = [
            "trainer",
            "training",
            "category",
            "severity",
            "triggered_on",
            "metric",
            "value",
            "status",
            "manager_comment",
        ]
        widgets = {
            "triggered_on": forms.DateInput(attrs={"type": "date"}),
            "manager_comment": forms.Textarea(attrs={"rows": 3}),
        }