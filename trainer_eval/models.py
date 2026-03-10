from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class EvaluationDecision(models.TextChoices):
    BEGINNER = "beginner", "Débutant"
    INTERMEDIATE = "intermediate", "Intermédiaire"
    EXPERT = "expert", "Expert"
    NA = "na", "Non concerné"


class InternalEvaluation(models.Model):
    """
    Évaluation interne : score core / specific / total
    + score grille (rubric) + décision
    """
    evaluated_on = models.DateField(default=timezone.now)

    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.PROTECT,
        related_name="internal_evaluations",
    )
    training = models.ForeignKey(
        "trainings.Training",
        on_delete=models.PROTECT,
        related_name="internal_evaluations",
    )

    rubric = models.ForeignKey(
        "trainer_eval.EvaluationRubric",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )

    rubric_score_total = models.PositiveIntegerField(default=0)
    rubric_score_max = models.PositiveIntegerField(default=0)
    rubric_score_100 = models.PositiveSmallIntegerField(default=0)

    core_score_20 = models.PositiveIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(20)]
    )
    specific_score_10 = models.PositiveIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(10)]
    )
    total_score_30 = models.PositiveIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(30)]
    )

    decision = models.CharField(
        max_length=20,
        choices=EvaluationDecision.choices,
        default=EvaluationDecision.BEGINNER,
    )

    strengths = models.TextField(blank=True)
    improvements = models.TextField(blank=True)

    manager_comment = models.TextField(blank=True)
    trainer_comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="internal_evaluations_created",
    )

    class Meta:
        ordering = ["-evaluated_on", "-id"]

    def recompute_rubric_scores(self, commit=False):
        scores = self.criterion_scores.select_related("criterion").all()

        total = 0
        max_total = 0

        for s in scores:
            c = s.criterion
            w = int(c.weight or 1)
            total += int(s.score or 0) * w
            max_total += int(c.max_score or 5) * w

        self.rubric_score_total = total
        self.rubric_score_max = max_total
        self.rubric_score_100 = int(round((total / max_total) * 100)) if max_total else 0

        # Si pas de critères => on ne touche pas à la décision
        if scores.exists():
            s100 = self.rubric_score_100
            if s100 < 50:
                self.decision = EvaluationDecision.BEGINNER
            elif s100 < 75:
                self.decision = EvaluationDecision.INTERMEDIATE
            else:
                self.decision = EvaluationDecision.EXPERT

        if commit:
            self.save(update_fields=[
                "rubric_score_total",
                "rubric_score_max",
                "rubric_score_100",
                "decision",
            ])

    def save(self, *args, **kwargs):
        self.total_score_30 = int(self.core_score_20 or 0) + int(self.specific_score_10 or 0)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.trainer} — {self.training} — {self.evaluated_on}"

class ContributionKind(models.TextChoices):
    DOC = "doc", "Documentation"
    MENTORING = "mentoring", "Mentoring"
    CONTENT = "content", "Contenu pédagogique"
    PROJECT = "project", "Projet transverse"
    FEEDBACK = "feedback", "Feedback produit"


class StrategicContribution(models.Model):
    """
    Contributions "stratégiques" (ex: doc, mentoring, contenu, etc.)
    pour logiques de prime/objectif.
    """
    date = models.DateField(default=timezone.now)
    trainer = models.ForeignKey("trainings.Trainer", on_delete=models.PROTECT, related_name="strategic_contributions")
    kind = models.CharField(max_length=20, choices=ContributionKind.choices)

    training = models.ForeignKey("trainings.Training", null=True, blank=True, on_delete=models.SET_NULL, related_name="strategic_contributions")
    description = models.TextField(blank=True)

    points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="strategic_contributions_created"
    )

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.trainer} — {self.get_kind_display()} — {self.date}"


class AlertSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class AlertStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACK = "ack", "Acknowledged"
    CLOSED = "closed", "Closed"


