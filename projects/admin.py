
from django.contrib import admin
from .models import Project, Task, ProjectCategory
from django import forms

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active")
    list_filter = ("category",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "priority", "assignee", "due_date", "updated_at")
    list_filter = ("status", "priority", "project")
    search_fields = ("title", "description", "project__name", "assignee__username")
    autocomplete_fields = ("assignee",)
    ordering = ("status", "order", "-updated_at")



class ProjectCategoryForm(forms.ModelForm):
    class Meta:
        model = ProjectCategory
        fields = "__all__"
        widgets = {
            "color": forms.TextInput(attrs={"type": "color", "style": "width: 80px; height: 36px; padding: 0;"}),
        }

@admin.register(ProjectCategory)
class ProjectCategoryAdmin(admin.ModelAdmin):
    form = ProjectCategoryForm
    list_display = ("name", "color")