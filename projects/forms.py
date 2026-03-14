from django import forms

from .models import Project, Task, TaskAssignment


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
            "estimated_days",
            "planned_start_date",
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
            "estimated_days": "Charge estimée (jours)",
            "planned_start_date": "Date prévue de début",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex: Préparer le module 1"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "planned_start_date": forms.DateInput(attrs={"type": "date"}),
            "order": forms.NumberInput(attrs={"min": 0}),
            "priority": forms.NumberInput(attrs={"min": 1, "max": 3}),
            "estimated_days": forms.NumberInput(attrs={"min": 0, "step": "0.1"}),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            "name",
            "category",
            "description",
            "status",
            "target_date",
            "estimated_days",
            "owner",
            "is_active",
        ]
        labels = {
            "name": "Nom du projet",
            "category": "Catégorie",
            "description": "Description",
            "status": "Statut",
            "target_date": "Date cible",
            "estimated_days": "Charge estimée globale (jours)",
            "owner": "Responsable",
            "is_active": "Projet actif",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex: Formation 1"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "target_date": forms.DateInput(attrs={"type": "date"}),
            "estimated_days": forms.NumberInput(attrs={"min": 0, "step": "0.1"}),
        }


class TaskAssignmentForm(forms.ModelForm):
    class Meta:
        model = TaskAssignment
        fields = [
            "task",
            "trainer",
            "planned_days",
            "start_date",
            "end_date",
            "status",
            "is_visible_in_one_to_one",
            "notes",
        ]
        labels = {
            "task": "Tâche",
            "trainer": "Formateur",
            "planned_days": "Charge planifiée (jours)",
            "start_date": "Date de début prévue",
            "end_date": "Date de fin prévue",
            "status": "Statut",
            "is_visible_in_one_to_one": "Visible dans les 1 to 1",
            "notes": "Notes",
        }
        widgets = {
            "planned_days": forms.NumberInput(attrs={"min": 0, "step": "0.1"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }