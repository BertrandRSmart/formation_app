from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ProjectCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=20, blank=True, default="")  # optionnel (#FF89E9)

    class Meta:
        ordering = ["name"]
        verbose_name = "Catégorie de projet"
        verbose_name_plural = "Catégories de projet"

    def __str__(self):
        return self.name


class Project(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "À lancer"
        DOING = "doing", "En cours"
        BLOCKED = "blocked", "Bloqué"
        DONE = "done", "Terminé"
        CANCELED = "canceled", "Annulé"

    name = models.CharField(max_length=160)
    category = models.ForeignKey(
        ProjectCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="projects",
    )
    is_active = models.BooleanField(default=True)

    # =========================
    # AJOUTS PILOTAGE PROJET
    # =========================
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
    )
    target_date = models.DateField("Date cible", null=True, blank=True)
    estimated_days = models.DecimalField(
        "Charge estimée globale (jours)",
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        validators=[MinValueValidator(Decimal("0.0"))],
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_projects",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Projet"
        verbose_name_plural = "Projets"

    def __str__(self):
        return self.name

    @property
    def tasks_total(self):
        return self.tasks.count()

    @property
    def tasks_done(self):
        return self.tasks.filter(status=Task.Status.DONE).count()

    @property
    def progress_percent(self):
        total = self.tasks_total
        if total == 0:
            return 0
        return int((self.tasks_done / total) * 100)


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

    # Conservé pour compatibilité avec ton existant
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )

    due_date = models.DateField(null=True, blank=True)

    # =========================
    # AJOUTS PILOTAGE TÂCHE
    # =========================
    estimated_days = models.DecimalField(
        "Charge estimée (jours)",
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
        validators=[MinValueValidator(Decimal("0.0"))],
    )
    planned_start_date = models.DateField("Date prévue de début", null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["project", "order", "id"]
        verbose_name = "Tâche"
        verbose_name_plural = "Tâches"

    def __str__(self):
        return self.title

    @property
    def assignments_total(self):
        return self.assignments.count()

    @property
    def assigned_days_total(self):
        value = self.assignments.aggregate(
            total=models.Sum("planned_days")
        )["total"]
        return value or Decimal("0.0")


class ProjectStep(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "À faire"
        DOING = "doing", "En cours"
        DONE = "done", "Validé"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="steps")
    title = models.CharField(max_length=160)  # ex: Kickoff / Recette / Livraison
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    order = models.PositiveIntegerField(default=0)

    due_date = models.DateField(null=True, blank=True)
    done_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = ("project", "title")

    def __str__(self):
        return f"{self.project} — {self.title}"


class TaskAssignment(models.Model):
    class Status(models.TextChoices):
        FORECAST = "forecast", "Prévisionnel"
        CONFIRMED = "confirmed", "Confirmé"
        IN_PROGRESS = "in_progress", "En cours"
        DONE = "done", "Terminé"
        CANCELED = "canceled", "Annulé"

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="assignments",
    )

    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.CASCADE,
        related_name="task_assignments",
    )

    planned_days = models.DecimalField(
        "Charge planifiée (jours)",
        max_digits=6,
        decimal_places=1,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0.0"))],
    )

    start_date = models.DateField("Date de début prévue", null=True, blank=True)
    end_date = models.DateField("Date de fin prévue", null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.FORECAST,
    )

    is_visible_in_one_to_one = models.BooleanField(
        "Visible dans les 1 to 1",
        default=True,
    )

    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_task_assignments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_date", "end_date", "task__project__name", "task__title"]
        verbose_name = "Affectation de tâche"
        verbose_name_plural = "Affectations de tâches"
        unique_together = ("task", "trainer", "start_date", "end_date")

    def __str__(self):
        return f"{self.task} — {self.trainer}"

    def clean(self):
        super().clean()

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("La date de fin ne peut pas être antérieure à la date de début.")

        if self.planned_days is not None and self.planned_days < 0:
            raise ValidationError("La charge planifiée ne peut pas être négative.")