class TrainerAlert(models.Model):
    """
    Alertes issues d'indicateurs (qualité, retards, scores, etc.)
    """
    triggered_on = models.DateTimeField(default=timezone.now)

    trainer = models.ForeignKey("trainings.Trainer", on_delete=models.PROTECT, related_name="alerts")
    training = models.ForeignKey("trainings.Training", null=True, blank=True, on_delete=models.SET_NULL, related_name="trainer_alerts")

    severity = models.CharField(max_length=20, choices=AlertSeverity.choices, default=AlertSeverity.INFO)
    category = models.CharField(max_length=60, blank=True)  # ex: "Satisfaction", "Pédagogie", "Process"
    status = models.CharField(max_length=20, choices=AlertStatus.choices, default=AlertStatus.OPEN)

    metric = models.CharField(max_length=120, blank=True)   # ex: "CSAT", "Late start"
    value = models.CharField(max_length=120, blank=True)    # ex: "12/20", "15 min"

    manager_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-triggered_on", "-id"]

    def __str__(self) -> str:
        return f"{self.trainer} — {self.severity} — {self.status}"



# =========================================
# Grilles & critères (versionnés)
# =========================================

class EvaluationRubric(models.Model):
    """
    Une 'grille' d'évaluation pour une formation donnée et une version donnée.
    Exemple: Training=ArgonOS Initiation, version=2026.1
    """
    training = models.ForeignKey(
        "trainings.Training",
        on_delete=models.PROTECT,
        related_name="eval_rubrics",
    )
    version_label = models.CharField(max_length=40)  # ex: "2026.1" / "v8.2" / "H1-2026"
    is_active = models.BooleanField(default=True)

    title = models.CharField(max_length=140, blank=True)  # ex: "Rubric standard — 2026.1"
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("training", "version_label")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.training} — {self.version_label}"


class EvaluationCriterion(models.Model):
    """
    Un critère appartenant à une grille.
    On structure en sections pour garder ton approche 'très complète'.
    """
    class Section(models.TextChoices):
        PREP = "prep", "Préparation"
        WELCOME = "welcome", "Accueil"
        DELIVERY = "delivery", "Animation / Pédagogie"
        CONTENT = "content", "Contenu & messages clés"
        PRACTICE = "practice", "Pratique / ateliers"
        TIMING = "timing", "Timing & organisation"
        ADAPT = "adapt", "Adaptation & gestion imprévus"
        WRAP = "wrap", "Clôture & livrables"

    rubric = models.ForeignKey(
        EvaluationRubric,
        on_delete=models.CASCADE,
        related_name="criteria",
    )
    section = models.CharField(max_length=20, choices=Section.choices, default=Section.DELIVERY)

    label = models.CharField(max_length=220)               # ex: "Vérifie la salle et le matériel"
    description = models.TextField(blank=True)             # aide / exemples
    weight = models.PositiveSmallIntegerField(default=1)   # pour pondération future

    max_score = models.PositiveSmallIntegerField(default=5)  # 1..5 par défaut
    sort_order = models.PositiveSmallIntegerField(default=100)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("section", "sort_order", "id")

    def __str__(self):
        return f"[{self.get_section_display()}] {self.label}"


class EvaluationScore(models.Model):
    """
    La note d'un critère pour une évaluation donnée.
    """
    evaluation = models.ForeignKey(
        "trainer_eval.InternalEvaluation",
        on_delete=models.CASCADE,
        related_name="criterion_scores",
    )
    criterion = models.ForeignKey(
        EvaluationCriterion,
        on_delete=models.PROTECT,
        related_name="scores",
    )

    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)

    class Meta:
        unique_together = ("evaluation", "criterion")
        ordering = ("criterion__section", "criterion__sort_order", "id")

    def __str__(self):
        return f"{self.evaluation_id} — {self.criterion_id} = {self.score}"

from projects.models import ProjectCategory, Project, ProjectStep  # ou en string FK si tu préfères

