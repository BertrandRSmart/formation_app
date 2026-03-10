from django.contrib import admin

# ✅ Admin "safe" : n'explose pas si les modèles ne sont pas encore créés
try:
    from .models import (
        # Formation
        InternalEvaluation,
        StrategicContribution,
        TrainerAlert,
        EvaluationRubric,
        EvaluationCriterion,
        EvaluationScore,

        # Projets (contributions)
        ProjectRubric,
        ProjectCriterion,
        ProjectContributionEvaluation,
        ProjectScore,
    )
except Exception:
    InternalEvaluation = StrategicContribution = TrainerAlert = None
    EvaluationRubric = EvaluationCriterion = EvaluationScore = None

    ProjectRubric = ProjectCriterion = ProjectContributionEvaluation = ProjectScore = None


# =========================================================
# Existing models (formation)
# =========================================================

if InternalEvaluation:
    @admin.register(InternalEvaluation)
    class InternalEvaluationAdmin(admin.ModelAdmin):
        list_display = (
            "evaluated_on",
            "trainer",
            "training",
            "core_score_20",
            "specific_score_10",
            "total_score_30",
            "decision",
            "rubric_score_100",
        )
        list_filter = ("training", "decision")
        search_fields = (
            "trainer__first_name",
            "trainer__last_name",
            "training__title",
            "strengths",
            "improvements",
            "manager_comment",
            "trainer_comment",
        )


if StrategicContribution:
    @admin.register(StrategicContribution)
    class StrategicContributionAdmin(admin.ModelAdmin):
        list_display = ("date", "trainer", "kind", "training", "points", "created_by")
        list_filter = ("kind", "training")
        search_fields = ("trainer__first_name", "trainer__last_name", "description")


if TrainerAlert:
    @admin.register(TrainerAlert)
    class TrainerAlertAdmin(admin.ModelAdmin):
        list_display = ("triggered_on", "trainer", "training", "severity", "category", "status")
        list_filter = ("severity", "category", "status", "training")
        search_fields = ("trainer__first_name", "trainer__last_name", "metric", "value", "manager_comment")


# =========================================================
# Rubrics / Criteria / Scores (formation)
# =========================================================

if EvaluationRubric and EvaluationCriterion:
    class EvaluationCriterionInline(admin.TabularInline):
        model = EvaluationCriterion
        extra = 0
        fields = ("section", "label", "max_score", "weight", "sort_order", "is_active")
        ordering = ("section", "sort_order", "id")


if EvaluationRubric:
    @admin.register(EvaluationRubric)
    class EvaluationRubricAdmin(admin.ModelAdmin):
        list_display = ("training", "version_label", "is_active", "created_at")
        list_filter = ("training", "is_active")
        search_fields = ("training__title", "version_label", "title")
        inlines = [EvaluationCriterionInline] if EvaluationCriterion else []


if EvaluationCriterion:
    @admin.register(EvaluationCriterion)
    class EvaluationCriterionAdmin(admin.ModelAdmin):
        list_display = ("rubric", "section", "label", "max_score", "weight", "sort_order", "is_active")
        list_filter = ("section", "is_active", "rubric__training")
        search_fields = ("label", "rubric__training__title", "rubric__version_label")


if EvaluationScore:
    @admin.register(EvaluationScore)
    class EvaluationScoreAdmin(admin.ModelAdmin):
        list_display = ("evaluation", "criterion", "score")
        list_filter = ("criterion__section",)
        search_fields = ("evaluation__trainer__last_name", "criterion__label")


# =========================================================
# NEW: Rubrics / Criteria / Scores (projets)
# =========================================================

if ProjectRubric and ProjectCriterion:
    class ProjectCriterionInline(admin.TabularInline):
        model = ProjectCriterion
        extra = 0
        fields = ("section", "label", "max_score", "weight", "sort_order", "is_active")
        ordering = ("section", "sort_order", "id")


if ProjectRubric:
    @admin.register(ProjectRubric)
    class ProjectRubricAdmin(admin.ModelAdmin):
        list_display = ("category", "version_label", "is_active", "created_at")
        list_filter = ("category", "is_active")
        search_fields = ("category__name", "version_label", "title", "description")
        inlines = [ProjectCriterionInline] if ProjectCriterion else []


if ProjectCriterion:
    @admin.register(ProjectCriterion)
    class ProjectCriterionAdmin(admin.ModelAdmin):
        list_display = ("rubric", "section", "label", "max_score", "weight", "sort_order", "is_active")
        list_filter = ("section", "is_active", "rubric__category")
        search_fields = ("label", "rubric__version_label", "rubric__category__name")


if ProjectContributionEvaluation:
    @admin.register(ProjectContributionEvaluation)
    class ProjectContributionEvaluationAdmin(admin.ModelAdmin):
        list_display = ("evaluated_on", "trainer", "project", "step", "decision", "rubric_score_100")
        list_filter = ("decision", "project__category", "project")
        search_fields = ("trainer__first_name", "trainer__last_name", "project__name", "step__title")


if ProjectScore:
    @admin.register(ProjectScore)
    class ProjectScoreAdmin(admin.ModelAdmin):
        list_display = ("evaluation", "criterion", "score")
        list_filter = ("criterion__section", "criterion__rubric")
        search_fields = ("evaluation__trainer__last_name", "criterion__label")