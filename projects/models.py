from django.conf import settings
from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "TODO"
        DOING = "doing", "En cours"
        BLOCKED = "blocked", "Bloqué"
        DONE = "done", "Terminé"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    order = models.IntegerField(default=0)

    priority = models.IntegerField(default=2)  # 1=haute 2=normale 3=basse
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    due_date = models.DateField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
