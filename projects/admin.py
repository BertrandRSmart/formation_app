from django.contrib import admin
from django import forms

from .models import (
    ProjectCategory,
    Project,
    Task,
    ProjectStep,
    TaskAssignment,
)


# ---- Catégorie (avec color picker) ----
class ProjectCategoryForm(forms.ModelForm):
    class Meta:
        model = ProjectCategory
        fields = "__all__"
        widgets = {
            "color": forms.TextInput(
                attrs={"type": "color", "style": "width: 80px; height: 36px; padding: 0;"}
            ),
        }


@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    form = ProjectCategoryForm
    list_display = ("name", "color")
    search_fields = ("name",)


# ---- Affectations de tâches (inline) ----
class TaskAssignmentInline(admin.TabularInline):
    model = TaskAssignment
    extra = 0
    autocomplete_fields = ("trainer",)
    fields = (
        "trainer",
        "planned_days",
        "start_date",
        "end_date",
        "status",
        "is_visible_in_one_to_one",
        "notes",
    )


# ---- Projets ----
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "status",
        "target_date",
        "estimated_days",
        "owner",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "category", "status")
    search_fields = ("name", "description")
    autocomplete_fields = ("category", "owner")
    ordering = ("name",)


# ---- Tâches ----
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "project",
        "status",
        "priority",
        "assignee",
        "planned_start_date",
        "due_date",
        "estimated_days",
        "updated_at",
    )
    list_filter = ("status", "priority", "project", "project__category")
    search_fields = ("title", "description", "project__name", "assignee__username")
    autocomplete_fields = ("project", "assignee")
    ordering = ("project", "status", "order", "-updated_at")
    inlines = [TaskAssignmentInline]


# ---- Affectations de tâches ----
@admin.register(TaskAssignment)
class TaskAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "task",
        "trainer",
        "planned_days",
        "start_date",
        "end_date",
        "status",
        "is_visible_in_one_to_one",
        "updated_at",
    )
    list_filter = (
        "status",
        "is_visible_in_one_to_one",
        "trainer__product",
        "trainer__platform",
        "task__project",
        "task__project__category",
    )
    search_fields = (
        "task__title",
        "task__project__name",
        "trainer__first_name",
        "trainer__last_name",
        "notes",
    )
    autocomplete_fields = ("task", "trainer")
    ordering = ("start_date", "end_date", "task__project__name", "task__title")


# ---- Étapes projet ----
@admin.register(ProjectStep)
class ProjectStepAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "order", "due_date", "done_date", "updated_at")
    list_filter = ("project", "status")
    search_fields = ("title", "description", "project__name")
    autocomplete_fields = ("project",)
    ordering = ("project", "order", "id")