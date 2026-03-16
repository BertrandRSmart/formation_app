# trainings/models.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from django.utils.html import format_html


# =========================================================
# Référentiels
# =========================================================

class Client(models.Model):
    name = models.CharField(max_length=200)
    is_partner = models.BooleanField("Partenaire", default=False)
    country = models.CharField("Pays", max_length=120, blank=True, default="")

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=200, blank=True)

    def __str__(self) -> str:
        return self.name


class TrainingType(models.Model):
    name = models.CharField(max_length=120)

    def __str__(self) -> str:
        return self.name


class Training(models.Model):
    title = models.CharField(max_length=200)
    training_type = models.ForeignKey(TrainingType, on_delete=models.PROTECT)
    default_days = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("1.0"))
    color = models.CharField(max_length=7, default="#3b82f6")  # format #RRGGBB

    # =========================
    # Tarifs de référence
    # =========================
    session_price_ht = models.DecimalField(
        "Tarif session HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    participant_price_ht = models.DecimalField(
        "Tarif participant HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    partner_session_price_ht = models.DecimalField(
        "Tarif session partenaire HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    partner_participant_price_ht = models.DecimalField(
        "Tarif participant partenaire HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    def __str__(self) -> str:
        return self.title

    def get_session_price_ht(self, is_partner: bool = False) -> Decimal:
        if is_partner and self.partner_session_price_ht is not None:
            return self.partner_session_price_ht
        return self.session_price_ht or Decimal("0.00")

    def get_participant_price_ht(self, is_partner: bool = False) -> Decimal:
        if is_partner and self.partner_participant_price_ht is not None:
            return self.partner_participant_price_ht
        return self.participant_price_ht or Decimal("0.00")


# =========================================================
# Formateurs
# =========================================================

class Trainer(models.Model):
    PRODUCT_MERCURE = "MERCURE"
    PRODUCT_ARGONOS = "ARGONOS"

    PRODUCT_CHOICES = [
        (PRODUCT_MERCURE, "Mercure"),
        (PRODUCT_ARGONOS, "ArgonOS"),
    ]

    PLATFORMS = (
        ("ARGONOS", "ArgonOS"),
        ("MERCURE", "Mercure"),
    )
    platform = models.CharField(max_length=16, choices=PLATFORMS, default="ARGONOS")

    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)

    product = models.CharField(
        "Produit",
        max_length=20,
        choices=PRODUCT_CHOICES,
        default=PRODUCT_ARGONOS,
    )

    email = models.EmailField(blank=True)

    # =========================
    # AJOUT PLAN DE CHARGE
    # =========================
    is_active = models.BooleanField("Actif", default=True)
    workload_percent = models.DecimalField(
        "Capacité disponible (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# =========================================================
# Plan de charge - absences / charges
# =========================================================

class TrainerAbsenceType(models.TextChoices):
    VACATION = "VACATION", "Congés"
    RTT = "RTT", "RTT"
    SICK = "SICK", "Maladie"
    UNAVAILABLE = "UNAVAILABLE", "Indisponible"
    INTERNAL = "INTERNAL", "Réservé interne"


class TrainerAbsence(models.Model):
    trainer = models.ForeignKey(
        Trainer,
        on_delete=models.CASCADE,
        related_name="absences",
    )
    absence_type = models.CharField(
        "Type d'absence",
        max_length=20,
        choices=TrainerAbsenceType.choices,
        default=TrainerAbsenceType.VACATION,
    )
    start_date = models.DateField("Date de début")
    end_date = models.DateField("Date de fin")
    days_count = models.DecimalField(
        "Nombre de jours",
        max_digits=4,
        decimal_places=1,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0.5"))],
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start_date", "trainer__last_name", "trainer__first_name")
        verbose_name = "Absence formateur"
        verbose_name_plural = "Absences formateurs"

    def __str__(self):
        return (
            f"{self.trainer} - {self.get_absence_type_display()} "
            f"({self.start_date} → {self.end_date})"
        )

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("La date de fin ne peut pas être antérieure à la date de début.")


class TrainerWorkloadType(models.TextChoices):
    PREPARATION = "PREPARATION", "Préparation"
    PROJECT = "PROJECT", "Projet transverse"
    QA = "QA", "QA / Documentation"
    MEETING = "MEETING", "Réunion"
    SUPPORT = "SUPPORT", "Support"
    TRAVEL = "TRAVEL", "Déplacement"
    OTHER = "OTHER", "Autre"


class TrainerWorkloadEntryStatus(models.TextChoices):
    FORECAST = "FORECAST", "Prévisionnel"
    CONFIRMED = "CONFIRMED", "Confirmé"
    DONE = "DONE", "Réalisé"
    CANCELED = "CANCELED", "Annulé"


class TrainerWorkloadEntry(models.Model):
    trainer = models.ForeignKey(
        Trainer,
        on_delete=models.CASCADE,
        related_name="workload_entries",
    )
    workload_type = models.CharField(
        "Type de charge",
        max_length=20,
        choices=TrainerWorkloadType.choices,
        default=TrainerWorkloadType.OTHER,
    )
    title = models.CharField("Intitulé", max_length=200)
    start_date = models.DateField("Date de début")
    end_date = models.DateField("Date de fin")
    days_count = models.DecimalField(
        "Nombre de jours",
        max_digits=4,
        decimal_places=1,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0.5"))],
    )
    status = models.CharField(
        "Statut",
        max_length=20,
        choices=TrainerWorkloadEntryStatus.choices,
        default=TrainerWorkloadEntryStatus.FORECAST,
    )
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("start_date", "trainer__last_name", "trainer__first_name")
        verbose_name = "Charge formateur"
        verbose_name_plural = "Charges formateurs"

    def __str__(self):
        return f"{self.trainer} - {self.title}"

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("La date de fin ne peut pas être antérieure à la date de début.")


# =========================================================
# Sessions
# =========================================================

class SessionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PLANNED = "PLANNED", "Planifiée"
    CONFIRMED = "CONFIRMED", "Confirmée"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    CLOSED = "CLOSED", "Clôturée"
    CANCELED = "CANCELED", "Annulée"


class WorkEnvironment(models.TextChoices):
    PSFORMATION = "PSFormation", "PSFormation"
    PSFORMATIONMID = "PSFormationMid", "PSFormationMid"


class SessionBillingMode(models.TextChoices):
    COLLECTIVE = "COLLECTIVE", "Inscription collective"
    INDIVIDUAL = "INDIVIDUAL", "Inscriptions individuelles"


class Session(models.Model):
    reference = models.CharField(max_length=50, blank=True, default="")

    on_client_site = models.BooleanField(default=False)
    client_address = models.CharField(max_length=300, blank=True, default="")

    training_type = models.ForeignKey(TrainingType, on_delete=models.PROTECT)
    training = models.ForeignKey(Training, on_delete=models.PROTECT)
    client = models.ForeignKey(Client, on_delete=models.PROTECT)

    trainer = models.ForeignKey(
        Trainer,
        on_delete=models.PROTECT,
        related_name="primary_sessions",
    )
    backup_trainer = models.ForeignKey(
        Trainer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="backup_sessions",
    )

    room = models.ForeignKey(Room, on_delete=models.PROTECT, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    days_count = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("1.0"))
    status = models.CharField(
        max_length=20,
        choices=SessionStatus.choices,
        default=SessionStatus.DRAFT,
    )

    notes = models.TextField(blank=True)

    # =========================
    # Facturation
    # =========================
    billing_mode = models.CharField(
        "Mode d'inscription",
        max_length=20,
        choices=SessionBillingMode.choices,
        default=SessionBillingMode.COLLECTIVE,
    )

    is_abroad = models.BooleanField("Formation à l'étranger", default=False)

    applied_session_price_ht = models.DecimalField(
        "Tarif session appliqué HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    applied_participant_price_ht = models.DecimalField(
        "Tarif participant par défaut appliqué HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    training_price_ht = models.DecimalField(
        "Prix formation HT",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    travel_fee_ht = models.DecimalField(
        "Frais de déplacement HT",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    price_ht = models.DecimalField(
        "Prix total HT",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    # Plan B (sans Entra): lien Teams collé manuellement après création Outlook/Teams
    teams_meeting_url = models.URLField("Lien Teams", blank=True, default="")
    participants_invited_at = models.DateTimeField(
        "Invitations participants envoyées le",
        null=True,
        blank=True,
    )

    # Suivi administratif
    software_version = models.CharField("Version du logiciel", max_length=50, blank=True, default="")
    work_environment = models.CharField(
        "Environnement de travail",
        max_length=20,
        choices=WorkEnvironment.choices,
        default=WorkEnvironment.PSFORMATION,
    )

    convocations_sent_at = models.DateField("Date d'envoi des convocations", null=True, blank=True)
    convocation_alert_closed = models.BooleanField("Alerte convocation fermée", default=False)

    report_sent_at = models.DateField("Date d'envoi du bilan", null=True, blank=True)
    accounting_sheets_sent_at = models.DateField("Date d'envoi feuilles compta", null=True, blank=True)

    # Clôture
    client_satisfaction = models.DecimalField(
        "Satisfaction client (/20)",
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
    )

    expected_participants = models.PositiveSmallIntegerField(
        "Nombre de participants prévu",
        default=0,
        editable=False,
    )
    present_count = models.PositiveSmallIntegerField(
        "Nombre de présents",
        default=0,
        editable=False,
    )

    @property
    def is_partner_pricing(self) -> bool:
        return bool(self.client_id and getattr(self.client, "is_partner", False))

    def __str__(self) -> str:
        return f"{self.reference} - {self.training} - {self.client} ({self.start_date})"

    def clean(self):
        super().clean()

        if self.on_client_site:
            if not (self.client_address or "").strip():
                raise ValidationError("Adresse obligatoire si la formation est chez le client.")
        else:
            if not self.room_id:
                raise ValidationError("Salle obligatoire si la formation n'est pas chez le client.")

        if not self.training_id:
            return

        is_partner = self.is_partner_pricing
        session_price = self.training.get_session_price_ht(is_partner=is_partner)
        participant_price = self.training.get_participant_price_ht(is_partner=is_partner)

        if self.billing_mode == SessionBillingMode.COLLECTIVE:
            if session_price <= Decimal("0.00"):
                raise ValidationError(
                    "Aucun tarif session HT n'est défini pour cette formation dans ce mode de tarification."
                )

        elif self.billing_mode == SessionBillingMode.INDIVIDUAL:
            if participant_price <= Decimal("0.00"):
                raise ValidationError(
                    "Aucun tarif participant HT n'est défini pour cette formation dans ce mode de tarification."
                )

        if self.is_abroad and (self.travel_fee_ht or Decimal("0.00")) <= Decimal("0.00"):
            raise ValidationError(
                "Une session à l'étranger doit avoir un forfait de déplacement HT renseigné."
            )

    def outlook_compose_link(self):
        if not self.start_date or not self.end_date:
            return "Dates non renseignées"

        start_dt = datetime.combine(self.start_date, time(9, 0))
        end_dt = datetime.combine(self.end_date, time(17, 0))

        subject = f"{self.training.title} — {self.client.name}"
        location = self.client_address if self.on_client_site else (self.room.name if self.room else "")

        body = (
            f"Formation : {self.training.title}\n"
            f"Client : {self.client.name}\n"
            f"Référence : {self.reference}\n"
            f"Formateur : {self.trainer}\n"
            f"Backup : {self.backup_trainer or ''}\n"
            f"Salle / Adresse : {location}\n\n"
            f"Notes :\n{self.notes or ''}\n\n"
            f"➡️ Active la réunion Teams dans Outlook, puis colle le lien Teams dans l'application."
        )

        params = {
            "subject": subject,
            "startdt": start_dt.isoformat(),
            "enddt": end_dt.isoformat(),
            "location": location,
            "body": body,
        }

        url = "https://outlook.office.com/calendar/0/deeplink/compose?" + urlencode(params)

        return format_html(
            '<a href="{}" target="_blank">Créer l’événement Outlook</a>',
            url
        )

    outlook_compose_link.short_description = "Lien Outlook"

    # --- Invitations helpers (HTML -> PDF) ---------------------------------

    def invitation_language_default(self) -> str:
        return "fr"

    def invitation_location_label(self) -> str:
        if self.on_client_site:
            return (self.client_address or "").strip()
        if self.room:
            loc = (self.room.location or "").strip()
            return f"{self.room.name}{' — ' + loc if loc else ''}"
        return ""

    def invitation_schedule_am(self) -> str:
        return "09:00–12:00"

    def invitation_schedule_pm(self) -> str:
        return "13:30–16:30"

    def invitation_schedule_full(self) -> str:
        return f"{self.invitation_schedule_am()} puis {self.invitation_schedule_pm()}"

    def apply_pricing_from_training(self, save: bool = False) -> None:
        """
        Copie les tarifs de référence depuis la formation vers la session.
        - collective : snapshot session
        - individual : snapshot participant par défaut
        """
        if not self.training_id:
            return

        is_partner = self.is_partner_pricing

        self.applied_session_price_ht = self.training.get_session_price_ht(is_partner=is_partner)
        self.applied_participant_price_ht = self.training.get_participant_price_ht(is_partner=is_partner)

        if self.billing_mode == SessionBillingMode.COLLECTIVE:
            self.training_price_ht = self.applied_session_price_ht or Decimal("0.00")
            self.price_ht = (self.training_price_ht or Decimal("0.00")) + (self.travel_fee_ht or Decimal("0.00"))

        if save and self.pk:
            self.save(update_fields=[
                "applied_session_price_ht",
                "applied_participant_price_ht",
                "training_price_ht",
                "price_ht",
            ])

    def update_participant_counters(self, save: bool = False) -> None:
        regs = self.registrations.all()
        self.expected_participants = regs.count()
        self.present_count = regs.filter(status=RegistrationStatus.PRESENT).count()

        if save and self.pk:
            self.save(update_fields=["expected_participants", "present_count"])

    def recalculate_prices(self, save: bool = True) -> None:
        """
        Recalcule :
        - training_price_ht
        - price_ht
        - compteurs participants
        """
        self.update_participant_counters(save=False)

        if self.billing_mode == SessionBillingMode.COLLECTIVE:
            if self.applied_session_price_ht is None:
                self.apply_pricing_from_training(save=False)
            self.training_price_ht = self.applied_session_price_ht or Decimal("0.00")

        else:
            total_training = Decimal("0.00")
            for reg in self.registrations.select_related("participant", "participant__client"):
                reg.compute_billed_amount_ht(save=False)
                total_training += reg.billed_amount_ht or Decimal("0.00")

            self.training_price_ht = total_training

        self.price_ht = (self.training_price_ht or Decimal("0.00")) + (self.travel_fee_ht or Decimal("0.00"))

        if save and self.pk:
            self.save(update_fields=[
                "expected_participants",
                "present_count",
                "training_price_ht",
                "price_ht",
            ])

    def save(self, *args, **kwargs):
        # auto-fill training_type depuis training si besoin
        if self.training and not self.training_type_id:
            self.training_type = self.training.training_type

        # détecter si start_date change (pour recalculer / rouvrir l'alerte)
        old_start_date = None
        if self.pk:
            old_start_date = (
                Session.objects.filter(pk=self.pk)
                .values_list("start_date", flat=True)
                .first()
            )

        if self.start_date:
            computed = self.start_date - timedelta(days=16)

            if not self.convocations_sent_at:
                self.convocations_sent_at = computed
            elif old_start_date and old_start_date != self.start_date:
                self.convocations_sent_at = computed
                self.convocation_alert_closed = False

        # snapshot tarif si non défini
        if self.training_id:
            if self.applied_session_price_ht is None:
                self.applied_session_price_ht = self.training.get_session_price_ht(
                    is_partner=self.is_partner_pricing
                )
            if self.applied_participant_price_ht is None:
                self.applied_participant_price_ht = self.training.get_participant_price_ht(
                    is_partner=self.is_partner_pricing
                )

        # calcul immédiat si collectif
        if self.billing_mode == SessionBillingMode.COLLECTIVE:
            self.training_price_ht = self.applied_session_price_ht or Decimal("0.00")
            self.price_ht = (self.training_price_ht or Decimal("0.00")) + (self.travel_fee_ht or Decimal("0.00"))

        super().save(*args, **kwargs)


# =========================================================
# Participants / inscriptions
# =========================================================

class Referrer(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="referrers",
    )

    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    role = models.CharField(max_length=150)
    email = models.EmailField()
    company_service = models.CharField(max_length=200)
    service_address = models.TextField("Adresse du service", blank=True)

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name} - {self.company_service}"


class Participant(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="participants",
    )

    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    email = models.EmailField()
    company_service = models.CharField(max_length=200, blank=True, default="")

    referrer = models.ForeignKey(
        Referrer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participants",
    )

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class RegistrationStatus(models.TextChoices):
    INVITED = "INVITED", "Invité"
    REGISTERED = "REGISTERED", "Inscrit"
    CONFIRMED = "CONFIRMED", "Confirmé"
    PRESENT = "PRESENT", "Présent"
    ABSENT = "ABSENT", "Absent"
    CANCELED = "CANCELED", "Annulé"


class RegistrationBillingRate(models.IntegerChoices):
    ZERO = 0, "Annulation 0%"
    THIRTY = 30, "Annulation 30%"
    FULL = 100, "Facturation 100%"


class Registration(models.Model):
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="registrations",
    )

    status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.INVITED,
    )

    is_free = models.BooleanField("Place offerte", default=False)

    canceled_at = models.DateField(
        "Date d'annulation",
        null=True,
        blank=True,
    )

    billing_rate_percent = models.PositiveSmallIntegerField(
        "Taux de facturation (%)",
        choices=RegistrationBillingRate.choices,
        default=RegistrationBillingRate.FULL,
    )

    applied_unit_price_ht = models.DecimalField(
        "Tarif participant appliqué HT",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    billed_amount_ht = models.DecimalField(
        "Montant facturable HT",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("session", "participant")

    @property
    def participant_client(self):
        return getattr(self.participant, "client", None) or getattr(self.session, "client", None)

    @property
    def participant_is_partner(self) -> bool:
        client = self.participant_client
        return bool(client and getattr(client, "is_partner", False))

    def apply_cancellation_policy(self) -> None:
        """
        Politique :
        - > 30 jours : 0%
        - 15 à 30 jours : 30%
        - < 15 jours : 100%
        """
        if self.status != RegistrationStatus.CANCELED:
            return

        if not self.canceled_at:
            self.canceled_at = timezone.localdate()

        if not self.session.start_date:
            self.billing_rate_percent = RegistrationBillingRate.FULL
            return

        days_before = (self.session.start_date - self.canceled_at).days

        if days_before > 30:
            self.billing_rate_percent = RegistrationBillingRate.ZERO
        elif 15 <= days_before <= 30:
            self.billing_rate_percent = RegistrationBillingRate.THIRTY
        else:
            self.billing_rate_percent = RegistrationBillingRate.FULL

    def compute_billed_amount_ht(self, save: bool = False) -> Decimal:
        if self.session.billing_mode == SessionBillingMode.COLLECTIVE:
            self.billed_amount_ht = Decimal("0.00")
        else:
            if (
                self.applied_unit_price_ht is None
                or self.applied_unit_price_ht <= Decimal("0.00")
            ):
                session_price = self.session.applied_participant_price_ht
                if session_price is not None and session_price > Decimal("0.00"):
                    self.applied_unit_price_ht = session_price
                elif self.session.training_id:
                    self.applied_unit_price_ht = self.session.training.get_participant_price_ht(
                        is_partner=self.participant_is_partner
                    )
                else:
                    self.applied_unit_price_ht = Decimal("0.00")

            unit_price = self.applied_unit_price_ht or Decimal("0.00")

            if self.is_free:
                self.billed_amount_ht = Decimal("0.00")
            else:
                rate = Decimal(self.billing_rate_percent or 0) / Decimal("100")
                self.billed_amount_ht = (unit_price * rate).quantize(Decimal("0.01"))

        if save and self.pk:
            self.save(update_fields=["applied_unit_price_ht", "billed_amount_ht"])

        return self.billed_amount_ht

    def clean(self):
        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.status == RegistrationStatus.CANCELED:
            self.apply_cancellation_policy()
        else:
            if not self.is_free:
                self.billing_rate_percent = RegistrationBillingRate.FULL

        if self.session_id:
            if (
                self.applied_unit_price_ht is None
                or self.applied_unit_price_ht <= Decimal("0.00")
            ):
                if (
                    self.session.applied_participant_price_ht is not None
                    and self.session.applied_participant_price_ht > Decimal("0.00")
                ):
                    self.applied_unit_price_ht = self.session.applied_participant_price_ht
                elif self.session.training_id:
                    self.applied_unit_price_ht = self.session.training.get_participant_price_ht(
                        is_partner=self.participant_is_partner
                    )

        self.compute_billed_amount_ht(save=False)

        super().save(*args, **kwargs)

        if self.session_id:
            self.session.recalculate_prices(save=True)

    def delete(self, *args, **kwargs):
        session = self.session
        super().delete(*args, **kwargs)
        if session:
            session.recalculate_prices(save=True)


# ==================================================================================
# Mercure — Contrats d’application + Factures
# ==================================================================================

class MercureContractStatus(models.TextChoices):
    TODO = "TODO", "À envoyer"
    SENT = "SENT", "Envoyé"
    SIGNED = "SIGNED", "Signé"
    CANCELLED = "CANCELLED", "Annulé"


class MercureInvoiceStatus(models.TextChoices):
    RECEIVED_ADMIN = "RECEIVED_ADMIN", "Reçue (Service admin)"
    WAITING_PROCESS = "WAITING_PROCESS", "En attente de traitement"
    PROCESSING = "PROCESSING", "En cours de traitement"
    VALIDATION = "VALIDATION", "En cours de validation"
    PAID = "PAID", "Payée"


class MercureContract(models.Model):
    """
    Contrat d'application Mercure (1 contrat par session Mercure)
    Objectif: suivi + alerte J-30 si non envoyé/signé.
    """
    session = models.OneToOneField(
        Session,
        on_delete=models.CASCADE,
        related_name="mercure_contract",
    )
    trainer = models.ForeignKey(
        Trainer,
        on_delete=models.PROTECT,
        related_name="mercure_contracts",
    )

    reference = models.CharField("Référence", max_length=50, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=MercureContractStatus.choices,
        default=MercureContractStatus.TODO,
    )

    sent_date = models.DateField(null=True, blank=True)
    signed_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def save(self, *args, **kwargs):
        if not self.trainer_id and getattr(self.session, "trainer_id", None):
            self.trainer_id = self.session.trainer_id

        if self.session_id:
            self.reference = (getattr(self.session, "reference", "") or "").strip()

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        ref = getattr(self.session, "reference", "") or f"Session #{self.session_id}"
        return f"Contrat Mercure - {ref}"

    @property
    def due_date(self):
        start = getattr(self.session, "start_date", None)
        if not start:
            return None
        return start - timedelta(days=30)

    @property
    def is_due_soon(self) -> bool:
        start = getattr(self.session, "start_date", None)
        if not start:
            return False
        today = timezone.localdate()
        if start < today:
            return False
        if (start - today).days > 30:
            return False
        return self.status in (MercureContractStatus.TODO,)


class MercureInvoice(models.Model):
    """
    Factures formateurs Mercure (suivi 60 jours à partir de la réception)
    """
    payment_alert_closed = models.BooleanField("Alerte paiement fermée", default=False)

    session = models.ForeignKey(
        Session,
        on_delete=models.PROTECT,
        related_name="mercure_invoices",
    )
    trainer = models.ForeignKey(
        Trainer,
        on_delete=models.PROTECT,
        related_name="mercure_invoices",
    )

    reference = models.CharField(max_length=120, blank=True, default="")
    document_path = models.CharField("Chemin facture (interne)", max_length=500, blank=True, default="")
    amount_ht = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    received_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=MercureInvoiceStatus.choices,
        default=MercureInvoiceStatus.RECEIVED_ADMIN,
    )

    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        ref = self.reference or "—"
        return f"Facture {ref} - {self.trainer}"

    @property
    def due_date(self):
        if not self.received_date:
            return None
        return self.received_date + timedelta(days=60)

    @property
    def is_overdue(self) -> bool:
        if self.status == MercureInvoiceStatus.PAID:
            return False
        due = self.due_date
        if not due:
            return False
        return timezone.localdate() > due


# ==================================================================================
# PARTNERS - DETAILS
# ===============================================================================

class PartnerContractPlan(models.Model):
    PLAN_SILVER = "silver"
    PLAN_GOLD = "gold"
    PLAN_PLATINUM = "platinum"

    PLAN_CHOICES = [
        (PLAN_SILVER, "Silver"),
        (PLAN_GOLD, "Gold"),
        (PLAN_PLATINUM, "Platinum"),
    ]

    name = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    label = models.CharField(max_length=50, blank=True)
    price_ht = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Partner contract plan"
        verbose_name_plural = "Partner contract plans"
        ordering = ["name"]

    def __str__(self):
        return self.label or self.get_name_display()


class PartnerContractPlanSeat(models.Model):
    plan = models.ForeignKey(
        PartnerContractPlan,
        on_delete=models.CASCADE,
        related_name="seat_rules",
    )
    training = models.ForeignKey(
        "Training",
        on_delete=models.CASCADE,
        related_name="partner_contract_rules",
    )
    included_seats = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Partner contract plan seat"
        verbose_name_plural = "Partner contract plan seats"
        unique_together = [("plan", "training")]
        ordering = ["plan", "training__title"]

    def __str__(self):
        return f"{self.plan} — {self.training} ({self.included_seats})"


class PartnerContract(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_DRAFT = "draft"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_DRAFT, "Draft"),
    ]

    partner = models.ForeignKey(
        "Client",
        on_delete=models.CASCADE,
        related_name="partner_contracts",
        limit_choices_to={"is_partner": True},
    )
    plan = models.ForeignKey(
        PartnerContractPlan,
        on_delete=models.PROTECT,
        related_name="partner_contracts",
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    price_ht_snapshot = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Partner contract"
        verbose_name_plural = "Partner contracts"
        ordering = ["-start_date", "partner__name"]

    def __str__(self):
        return f"{self.partner} — {self.plan}"

    @property
    def effective_price_ht(self):
        return self.price_ht_snapshot if self.price_ht_snapshot is not None else self.plan.price_ht

    def save(self, *args, **kwargs):
        if self.price_ht_snapshot is None and self.plan_id:
            self.price_ht_snapshot = self.plan.price_ht
        super().save(*args, **kwargs)
