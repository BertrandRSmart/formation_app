from decimal import Decimal

from django.contrib import admin, messages
from django import forms
from django.urls import reverse
from django.utils.html import format_html

from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .services.invitations import generate_invitations_for_session

from .models import MercureContract, MercureInvoice

from .models import (
    Client,
    Room,
    TrainingType,
    Training,
    Trainer,
    TrainerAbsence,
    TrainerWorkloadEntry,
    Session,
    Referrer,
    Participant,
    Registration,
    PartnerContractPlan,
    PartnerContractPlanSeat,
    PartnerContract,
)


# ---------------------------------------------------------
# Clients
# ---------------------------------------------------------
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "is_partner", "country")
    list_filter = ("is_partner", "country")
    search_fields = ("name", "country")


# ---------------------------------------------------------
# Enregistrements simples
# ---------------------------------------------------------
admin.site.register(Room)
admin.site.register(TrainingType)


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "participant",
        "status",
        "is_free",
        "billing_rate_percent",
        "applied_unit_price_ht",
        "billed_amount_ht",
        "canceled_at",
        "created_at",
    )
    list_filter = (
        "status",
        "is_free",
        "billing_rate_percent",
        "session__billing_mode",
        "session__training_type",
    )
    search_fields = (
        "participant__first_name",
        "participant__last_name",
        "participant__email",
        "session__reference",
        "session__training__title",
    )


@admin.register(Training)
class TrainingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "training_type",
        "session_price_ht",
        "participant_price_ht",
        "partner_session_price_ht",
        "partner_participant_price_ht",
    )
    list_filter = ("training_type",)
    search_fields = ("title", "training_type__name")

    fieldsets = (
        ("Informations générales", {
            "fields": (
                "title",
                "training_type",
                "default_days",
                "color",
            )
        }),
        ("Tarification standard", {
            "fields": (
                "session_price_ht",
                "participant_price_ht",
            )
        }),
        ("Tarification partenaire", {
            "fields": (
                "partner_session_price_ht",
                "partner_participant_price_ht",
            )
        }),
    )


# ---------------------------------------------------------
# Action admin - Convocations (PDF session + email participants)
# ---------------------------------------------------------
@admin.action(description="📩 Générer convocations (PDF) — FR+EN (wkhtmltopdf)")
def generate_session_invitations(modeladmin, request, queryset):
    ok = 0
    for s in queryset:
        try:
            base_url = request.build_absolute_uri("/")
            r_fr = generate_invitations_for_session(session=s, lang="fr", base_url=base_url)
            r_en = generate_invitations_for_session(session=s, lang="en", base_url=base_url)

            messages.success(
                request,
                f"{s.reference or s.id} : FR({len(r_fr.pdf_files)} PDF) + EN({len(r_en.pdf_files)} PDF) — dossier: {r_fr.folder_rel}"
            )
            ok += 1
        except Exception as e:
            messages.error(request, f"Erreur {s.reference or s.id} : {e}")

    if ok:
        messages.success(request, f"✅ Terminé pour {ok} session(s).")


# ---------------------------------------------------------
# Referrers
# ---------------------------------------------------------
@admin.register(Referrer)
class ReferrerAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email", "client", "service_address")
    search_fields = ("last_name", "first_name", "email", "client__name", "service_address")
    list_filter = ("client",)


# ---------------------------------------------------------
# Trainers
# ---------------------------------------------------------
@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "email",
        "product",
        "platform",
        "is_active",
        "workload_percent",
    )
    list_filter = ("product", "platform", "is_active")
    search_fields = ("last_name", "first_name", "email")


# ---------------------------------------------------------
# Participants (import/export + filtrage referrers par client)
# ---------------------------------------------------------
class ParticipantResource(resources.ModelResource):
    client = fields.Field(
        column_name="client",
        attribute="client",
        widget=ForeignKeyWidget(Client, "name"),
    )

    referrer = fields.Field(
        column_name="referrer_email",
        attribute="referrer",
        widget=ForeignKeyWidget(Referrer, "email"),
    )

    class Meta:
        model = Participant
        fields = ("id", "first_name", "last_name", "email", "company_service", "client", "referrer")
        export_order = ("id", "first_name", "last_name", "email", "company_service", "client", "referrer")
        skip_unchanged = True
        report_skipped = True
        import_id_fields = ("email",)


