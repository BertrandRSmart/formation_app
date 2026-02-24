from django.db import models

# Create your models here.
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


# ---------- Évaluation interne (socle /20 + spécifique /10 = /30) ----------

class InternalEvaluationDecision(models.TextChoices):
    VALIDATED = "VALIDATED", "Validée"
    TO_REDO = "TO_REDO", "À refaire"
    RETURN_TO_SIMULATION = "RETURN_TO_SIMULATION", "Retour simulation"


class InternalEvaluation(models.Model):
    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.PROTECT,
        related_name="internal_evaluations",
    )
    training = models.ForeignKey(
    "trainings.Training",
    on_delete=models.PROTECT,
    null=True,
    blank=True,
    related_name="internal_evaluations",
    )

    evaluated_on = models.DateField()

    core_score_20 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
    )
    specific_score_10 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    total_score_30 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        editable=False,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(30)],
    )

    strengths = models.TextField(blank=True)
    improvements = models.TextField(blank=True)

    decision = models.CharField(
        max_length=32,
        choices=InternalEvaluationDecision.choices,
        default=InternalEvaluationDecision.VALIDATED,
    )

    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="trainer_internal_evaluations",
    )
    private_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-evaluated_on"]

    def save(self, *args, **kwargs):
        self.total_score_30 = (self.core_score_20 or 0) + (self.specific_score_10 or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Eval interne {self.trainer} - {self.training} ({self.total_score_30}/30)"


# ---------- Contribution stratégique ----------

class ContributionKind(models.TextChoices):
    CREATE_MODULE = "CREATE_MODULE", "Création module"
    UPDATE_MAJOR = "UPDATE_MAJOR", "Mise à jour majeure"
    UPDATE_MINOR = "UPDATE_MINOR", "Mise à jour mineure"
    MENTORING = "MENTORING", "Mentorat"
    INTERNAL_WORKSHOP = "INTERNAL_WORKSHOP", "Atelier interne"
    PROJECT = "PROJECT", "Projet interne"


class StrategicContribution(models.Model):
    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.PROTECT,
        related_name="contributions",
    )
    training = models.ForeignKey(
        "trainings.Training",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contributions",
    )

    kind = models.CharField(max_length=32, choices=ContributionKind.choices)
    points = models.IntegerField(default=0)  # tu centralises au début
    date = models.DateField()
    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="trainer_contributions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.trainer} - {self.kind} ({self.points} pts)"


# ---------- Alertes historisées ----------

class AlertCategory(models.TextChoices):
    QUALITY = "QUALITY", "Qualité client"
    INTERNAL = "INTERNAL", "Évaluation interne"
    VOLUME = "VOLUME", "Volume / engagement"
    CONTRIBUTION = "CONTRIBUTION", "Contribution"


class AlertSeverity(models.TextChoices):
    RED = "RED", "Rouge"
    ORANGE = "ORANGE", "Orange"
    YELLOW = "YELLOW", "Jaune"
    BLUE = "BLUE", "Bleu"


class AlertStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    CLOSED = "CLOSED", "Clôturée"


class TrainerAlert(models.Model):
    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.PROTECT,
        related_name="alerts",
    )
    training = models.ForeignKey(
        "trainings.Training",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alerts",
    )

    category = models.CharField(max_length=16, choices=AlertCategory.choices)
    severity = models.CharField(max_length=8, choices=AlertSeverity.choices)

    triggered_on = models.DateField()
    metric = models.CharField(max_length=64, blank=True)  # ex: "avg_3_sessions"
    value = models.CharField(max_length=64, blank=True)   # ex: "13.20"

    status = models.CharField(
        max_length=16,
        choices=AlertStatus.choices,
        default=AlertStatus.ACTIVE,
    )
    manager_comment = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="trainer_alerts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-triggered_on"]

    def __str__(self):
        return f"Alerte {self.severity} {self.category} - {self.trainer}"