class ProjectRubric(models.Model):
    """
    Grille d'évaluation pour contributions projets, versionnée.
    Peut être liée à une catégorie de projet (ou null = générique).
    """
    category = models.ForeignKey(
        "projects.ProjectCategory",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="project_rubrics",
    )
    version_label = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    title = models.CharField(max_length=140, blank=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("category", "version_label")
        ordering = ("-created_at",)

    def __str__(self):
        cat = self.category.name if self.category else "Générique"
        return f"{cat} — {self.version_label}"


class ProjectCriterion(models.Model):
    class Section(models.TextChoices):
        PREP = "prep", "Préparation"
        EXEC = "exec", "Exécution"
        COM = "com", "Communication"
        QUAL = "qual", "Qualité / livrables"
        RISK = "risk", "Risques / imprévus"
        WRAP = "wrap", "Clôture"

    rubric = models.ForeignKey(ProjectRubric, on_delete=models.CASCADE, related_name="criteria")
    section = models.CharField(max_length=20, choices=Section.choices, default=Section.EXEC)

    label = models.CharField(max_length=220)
    description = models.TextField(blank=True)

    weight = models.PositiveSmallIntegerField(default=1)
    max_score = models.PositiveSmallIntegerField(default=5)
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("section", "sort_order", "id")

    def __str__(self):
        return f"[{self.get_section_display()}] {self.label}"


class ProjectContributionEvaluation(models.Model):
    evaluated_on = models.DateField(default=timezone.now)

    trainer = models.ForeignKey(
        "trainings.Trainer",
        on_delete=models.PROTECT,
        related_name="project_contribution_evaluations",
    )

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="contribution_evaluations",
    )

    step = models.ForeignKey(
        "projects.ProjectStep",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contribution_evaluations",
    )

    rubric = models.ForeignKey(
        "trainer_eval.ProjectRubric",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )

    rubric_score_total = models.PositiveIntegerField(default=0)
    rubric_score_max = models.PositiveIntegerField(default=0)
    rubric_score_100 = models.PositiveSmallIntegerField(default=0)

    decision = models.CharField(
        max_length=20,
        choices=EvaluationDecision.choices,
        default=EvaluationDecision.BEGINNER,
    )

    strengths = models.TextField(blank=True)
    improvements = models.TextField(blank=True)
    manager_comment = models.TextField(blank=True)
    trainer_comment = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="project_contribution_evaluations_created",
    )

    class Meta:
        ordering = ["-evaluated_on", "-id"]

    def recompute_rubric_scores(self, commit=False):
        scores = self.criterion_scores.select_related("criterion").all()

        total = 0
        max_total = 0
        for s in scores:
            c = s.criterion
            w = int(c.weight or 1)
            total += int(s.score or 0) * w
            max_total += int(c.max_score or 5) * w

        self.rubric_score_total = total
        self.rubric_score_max = max_total
        self.rubric_score_100 = int(round((total / max_total) * 100)) if max_total else 0

        if scores.exists():
            s100 = self.rubric_score_100
            if s100 < 50:
                self.decision = EvaluationDecision.BEGINNER
            elif s100 < 75:
                self.decision = EvaluationDecision.INTERMEDIATE
            else:
                self.decision = EvaluationDecision.EXPERT

        if commit:
            self.save(update_fields=["rubric_score_total","rubric_score_max","rubric_score_100","decision"])

    def __str__(self):
        return f"{self.trainer} — {self.project} — {self.step or 'Étape ?'} — {self.evaluated_on}"


class ProjectScore(models.Model):
    evaluation = models.ForeignKey(
        "trainer_eval.ProjectContributionEvaluation",
        on_delete=models.CASCADE,
        related_name="criterion_scores",
    )
    criterion = models.ForeignKey(
        "trainer_eval.ProjectCriterion",
        on_delete=models.PROTECT,
        related_name="scores",
    )
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(5)])
    comment = models.TextField(blank=True)

    class Meta:
        unique_together = ("evaluation", "criterion")
        ordering = ("criterion__section", "criterion__sort_order", "id")