@admin.register(Participant)
class ParticipantAdmin(ImportExportModelAdmin):
    resource_class = ParticipantResource

    list_display = ("client", "first_name", "last_name", "email", "company_service", "referrer")
    search_fields = (
        "first_name",
        "last_name",
        "email",
        "company_service",
        "client__name",
        "referrer__first_name",
        "referrer__last_name",
        "referrer__email",
    )

    list_filter = (
        "client",
        "company_service",
        ("registrations__session__training_type", admin.RelatedOnlyFieldListFilter),
        ("registrations__session", admin.RelatedOnlyFieldListFilter),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).distinct()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj=obj, **kwargs)

        if "referrer" in form.base_fields:
            if obj and obj.client_id:
                form.base_fields["referrer"].queryset = Referrer.objects.filter(client_id=obj.client_id)
            else:
                form.base_fields["referrer"].queryset = Referrer.objects.none()

        return form


# ---------------------------------------------------------
# Sessions
# ---------------------------------------------------------
class SessionAdminForm(forms.ModelForm):
    class Meta:
        model = Session
        exclude = ("expected_participants", "present_count")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.instance.training_type_id:
            self.fields["training"].queryset = Training.objects.filter(
                training_type_id=self.instance.training_type_id
            )

        for fname in (
            "applied_session_price_ht",
            "applied_participant_price_ht",
            "training_price_ht",
            "price_ht",
        ):
            if fname in self.fields:
                self.fields[fname].required = False
                self.fields[fname].widget.attrs["readonly"] = True
                self.fields[fname].widget.attrs["style"] = (
                    "background:rgba(255,255,255,.06);"
                    "color:#fff;"
                    "font-weight:900;"
                )

    def clean(self):
        cleaned = super().clean()

        training = cleaned.get("training")
        client = cleaned.get("client")
        billing_mode = cleaned.get("billing_mode")
        travel_fee_ht = cleaned.get("travel_fee_ht") or Decimal("0.00")

        if training:
            is_partner = bool(client and getattr(client, "is_partner", False))

            cleaned["applied_session_price_ht"] = training.get_session_price_ht(
                is_partner=is_partner
            )
            cleaned["applied_participant_price_ht"] = training.get_participant_price_ht(
                is_partner=is_partner
            )

            if billing_mode == "COLLECTIVE":
                training_price = cleaned["applied_session_price_ht"] or Decimal("0.00")
                cleaned["training_price_ht"] = training_price
                cleaned["price_ht"] = training_price + travel_fee_ht

            elif billing_mode == "INDIVIDUAL":
                existing_training_price = cleaned.get("training_price_ht") or Decimal("0.00")
                cleaned["training_price_ht"] = existing_training_price
                cleaned["price_ht"] = existing_training_price + travel_fee_ht

        return cleaned


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    form = SessionAdminForm
    actions = [generate_session_invitations]

    list_display = (
        "reference",
        "training_type",
        "training",
        "client",
        "billing_mode",
        "is_abroad",
        "start_date",
        "end_date",
        "trainer",
        "room",
        "on_client_site",
        "status",
        "expected_participants",
        "present_count",
        "presence_gauge",
        "client_satisfaction",
        "bulk_registrations_link",
        "training_price_ht",
        "travel_fee_ht",
        "price_ht",
    )

    list_filter = (
        "training_type",
        "client",
        "client__is_partner",
        "billing_mode",
        "is_abroad",
        "trainer",
        "room",
        "on_client_site",
        "status",
        "convocations_sent_at",
        "report_sent_at",
        "accounting_sheets_sent_at",
    )

    search_fields = (
        "reference",
        "client__name",
        "training__title",
        "trainer__last_name",
        "trainer__first_name",
        "software_version",
    )

    ordering = ("-start_date",)

    readonly_fields = (
        "created_at",
        "expected_participants",
        "present_count",
        "bulk_registrations_button",
        "create_teams_button",
    )

    fieldsets = (
        ("Informations session", {
            "fields": (
                "bulk_registrations_button",
                "create_teams_button",
                "reference",
                "status",
                "training_type",
                "training",
                "client",
                "billing_mode",
                "start_date",
                "end_date",
                "days_count",
                "trainer",
                "backup_trainer",
            )
        }),
        ("Tarification", {
            "fields": (
                "applied_session_price_ht",
                "applied_participant_price_ht",
                "training_price_ht",
                "travel_fee_ht",
                "price_ht",
            )
        }),
        ("Lieu", {
            "fields": (
                "on_client_site",
                "client_address",
                "room",
                "is_abroad",
            )
        }),
        ("Suivi administratif", {
            "fields": (
                "software_version",
                "work_environment",
                "convocations_sent_at",
                "teams_meeting_url",
            )
        }),
        ("Clôture de la session", {
            "fields": (
                "expected_participants",
                "present_count",
                "client_satisfaction",
                "report_sent_at",
                "accounting_sheets_sent_at",
            )
        }),
        ("Notes", {
            "fields": ("notes",)
        }),
        ("Métadonnées", {
            "fields": ("created_at",)
        }),
    )

    @admin.display(description="Réunion Teams")
    def create_teams_button(self, obj):
        if not obj or not obj.pk:
            return "Enregistre la session d'abord."
        return format_html(
            '<a class="button" style="padding:8px 12px; font-weight:600;" href="{}" target="_blank">📅 Créer réunion Teams</a>',
            obj.outlook_compose_link()
        )

    def save_model(self, request, obj, form, change):
        obj.apply_pricing_from_training(save=False)
        super().save_model(request, obj, form, change)
        obj.recalculate_prices(save=True)

    @admin.display(description="Inscriptions en masse")
    def bulk_registrations_button(self, obj):
        if not obj or not obj.pk:
            return "Enregistre la session d'abord pour activer le bouton."
        url = reverse("bulk_registrations_admin") + f"?session_id={obj.id}"
        return format_html(
            '<a class="button" style="padding:8px 12px; font-weight:600;" href="{}">➕ Inscriptions en masse</a>',
            url
        )

    @admin.display(description="Bulk")
    def bulk_registrations_link(self, obj):
        url = reverse("bulk_registrations_admin") + f"?session_id={obj.id}"
        return format_html('<a class="button" href="{}">Bulk</a>', url)

    @admin.display(description="Jauge présence")
    def presence_gauge(self, obj):
        expected = obj.expected_participants or 0
        present = obj.present_count or 0

        if expected <= 0:
            return "—"

        percent = int(min(100, (present / expected) * 100))

        return format_html(
            """
            <div style="min-width:180px">
              <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
                <span>{}/{} </span><span>{}%</span>
              </div>
              <div style="height:10px; border:1px solid #ccc; border-radius:6px; overflow:hidden;">
                <div style="height:10px; width:{}%; background:#3b82f6;"></div>
              </div>
            </div>
            """,
            present, expected, percent, percent
        )

    class Media:
        js = (
            "trainings/session_admin.js",
            "trainings/session_location_admin.js",
        )


