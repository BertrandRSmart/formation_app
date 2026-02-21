from django.db import models
from django.utils import timezone
from trainings.models import Trainer


# =========================================================
# Modules ArgonOS (minimum viable pour l’instant)
# =========================================================
class ArgonosModule(models.Model):
    KIND_TECH = "TECH"
    KIND_FUNC = "FUNC"
    KIND_CHOICES = (
        (KIND_TECH, "Technique"),
        (KIND_FUNC, "Fonctionnelle"),
    )

    LEVEL_1 = "L1"
    LEVEL_2 = "L2"
    LEVEL_3 = "L3"
    LEVEL_CHOICES = (
        (LEVEL_1, "Niveau 1"),
        (LEVEL_2, "Niveau 2"),
        (LEVEL_3, "Niveau 3"),
    )

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_TECH)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=LEVEL_1)

    major_version = models.PositiveIntegerField(default=1)
    current_patch = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    prerequisites = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="required_for",
    )

    class Meta:
        ordering = ("kind", "level", "name")

    def __str__(self):
        return self.name


# =========================================================
# Parcours (track) + étapes (step)
# =========================================================
class ArgonosTrack(models.Model):
    KIND_TECH = "TECH"
    KIND_FUNC = "FUNC"
    KIND_CHOICES = (
        (KIND_TECH, "Technique"),
        (KIND_FUNC, "Fonctionnelle"),
    )

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_TECH)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "name")

    def __str__(self):
        return self.name


class ArgonosTrackStep(models.Model):
    track = models.ForeignKey(ArgonosTrack, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(default=1)
    module = models.ForeignKey(ArgonosModule, on_delete=models.PROTECT, related_name="track_steps")
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ("track", "order")
        unique_together = (("track", "order"),)

    def __str__(self):
        return f"{self.track} #{self.order} — {self.module}"


# =========================================================
# Maîtrise par module / niveau officiel par parcours
# (on met des champs simples pour ne pas te bloquer)
# =========================================================
class TrainerModuleMastery(models.Model):
    AUTO_L1 = "L1"
    AUTO_L2 = "L2"
    AUTO_L3 = "L3"
    AUTO_CHOICES = (
        (AUTO_L1, "Auto L1"),
        (AUTO_L2, "Auto L2"),
        (AUTO_L3, "Auto L3"),
    )

    STATUS_PENDING = "PENDING"
    STATUS_OK = "OK"
    STATUS_KO = "KO"
    STATUS_CHOICES = (
        (STATUS_PENDING, "En attente"),
        (STATUS_OK, "OK"),
        (STATUS_KO, "KO"),
    )

    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="module_masteries")
    module = models.ForeignKey(ArgonosModule, on_delete=models.CASCADE, related_name="trainer_masteries")

    auto_level = models.CharField(max_length=10, choices=AUTO_CHOICES, default=AUTO_L1)
    manager_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    cert_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)

    validated_major = models.PositiveIntegerField(null=True, blank=True)
    validated_patch = models.PositiveIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("trainer", "module"),)
        ordering = ("trainer__last_name", "module__kind", "module__name")

    def __str__(self):
        return f"{self.trainer} — {self.module}"


class TrainerTrackProgress(models.Model):
    LEVEL_1 = "L1"
    LEVEL_2 = "L2"
    LEVEL_3 = "L3"
    LEVEL_CHOICES = (
        (LEVEL_1, "Niveau 1"),
        (LEVEL_2, "Niveau 2"),
        (LEVEL_3, "Niveau 3"),
    )

    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="track_progress")
    track = models.ForeignKey(ArgonosTrack, on_delete=models.CASCADE, related_name="trainer_progress")
    official_level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default=LEVEL_1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("trainer", "track"),)
        ordering = ("trainer__last_name", "track__kind", "track__name")

    def __str__(self):
        return f"{self.trainer} — {self.track} ({self.official_level})"


# =========================================================
# 1 to 1 (réunion hebdo) + objectifs
# =========================================================
def monday_of_week(d):
    # d est une date (timezone.localdate)
    return d - timezone.timedelta(days=d.weekday())


class OneToOneStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    VALIDATED = "VALIDATED", "Validé"


class ObjectiveStatus(models.TextChoices):
    TODO = "TODO", "À faire"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    BLOCKED = "BLOCKED", "Bloqué"
    DONE = "DONE", "Terminé"


class ObjectiveCategory(models.TextChoices):
    TRAINING = "TRAINING", "Formations réalisées"
    GOAL = "GOAL", "Objectifs"
    OTHER = "OTHER", "Autres points"


class OneToOneMeeting(models.Model):
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="one_to_ones")
    week_start = models.DateField("Semaine du (lundi)", default=timezone.localdate)
    meeting_date = models.DateField("Date du 1 to 1", null=True, blank=True)
    status = models.CharField(max_length=20, choices=OneToOneStatus.choices, default=OneToOneStatus.DRAFT)
    summary = models.TextField("Résumé (optionnel)", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-week_start",)
        unique_together = (("trainer", "week_start"),)

    def __str__(self):
        return f"1to1 {self.trainer} — {self.week_start}"


class OneToOneObjective(models.Model):
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="one_to_one_objectives")
    meeting = models.ForeignKey(OneToOneMeeting, on_delete=models.CASCADE, related_name="objectives")

    category = models.CharField(max_length=20, choices=ObjectiveCategory.choices, default=ObjectiveCategory.GOAL)
    title = models.CharField("Objectif", max_length=200)
    description = models.TextField("Détails", blank=True, default="")
    due_date = models.DateField("Échéance", null=True, blank=True)

    status = models.CharField(max_length=20, choices=ObjectiveStatus.choices, default=ObjectiveStatus.TODO)
    actionable = models.BooleanField("Créer une tâche Kanban", default=False)

    linked_module = models.ForeignKey(
        ArgonosModule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="objectives",
        verbose_name="Module lié (optionnel)",
    )

    created_task_id = models.IntegerField(null=True, blank=True)  # id de Task (app projects)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title