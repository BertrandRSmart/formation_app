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

    def __str__(self) -> str:
        return self.title


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

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


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
        max_digits=4,          # ex: 20.00 => 4 chiffres au total
        decimal_places=2,      # 2 chiffres après la virgule
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

    price_ht = models.DecimalField(
        "Prix formation HT",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    

    def outlook_compose_link(self):
        """
        Ouvre Outlook Web avec un évènement pré-rempli.
        Ensuite tu cliques "Réunion Teams" dans Outlook/Teams, tu enregistres,
        puis tu colles le lien dans `teams_meeting_url`.
        """
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
        """
        Langue par défaut si on ne stocke pas en DB.
        On part sur FR, et on pourra choisir EN via le bouton (paramètre POST).
        """
        return "fr"

    def invitation_location_label(self) -> str:
        """
        Libellé lieu à afficher sur la convocation.
        - Si chez le client : adresse client
        - Sinon : salle + éventuellement adresse salle
        """
        if self.on_client_site:
            return (self.client_address or "").strip()
        if self.room:
            # On combine nom + location si disponible
            loc = (self.room.location or "").strip()
            return f"{self.room.name}{' — ' + loc if loc else ''}"
        return ""

    def invitation_schedule_am(self) -> str:
        return "09:00–12:00"

    def invitation_schedule_pm(self) -> str:
        return "13:30–16:30"

    def invitation_schedule_full(self) -> str:
        return f"{self.invitation_schedule_am()} puis {self.invitation_schedule_pm()}"

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

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.reference} - {self.training} - {self.client} ({self.start_date})"

    def clean(self):
        if self.on_client_site:
            if not (self.client_address or "").strip():
                raise ValidationError("Adresse obligatoire si la formation est chez le client.")
        else:
            if not self.room_id:
                raise ValidationError("Salle obligatoire si la formation n'est pas chez le client.")


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
    role = models.CharField(max_length=150)  # "qualité" (ex: RH, Manager, etc.)
    email = models.EmailField()
    company_service = models.CharField(max_length=200)  # Service/Société
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("session", "participant")

    def clean(self):
        super().clean()
        # ✅ plus de limite de places (aucune validation de capacité)
        return

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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
        # Auto-fill trainer depuis la session si manquant
        if not self.trainer_id and getattr(self.session, "trainer_id", None):
            self.trainer_id = self.session.trainer_id

        # ✅ Sync référence avec la session
        if self.session_id:
            self.reference = (getattr(self.session, "reference", "") or "").strip()
            
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        ref = getattr(self.session, "reference", "") or f"Session #{self.session_id}"
        return f"Contrat Mercure - {ref}"

    @property
    def due_date(self):
        """Date cible = J-30 avant start_date"""
        start = getattr(self.session, "start_date", None)
        if not start:
            return None
        return start - timedelta(days=30)

    @property
    def is_due_soon(self) -> bool:
        """
        True si on est à <= 30 jours de la session et contrat pas envoyé/signé.
        """
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

    payment_alert_closed = models.BooleanField("Alerte paiement fermée", default=False)

    """
    Factures formateurs Mercure (suivi 60 jours à partir de la réception)
    """
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

    document_path = models.CharField(
    "Chemin facture (interne)",
    max_length=500,
    blank=True,
    default="",
    )

    from django.views.decorators.http import require_POST
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib.admin.views.decorators import staff_member_required

    @staff_member_required
    @require_POST
    def dismiss_mercure_invoice_alert(request, invoice_id: int):
        inv = get_object_or_404(MercureInvoice, pk=invoice_id)
        inv.payment_alert_closed = True
        inv.save(update_fields=["payment_alert_closed"])
        return redirect("trainings:home")

    reference = models.CharField(max_length=120, blank=True, default="")
    document_path = models.CharField("Chemin facture (interne)", max_length=500, blank=True, default="")
    amount_ht = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )

    # ⚠️ null/blank pour éviter les prompts makemigrations si tu as déjà des lignes
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

from django.core.validators import MinValueValidator


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