from django.contrib import admin, messages
from django import forms
from django.urls import reverse
from django.utils.html import format_html

from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .services.convocations import generate_and_send_session_convocation


from .models import (
    Client,
    Room,
    TrainingType,
    Training,
    Trainer,
    Session,
    Referrer,
    Participant,
    Registration,
)

# ---------------------------------------------------------
# Enregistrements simples
# ---------------------------------------------------------
admin.site.register(Client)
admin.site.register(Room)
admin.site.register(TrainingType)
admin.site.register(Training)
admin.site.register(Registration)

# ---------------------------------------------------------
# Action admin - Convocations (PDF session + email participants)
# ---------------------------------------------------------
@admin.action(description="📩 Générer + envoyer la convocation (PDF) aux participants")
def send_session_convocations(modeladmin, request, queryset):
    ok = 0
    for session in queryset:
        try:
            sent = generate_and_send_session_convocation(session)
            messages.success(
                request,
                f"{session.reference or session.id} : {sent} email(s) envoyé(s)."
            )
            ok += 1
        except Exception as e:
            messages.error(request, f"Erreur {session.reference or session.id} : {e}")
    if ok:
        messages.success(request, f"✅ Terminé pour {ok} session(s).")

# ---------------------------------------------------------
# Referrers
# ---------------------------------------------------------
@admin.register(Referrer)
class ReferrerAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email", "client")
    search_fields = ("last_name", "first_name", "email", "client__name")
    list_filter = ("client",)


# ---------------------------------------------------------
# Trainers
# ---------------------------------------------------------
@admin.register(Trainer)
class TrainerAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email", "product")  # adapte si tes champs ont d'autres noms
    list_filter = ("product",)
    search_fields = ("last_name", "first_name", "email")


# ---------------------------------------------------------
# Participants (import/export + filtrage referrers par client)
# ---------------------------------------------------------
class ParticipantResource(resources.ModelResource):
    # Clé étrangère Client via son nom
    client = fields.Field(
        column_name="client",
        attribute="client",
        widget=ForeignKeyWidget(Client, "name"),
    )

    # Clé étrangère Referrer via son email
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
        exclude = ("expected_participants", "present_count", "participants_count")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Filtrer les trainings selon le training_type (fiable en édition)
        if self.instance and self.instance.pk and self.instance.training_type_id:
            self.fields["training"].queryset = Training.objects.filter(
                training_type_id=self.instance.training_type_id
            )

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    form = SessionAdminForm

    actions = [send_session_convocations]

    list_display = (
        "reference",
        "training_type",
        "training",
        "client",
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
    )

    list_filter = (
        "training_type",
        "client",
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

    @admin.display(description="Réunion Teams")
    def create_teams_button(self, obj):
        if not obj or not obj.pk:
            return "Enregistre la session d'abord."
        return format_html(
            '<a class="button" style="padding:8px 12px; font-weight:600;" href="{}" target="_blank">📅 Créer réunion Teams</a>',
            obj.outlook_compose_link()
        )

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
                "start_date",
                "end_date",
                "days_count",
                "trainer",
                "backup_trainer",
            )
        }),
        ("Lieu", {
            "fields": ("on_client_site", "client_address", "room")
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

    class Media:
        js = (
            "trainings/session_admin.js",
            "trainings/session_location_admin.js",
        )
