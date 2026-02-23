from django import forms
from .models import Task, Project


from django import forms
from .models import Task, Project


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "project",
            "title",
            "description",
            "status",
            "order",
            "priority",
            "assignee",
            "due_date",
        ]
        labels = {
            "project": "Projet",
            "title": "Titre",
            "description": "Description",
            "status": "Statut",
            "order": "Ordre",
            "priority": "Priorité",
            "assignee": "Assigné à",
            "due_date": "Échéance",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex: Point de synchro…"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "order": forms.NumberInput(attrs={"min": 0}),
            "priority": forms.NumberInput(attrs={"min": 1, "max": 3}),
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
