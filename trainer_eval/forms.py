from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from trainings.models import Session

from projects.models import Project, ProjectStep

from .models import (
    # --- Evaluations internes ---
    InternalEvaluation,
    EvaluationScore,
    EvaluationRubric,

    # --- Contributions "points" (déjà existant chez toi) ---
    StrategicContribution,
    ContributionKind,

    # --- Alerts ---
    TrainerAlert,

    # --- Contributions projets (nouveaux modèles) ---
    ProjectRubric,
    ProjectContributionEvaluation,
    ProjectScore,
)


# ------------------------------------------------------------
# Satisfaction client (Session)
# ------------------------------------------------------------
class SessionSatisfactionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = ["client_satisfaction"]
        widgets = {
            "client_satisfaction": forms.NumberInput(attrs={"min": 0, "max": 20}),
        }


# ------------------------------------------------------------
# Internal Evaluation (header/context)
# ------------------------------------------------------------
class InternalEvaluationForm(forms.ModelForm):
    class Meta:
        model = InternalEvaluation
        fields = [
            "evaluated_on",
            "trainer",
            "training",
            "rubric",

            # champs manquants vs ton template
            "decision",
            "core_score_20",
            "specific_score_10",

            "strengths",
            "improvements",
            "manager_comment",
            "trainer_comment",
        ]
        widgets = {
            "evaluated_on": forms.DateInput(attrs={"type": "date"}),

            "core_score_20": forms.NumberInput(attrs={"min": 0, "max": 20, "step": 1}),
            "specific_score_10": forms.NumberInput(attrs={"min": 0, "max": 10, "step": 1}),

            "strengths": forms.Textarea(attrs={"rows": 3}),
            "improvements": forms.Textarea(attrs={"rows": 3}),
            "manager_comment": forms.Textarea(attrs={"rows": 3}),
            "trainer_comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        training_id = None
        if self.data.get("training"):
            training_id = self.data.get("training")
        elif getattr(self.instance, "training_id", None):
            training_id = self.instance.training_id

        qs = EvaluationRubric.objects.all().order_by("-created_at")
        if training_id:
            qs = qs.filter(training_id=training_id)

        self.fields["rubric"].queryset = qs

        # pré-sélection rubric active
        if not self.initial.get("rubric") and not getattr(self.instance, "rubric_id", None):
            active = qs.filter(is_active=True).first()
            if active:
                self.initial["rubric"] = active.pk
        self.fields["rubric"].required = True


# ------------------------------------------------------------
# Scores par critère (formset)
# ------------------------------------------------------------
class EvaluationScoreForm(forms.ModelForm):
    class Meta:
        model = EvaluationScore
        fields = ["criterion", "score", "comment"]
        widgets = {
            "criterion": forms.HiddenInput(),
            "score": forms.NumberInput(attrs={"min": 0, "max": 5, "step": 1}),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }


EvaluationScoreFormSet = inlineformset_factory(
    parent_model=InternalEvaluation,
    model=EvaluationScore,
    form=EvaluationScoreForm,
    extra=0,
    can_delete=False,
)


# ------------------------------------------------------------
# Strategic Contributions (points)
# ------------------------------------------------------------
DEFAULT_POINTS = {
    ContributionKind.DOC: 10,
    ContributionKind.MENTORING: 10,
    ContributionKind.CONTENT: 10,
    ContributionKind.PROJECT: 10,
    ContributionKind.FEEDBACK: 10,
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

        if kind and (points is None or points == 0):
            cleaned["points"] = DEFAULT_POINTS.get(kind, 0)

        return cleaned


# ------------------------------------------------------------
# Alerts
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# Project Contributions Evaluation (header/context)
# ------------------------------------------------------------
class ProjectContributionEvaluationForm(forms.ModelForm):
    class Meta:
        model = ProjectContributionEvaluation
        fields = [
            "evaluated_on",
            "trainer",
            "project",
            "step",
            "rubric",

            # important : ton modèle a decision
            "decision",

            "strengths",
            "improvements",
            "manager_comment",
            "trainer_comment",
        ]
        widgets = {
            "evaluated_on": forms.DateInput(attrs={"type": "date"}),
            "strengths": forms.Textarea(attrs={"rows": 3}),
            "improvements": forms.Textarea(attrs={"rows": 3}),
            "manager_comment": forms.Textarea(attrs={"rows": 3}),
            "trainer_comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- project sélectionné (POST / instance) ---
        project_id = None
        if self.data.get("project"):
            project_id = self.data.get("project")
        elif getattr(self.instance, "project_id", None):
            project_id = self.instance.project_id

        # --- steps dépend du projet ---
        if project_id and str(project_id).isdigit():
            self.fields["step"].queryset = ProjectStep.objects.filter(
                project_id=int(project_id)
            ).order_by("order", "id")
        else:
            self.fields["step"].queryset = ProjectStep.objects.none()

        # --- rubrics dépend de la catégorie du projet (ou générique) ---
        rubrics_qs = ProjectRubric.objects.all().order_by("-created_at")

        if project_id and str(project_id).isdigit():
            proj = Project.objects.filter(pk=int(project_id)).select_related("category").first()
            if proj and proj.category_id:
                rubrics_qs = rubrics_qs.filter(
                    Q(category_id=proj.category_id) | Q(category__isnull=True)
                )

        self.fields["rubric"].queryset = rubrics_qs

        if not self.initial.get("rubric") and not getattr(self.instance, "rubric_id", None):
            active = rubrics_qs.filter(is_active=True).first()
            if active:
                self.initial["rubric"] = active.pk


# ------------------------------------------------------------
# Project Scores par critère (formset)
# ------------------------------------------------------------
class ProjectScoreForm(forms.ModelForm):
    class Meta:
        model = ProjectScore
        fields = ["criterion", "score", "comment"]
        widgets = {
            "criterion": forms.HiddenInput(),
            "score": forms.NumberInput(attrs={"min": 0, "max": 5, "step": 1}),
            "comment": forms.Textarea(attrs={"rows": 2}),
        }


ProjectScoreFormSet = inlineformset_factory(
    parent_model=ProjectContributionEvaluation,
    model=ProjectScore,
    form=ProjectScoreForm,
    extra=0,
    can_delete=False,
)

