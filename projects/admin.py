from django.contrib import admin
from .models import Project, Task


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "priority", "assignee", "due_date", "updated_at")
    list_filter = ("status", "priority", "project")
    search_fields = ("title", "description", "project__name", "assignee__username")
    autocomplete_fields = ("assignee",)
    ordering = ("status", "order", "-updated_at")
