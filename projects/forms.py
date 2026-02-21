from django import forms
from .models import Task, Project


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["project", "title", "description", "status", "priority", "assignee", "due_date"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "is_active"]
        labels = {
            "name": "Nom du projet",
            "is_active": "Projet actif",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex: Déploiement 2026"}),
        }
