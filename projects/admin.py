from django.contrib import admin
from django import forms

from .models import ProjectCategory, Project, Task, ProjectStep


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


# ---- Projets ----
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name",)
    autocomplete_fields = ("category",)


# ---- Tâches ----
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "priority", "assignee", "due_date", "updated_at")
    list_filter = ("status", "priority", "project")
    search_fields = ("title", "description", "project__name", "assignee__username")
    autocomplete_fields = ("project", "assignee")
    ordering = ("project", "status", "order", "-updated_at")


# ---- Étapes projet ----
@admin.register(ProjectStep)
class ProjectStepAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "order", "due_date", "done_date", "updated_at")
    list_filter = ("project", "status")
    search_fields = ("title", "description", "project__name")
    autocomplete_fields = ("project",)
    ordering = ("project", "order", "id")