# ================================================================
# Gestion suivi prestations formateurs Mercure
# ================================================================
@admin.register(MercureContract)
class MercureContractAdmin(admin.ModelAdmin):
    list_display = ("session", "trainer", "status", "sent_date", "signed_date", "created_at")
    list_filter = ("status", "trainer")
    search_fields = ("session__reference", "trainer__first_name", "trainer__last_name")


@admin.register(MercureInvoice)
class MercureInvoiceAdmin(admin.ModelAdmin):
    list_display = ("reference", "trainer", "session", "amount_ht", "received_date", "status", "paid_date")
    list_filter = ("status", "trainer")
    search_fields = ("reference", "session__reference", "trainer__first_name", "trainer__last_name")


# ================================================================
# Gestion partners
# ================================================================
class PartnerContractPlanSeatInline(admin.TabularInline):
    model = PartnerContractPlanSeat
    extra = 1


@admin.register(PartnerContractPlan)
class PartnerContractPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "label", "price_ht", "is_active")
    list_filter = ("is_active", "name")
    search_fields = ("name", "label")
    inlines = [PartnerContractPlanSeatInline]


@admin.register(PartnerContract)
class PartnerContractAdmin(admin.ModelAdmin):
    list_display = ("partner", "plan", "status", "start_date", "end_date", "price_ht_snapshot")
    list_filter = ("status", "plan")
    search_fields = ("partner__name",)


# ================================================================
# Plan de charge formateurs
# ================================================================
@admin.register(TrainerAbsence)
class TrainerAbsenceAdmin(admin.ModelAdmin):
    list_display = (
        "trainer",
        "absence_type",
        "start_date",
        "end_date",
        "days_count",
        "created_at",
    )
    list_filter = (
        "absence_type",
        "trainer__product",
        "trainer__platform",
        "start_date",
        "end_date",
    )
    search_fields = (
        "trainer__first_name",
        "trainer__last_name",
        "trainer__email",
        "notes",
    )
    ordering = ("-start_date", "trainer__last_name", "trainer__first_name")


@admin.register(TrainerWorkloadEntry)
class TrainerWorkloadEntryAdmin(admin.ModelAdmin):
    list_display = (
        "trainer",
        "title",
        "workload_type",
        "status",
        "start_date",
        "end_date",
        "days_count",
        "created_at",
    )
    list_filter = (
        "workload_type",
        "status",
        "trainer__product",
        "trainer__platform",
        "start_date",
        "end_date",
    )
    search_fields = (
        "title",
        "notes",
        "trainer__first_name",
        "trainer__last_name",
        "trainer__email",
    )
    ordering = ("-start_date", "trainer__last_name", "trainer__first_name")