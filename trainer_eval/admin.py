from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    InternalEvaluation,
    StrategicContribution,
    TrainerAlert,
)


@admin.register(InternalEvaluation)
class InternalEvaluationAdmin(admin.ModelAdmin):
    list_display = ("evaluated_on", "trainer", "training", "core_score_20", "specific_score_10", "total_score_30", "decision")
    list_filter = ("training", "decision")
    search_fields = ("trainer__first_name", "trainer__last_name", "training__title", "strengths", "improvements")


@admin.register(StrategicContribution)
class StrategicContributionAdmin(admin.ModelAdmin):
    list_display = ("date", "trainer", "kind", "training", "points", "created_by")
    list_filter = ("kind", "training")
    search_fields = ("trainer__first_name", "trainer__last_name", "description")


@admin.register(TrainerAlert)
class TrainerAlertAdmin(admin.ModelAdmin):
    list_display = ("triggered_on", "trainer", "training", "severity", "category", "status")
    list_filter = ("severity", "category", "status", "training")
    search_fields = ("trainer__first_name", "trainer__last_name", "metric", "value", "manager_comment")