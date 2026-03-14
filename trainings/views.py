from __future__ import annotations

import glob
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from functools import wraps

import pdfkit
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, DateField, DecimalField, ExpressionWrapper, F, IntegerField, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import smart_str
from django.views.decorators.http import require_POST
from calendar import monthrange
from django.db import models

from trainings.services.invitations import generate_invitations_for_session

from .forms import BulkRegistrationForm, MercureContractForm, MercureInvoiceForm, NewParticipantFormSet
from .models import (
    Client,
    MercureContract,
    MercureContractStatus,
    MercureInvoice,
    MercureInvoiceStatus,
    Participant,
    PartnerContract,
    PartnerContractPlan,
    PartnerContractPlanSeat,
    Registration,
    RegistrationStatus,
    Session,
    SessionBillingMode,
    Trainer,
    Training,
    TrainingType,
    SessionStatus,
    TrainerAbsence,
    TrainerWorkloadEntry,
    
)

from argonteam.models import (
    ArgonosModule,
    ObjectiveCategory,
    ObjectiveStatus,
    OneToOneMeeting,
    OneToOneObjective,
    OneToOneStatus,
    TrainerModuleMastery,
)

try:
    from projects.models import Project, Task, TaskAssignment
except Exception:
    Project = None
    Task = None
    TaskAssignment = None


# =========================================================
# Rôles / droits
# =========================================================

def is_trainer_readonly(user) -> bool:
    """Retourne True si l'utilisateur est dans le groupe FORMATEURS."""
    return user.is_authenticated and user.groups.filter(name="FORMATEURS").exists()


def get_trainer_for_user(user):
    """
    Retrouve le Trainer associé à l'utilisateur.
    - Essaye Trainer.user (si ce champ existe)
    - Sinon fallback sur email
    """
    if not user.is_authenticated:
        return None

    try:
        trainer = Trainer.objects.filter(user=user).first()
        if trainer:
            return trainer
    except Exception:
        pass

    user_email = (getattr(user, "email", "") or "").strip()
    if user_email:
        try:
            trainer = Trainer.objects.filter(email__iexact=user_email).first()
            if trainer:
                return trainer
        except Exception:
            pass

    return None


def mercure_only_required(view_func):
    """
    Autorise :
    - managers (non FORMATEURS)
    - formateurs Mercure
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_trainer_readonly(request.user):
            return view_func(request, *args, **kwargs)

        trainer = get_trainer_for_user(request.user)
        if trainer and (getattr(trainer, "product", "") or "").upper() == Trainer.PRODUCT_MERCURE:
            return view_func(request, *args, **kwargs)

        raise PermissionDenied("Accès réservé aux formateurs Mercure et aux responsables.")
    return _wrapped


def manager_required(view_func):
    """Bloque l'accès aux utilisateurs du groupe FORMATEURS."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if is_trainer_readonly(request.user):
            raise PermissionDenied("Accès réservé aux responsables.")
        return view_func(request, *args, **kwargs)
    return _wrapped


# =========================================================
# Helpers
# =========================================================

def _monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _color_for_training(training_id: int) -> str:
    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]
    return palette[(training_id or 0) % len(palette)]


def _week_bounds(d: date) -> tuple[date, date]:
    """Bornes semaine ISO (lundi -> dimanche) pour la date d."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _session_days_in_week(start: date | None, end: date | None, week_start: date, week_end: date) -> int:
    """Nombre de jours inclusifs de chevauchement entre [start,end] et [week_start,week_end]."""
    if not start:
        return 0
    if not end:
        end = start
    a = max(start, week_start)
    b = min(end, week_end)
    if b < a:
        return 0
    return (b - a).days + 1

def _month_bounds_from_string(month_str: str | None) -> tuple[date, date, str]:
    """
    Retourne :
    - start_date du mois
    - end_date du mois
    - month_str normalisé YYYY-MM
    """
    today = timezone.localdate()

    if month_str:
        try:
            y, m = month_str.split("-")
            year = int(y)
            month = int(m)
            start = date(year, month, 1)
        except Exception:
            start = date(today.year, today.month, 1)
    else:
        start = date(today.year, today.month, 1)

    _, last_day = monthrange(start.year, start.month)
    end = date(start.year, start.month, last_day)
    normalized = start.strftime("%Y-%m")
    return start, end, normalized


def _working_days_between(start: date, end: date) -> int:
    """
    Nombre de jours ouvrés (lun->ven) inclusifs.
    """
    if end < start:
        return 0

    current = start
    total = 0
    while current <= end:
        if current.weekday() < 5:
            total += 1
        current += timedelta(days=1)
    return total


def _inclusive_days_between(start: date | None, end: date | None) -> int:
    if not start:
        return 0
    if not end:
        end = start
    if end < start:
        return 0
    return (end - start).days + 1


def _overlap_inclusive_days(
    start_a: date | None,
    end_a: date | None,
    start_b: date,
    end_b: date,
) -> int:
    """
    Nombre de jours calendaires inclusifs communs entre [a] et [b].
    """
    if not start_a:
        return 0

    if not end_a:
        end_a = start_a

    a = max(start_a, start_b)
    b = min(end_a, end_b)

    if b < a:
        return 0
    return (b - a).days + 1


def _prorated_days_for_period(
    item_start: date | None,
    item_end: date | None,
    item_days_count: Decimal | None,
    period_start: date,
    period_end: date,
) -> Decimal:
    """
    Répartit proportionnellement days_count selon le chevauchement de dates.
    Exemple :
    - item sur 4 jours calendaires
    - chevauchement de 2 jours
    => 50% de days_count
    """
    if not item_start:
        return Decimal("0.0")

    total_span = _inclusive_days_between(item_start, item_end)
    overlap = _overlap_inclusive_days(item_start, item_end, period_start, period_end)

    if total_span <= 0 or overlap <= 0:
        return Decimal("0.0")

    base = item_days_count if item_days_count is not None else Decimal(str(overlap))
    return (Decimal(overlap) / Decimal(total_span)) * Decimal(base)


def _workload_status_label(rate_pct: Decimal) -> str:
    if rate_pct > Decimal("100"):
        return "Surcharge"
    if rate_pct >= Decimal("85"):
        return "Tension"
    if rate_pct < Decimal("50"):
        return "Sous-charge"
    return "OK"

# =========================================================
# Sync objectifs -> Tasks (projects app)
# =========================================================

def _get_or_create_argonos_project() -> "Project | None":
    """Projet unique qui centralise les tâches issues des objectifs ArgonOS."""
    if Project is None:
        return None

    proj, _ = Project.objects.get_or_create(
        name="ArgonOS — 1 to 1",
        defaults={"is_active": True},
    )
    if not proj.is_active:
        proj.is_active = True
        proj.save(update_fields=["is_active"])
    return proj


def _map_objective_status_to_task_status(obj_status: str) -> str:
    """Mappe ObjectiveStatus -> Task.Status."""
    if Task is None:
        return "todo"

    mapping = {
        "TODO": Task.Status.TODO,
        "IN_PROGRESS": Task.Status.DOING,
        "BLOCKED": Task.Status.BLOCKED,
        "DONE": Task.Status.DONE,
    }
    return mapping.get(obj_status, Task.Status.TODO)


def _create_task_for_objective(objective: OneToOneObjective) -> None:
    """
    Crée la Task si objective.actionable=True et objective.created_task_id vide.
    Remplit objective.created_task_id.
    """
    if Task is None or Project is None:
        return

    if not getattr(objective, "actionable", False) or getattr(objective, "created_task_id", None):
        return

    project = _get_or_create_argonos_project()
    if not project:
        return

    max_order = Task.objects.filter(project=project).aggregate(m=Max("order")).get("m")
    next_order = (max_order or 0) + 1

    task = Task.objects.create(
        project=project,
        title=objective.title,
        description=(objective.description or "").strip(),
        status=_map_objective_status_to_task_status(objective.status),
        order=next_order,
        priority=2,
        due_date=objective.due_date,
    )

    objective.created_task_id = task.id
    objective.save(update_fields=["created_task_id"])


def _sync_task_from_objective(objective: OneToOneObjective) -> None:
    """Met à jour la task liée si elle existe."""
    if Task is None or not getattr(objective, "created_task_id", None):
        return

    task = Task.objects.filter(id=objective.created_task_id).first()
    if not task:
        return

    task.title = objective.title
    task.description = (objective.description or "").strip()
    task.due_date = objective.due_date
    task.status = _map_objective_status_to_task_status(objective.status)
    task.save(update_fields=["title", "description", "due_date", "status", "updated_at"])


# =========================================================
# Pages principales
# =========================================================

@login_required
def home_view(request):
    today = date.today()
    limit = today + timedelta(days=15)

    week_start, week_end = _week_bounds(today)

    week_sessions = (
        Session.objects
        .select_related("training", "training_type", "client")
        .filter(start_date__gte=week_start, start_date__lte=week_end)
    )

    week_argonos_count = (
        week_sessions.filter(
            Q(training_type__name__iexact="ArgonOS")
            | Q(training__training_type__name__iexact="ArgonOS")
        ).count()
    )

    week_mercure_count = (
        week_sessions.filter(
            Q(training_type__name__iexact="Mercure")
            | Q(training__training_type__name__iexact="Mercure")
        ).count()
    )

    week_deadlines_count = None
    if Task is not None:
        try:
            done_value = Task.Status.DONE
            week_deadlines_count = (
                Task.objects.filter(due_date__gte=week_start, due_date__lte=week_end)
                .exclude(status=done_value)
                .count()
            )
        except Exception:
            week_deadlines_count = (
                Task.objects.filter(due_date__gte=week_start, due_date__lte=week_end)
                .exclude(Q(status__iexact="DONE") | Q(status__iexact="TERMINÉ") | Q(status__iexact="TERMINE"))
                .count()
            )

    planned_days = 0
    for start_date, end_date in week_sessions.values_list("start_date", "end_date"):
        planned_days += _session_days_in_week(start_date, end_date, week_start, week_end)

    working_days = 5
    week_utilization_pct = round((planned_days / working_days) * 100) if working_days else None
    utilization_target = 80

    invoices_alerts = MercureInvoice.objects.none()

    qs = Session.objects.select_related("training", "client").filter(
        start_date__gte=today,
        start_date__lte=limit,
    )

    try:
        qs = qs.filter(convocation_alert_closed__in=[False, None])
    except Exception:
        pass

    convocations_alerts = qs.order_by("start_date")

    if not is_trainer_readonly(request.user):
        can_access_mercure = True
    else:
        trainer = get_trainer_for_user(request.user)
        can_access_mercure = bool(
            trainer and (getattr(trainer, "product", "") or "").upper() == Trainer.PRODUCT_MERCURE
        )

    if can_access_mercure or request.user.is_staff:
        invoices_qs = (
            MercureInvoice.objects
            .select_related("trainer", "session", "session__client", "session__training")
            .exclude(status=MercureInvoiceStatus.PAID)
            .exclude(received_date__isnull=True)
            .exclude(payment_alert_closed=True)
            .annotate(
                due_date_db=ExpressionWrapper(
                    F("received_date") + timedelta(days=60),
                    output_field=DateField(),
                )
            )
        )

        if is_trainer_readonly(request.user):
            trainer = get_trainer_for_user(request.user)
            if trainer:
                invoices_qs = invoices_qs.filter(trainer=trainer)

        invoices_alerts = invoices_qs.filter(
            due_date_db__gte=today,
            due_date_db__lte=limit,
        ).order_by("due_date_db")

    invoices_alerts_list = list(invoices_alerts)
    invoices_alerts_count = len(invoices_alerts_list)

    convocations_alerts_list = list(convocations_alerts)
    convocations_alerts_count = len(convocations_alerts_list)

    alerts_total = invoices_alerts_count + convocations_alerts_count

    return render(request, "trainings/home.html", {
        "today": today,
        "week_start": week_start,
        "week_end": week_end,
        "week_argonos_count": week_argonos_count,
        "week_mercure_count": week_mercure_count,
        "week_deadlines_count": week_deadlines_count if week_deadlines_count is not None else "—",
        "week_utilization_pct": week_utilization_pct,
        "utilization_target": utilization_target,
        "convocations_alerts": convocations_alerts_list,
        "invoices_alerts": invoices_alerts_list,
        "convocations_alerts_count": convocations_alerts_count,
        "invoices_alerts_count": invoices_alerts_count,
        "alerts_total": alerts_total,
        "can_access_mercure": can_access_mercure,
    })


@staff_member_required
@require_POST
def create_invitations(request, session_id: int):
    session = get_object_or_404(
        Session.objects.select_related("training", "client", "trainer", "room"),
        pk=session_id,
    )

    lang = (request.POST.get("lang") or "fr").lower().strip()
    base_url = request.build_absolute_uri("/")

    try:
        result = generate_invitations_for_session(session=session, lang=lang, base_url=base_url)
        messages.success(
            request,
            f"✅ Convocations {lang.upper()} générées : {len(result.pdf_files)} PDF — {result.folder_rel}"
        )
    except Exception as e:
        messages.error(request, f"❌ Erreur convocations : {e}")

    return redirect("trainings:home")


@staff_member_required
@require_POST
def dismiss_mercure_invoice_alert(request, invoice_id: int):
    inv = get_object_or_404(MercureInvoice, pk=invoice_id)
    inv.payment_alert_closed = True
    inv.save(update_fields=["payment_alert_closed"])
    return redirect("trainings:home")


@login_required
def team_home(request):
    return render(request, "trainings/team_home.html")


@login_required
def agenda_view(request):
    today = timezone.localdate()
    return render(request, "trainings/agenda.html", {"today": today})


@login_required
def session_detail_view(request, session_id: int):
    session = get_object_or_404(
        Session.objects
        .select_related("training", "training_type", "client", "trainer", "backup_trainer", "room")
        .prefetch_related("registrations__participant"),
        id=session_id,
    )
    return render(request, "trainings/session_detail.html", {"s": session})


# =========================================================
# Inscriptions en masse
# =========================================================

@staff_member_required
def bulk_registrations(request):
    if request.method == "POST":
        form = BulkRegistrationForm(request.POST)
        formset = NewParticipantFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            session = form.cleaned_data["session"]
            selected = list(form.cleaned_data["existing_participants"])

            for f in formset:
                cd = f.cleaned_data
                if not cd or not any([
                    cd.get("first_name"),
                    cd.get("last_name"),
                    cd.get("email"),
                    cd.get("company_service"),
                ]):
                    continue

                participant, _created = Participant.objects.get_or_create(
                    email=cd["email"],
                    defaults={
                        "first_name": cd["first_name"],
                        "last_name": cd["last_name"],
                        "company_service": cd.get("company_service") or "",
                        "client": session.client,
                    },
                )

                if participant.client_id is None:
                    participant.client = session.client
                    participant.save(update_fields=["client"])

                selected.append(participant)

            for participant in selected:
                Registration.objects.get_or_create(
                    session=session,
                    participant=participant,
                    defaults={"status": RegistrationStatus.INVITED},
                )

            return redirect(f"/admin/trainings/session/{session.id}/change/")

    else:
        initial = {}
        sid = request.GET.get("session_id")
        if sid:
            initial["session"] = sid
        form = BulkRegistrationForm(initial=initial)
        formset = NewParticipantFormSet()

    selected_session = None
    sid = request.POST.get("session") or request.GET.get("session_id")
    if sid:
        selected_session = Session.objects.select_related("training", "client").filter(pk=sid).first()

    return render(request, "trainings/bulk_registrations.html", {
        "form": form,
        "formset": formset,
        "selected_session": selected_session,
    })


# =========================================================
# APIs
# =========================================================

@login_required
def sessions_json(request):
    """Renvoie les sessions pour FullCalendar avec filtres."""

    client_id = request.GET.get("client_id")
    trainer_id = request.GET.get("trainer_id")

    product = (request.GET.get("product") or "").upper().strip()
    from_str = (request.GET.get("from") or "").strip()
    to_str = (request.GET.get("to") or "").strip()

    from_date = None
    to_date = None
    try:
        if from_str:
            from_date = date.fromisoformat(from_str)
        if to_str:
            to_date = date.fromisoformat(to_str)
    except Exception:
        from_date = None
        to_date = None

    qs = Session.objects.select_related(
        "training", "training_type", "client", "trainer", "backup_trainer", "room"
    ).filter(start_date__isnull=False)

    if client_id:
        qs = qs.filter(client_id=client_id)
    if trainer_id:
        qs = qs.filter(trainer_id=trainer_id)

    if product in ("ARGONOS", "MERCURE"):
        qs = qs.filter(
            Q(training_type__name__iexact=product)
            | Q(training__training_type__name__iexact=product)
        )

    if from_date:
        qs = qs.filter(start_date__gte=from_date)
    if to_date:
        qs = qs.filter(start_date__lte=to_date)

    events = []
    for session in qs:
        if not session.start_date:
            continue

        if getattr(session, "on_client_site", False):
            location = getattr(session, "client_address", "") or ""
        else:
            location = session.room.name if getattr(session, "room", None) else ""

        end_date = getattr(session, "end_date", None) or session.start_date
        end_exclusive = end_date + timedelta(days=1)

        title = session.reference or (session.training.title if session.training else "Session")
        color = _color_for_training(session.training_id or 0)

        events.append({
            "id": session.id,
            "title": title,
            "start": session.start_date.isoformat(),
            "end": end_exclusive.isoformat(),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "detail_url": f"/sessions/{session.id}/",
            "reference": session.reference or "",
            "work_environment": getattr(session, "work_environment", ""),
            "client": session.client.name if session.client else "",
            "training": session.training.title if session.training else "",
            "training_type": session.training_type.name if getattr(session, "training_type", None) else "",
            "trainer": f"{session.trainer.first_name} {session.trainer.last_name}".strip() if session.trainer else "",
            "backup_trainer": (
                f"{session.backup_trainer.first_name} {session.backup_trainer.last_name}".strip()
                if getattr(session, "backup_trainer", None) else ""
            ),
            "location": location,
            "start_date": session.start_date.strftime("%d/%m/%Y") if session.start_date else "",
            "end_date": end_date.strftime("%d/%m/%Y") if end_date else "",
            "status": getattr(session, "status", ""),
        })

    return JsonResponse(events, safe=False)


@login_required
def trainings_by_type_json(request):
    training_type_id = request.GET.get("training_type_id")

    qs = Training.objects.all().order_by("title")
    if training_type_id:
        qs = qs.filter(training_type_id=training_type_id)

    data = [{"id": t.id, "title": t.title} for t in qs]
    return JsonResponse(data, safe=False)


@login_required
def clients_list_json(request):
    data = list(Client.objects.order_by("name").values("id", "name"))
    return JsonResponse(data, safe=False)


@login_required
def trainers_list_json(request):
    qs = Trainer.objects.order_by("last_name", "first_name")
    data = [{"id": t.id, "name": f"{t.first_name} {t.last_name}".strip()} for t in qs]
    return JsonResponse(data, safe=False)


@login_required
def trainings_legend_json(request):
    trainings = Training.objects.select_related("training_type").all().order_by("training_type__name", "title")

    groups = {}
    for t in trainings:
        type_name = t.training_type.name if t.training_type else "Sans type"
        groups.setdefault(type_name, [])
        groups[type_name].append({
            "id": t.id,
            "title": t.title,
            "color": _color_for_training(t.id),
        })

    data = [{"training_type": k, "items": v} for k, v in groups.items()]
    return JsonResponse(data, safe=False)


# =========================================================
# Alertes
# =========================================================

@staff_member_required
@require_POST
def dismiss_convocation_alert(request, session_id: int):
    session = get_object_or_404(Session, pk=session_id)
    try:
        session.convocation_alert_closed = True
        session.save(update_fields=["convocation_alert_closed"])
    except Exception:
        pass
    return redirect("trainings:home")


# =========================================================
# Dashboard manager
# =========================================================

@login_required
@manager_required
def dashboard_view(request):
    by_type = (
        Session.objects
        .values("training_type__name")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    labels_type = [row["training_type__name"] or "Sans type" for row in by_type]
    values_type = [row["total"] for row in by_type]

    return render(request, "trainings/dashboard.html", {
        "labels_type": labels_type,
        "values_type": values_type,
    })


# =========================================================
# Team
# =========================================================

@login_required
def team(request):
    product = (request.GET.get("product") or Trainer.PRODUCT_ARGONOS).upper()

    if product not in (Trainer.PRODUCT_ARGONOS, Trainer.PRODUCT_MERCURE):
        product = Trainer.PRODUCT_ARGONOS

    trainers = Trainer.objects.filter(product=product).order_by("last_name", "first_name")
    label = "ArgonOS" if product == Trainer.PRODUCT_ARGONOS else "Mercure"

    return render(request, "trainings/team.html", {
        "trainers": trainers,
        "product": product,
        "product_label": label,
    })


# =========================================================
# Team ArgonOS
# =========================================================

@login_required
def team_argonos(request):
    trainers = Trainer.objects.filter(product="ARGONOS").order_by("last_name", "first_name")

    trainer_id = request.GET.get("trainer")
    selected = trainers.filter(id=trainer_id).first() if trainer_id else None
    if not selected and trainers.exists():
        selected = trainers.first()

    tab = (request.GET.get("tab") or "detail").strip().lower()
    if tab not in ("detail", "1to1"):
        tab = "detail"

    meetings = OneToOneMeeting.objects.none()
    objectives_open = OneToOneObjective.objects.none()
    objectives_done = OneToOneObjective.objects.none()
    recent_sessions = Session.objects.none()

    today = timezone.localdate()
    this_week_start = _monday_of_week(today)
    this_week_meeting = None
    this_week_objectives = OneToOneObjective.objects.none()
    can_create_this_week = False

    module_rows = []
    modules_count = 0

    visible_task_assignments = []
    visible_task_assignments_open = []
    visible_task_assignments_done = []
    project_load_total = Decimal("0.0")

    if selected:
        meetings = OneToOneMeeting.objects.filter(trainer=selected).order_by("-week_start")

        objectives_open = (
            OneToOneObjective.objects
            .filter(trainer=selected)
            .exclude(status=ObjectiveStatus.DONE)
            .order_by("-created_at")
        )

        objectives_done = (
            OneToOneObjective.objects
            .filter(trainer=selected, status=ObjectiveStatus.DONE)
            .order_by("-created_at")[:25]
        )

        recent_sessions = Session.objects.filter(trainer=selected).order_by("-start_date")[:10]

        this_week_meeting = (
            OneToOneMeeting.objects
            .filter(trainer=selected, week_start=this_week_start)
            .first()
        )
        can_create_this_week = this_week_meeting is None

        if this_week_meeting:
            this_week_objectives = this_week_meeting.objectives.all().order_by("-created_at")

        modules = ArgonosModule.objects.filter(is_active=True).order_by("kind", "level", "name")
        modules_count = modules.count()

        existing = TrainerModuleMastery.objects.filter(trainer=selected, module__in=modules)
        existing_by_module_id = {m.module_id: m for m in existing}

        missing = []
        for mod in modules:
            if mod.id not in existing_by_module_id:
                missing.append(TrainerModuleMastery(trainer=selected, module=mod))
        if missing:
            TrainerModuleMastery.objects.bulk_create(missing, ignore_conflicts=True)
            existing = TrainerModuleMastery.objects.filter(trainer=selected, module__in=modules)
            existing_by_module_id = {m.module_id: m for m in existing}

        for mod in modules:
            mastery = existing_by_module_id.get(mod.id)
            module_rows.append({"module": mod, "mastery": mastery})

        if TaskAssignment is not None:
            visible_task_assignments = list(
                TaskAssignment.objects
                .select_related("task", "task__project", "trainer")
                .filter(
                    trainer=selected,
                    is_visible_in_one_to_one=True,
                )
                .exclude(status=TaskAssignment.Status.CANCELED)
                .order_by("start_date", "end_date", "task__project__name", "task__title")
            )

            visible_task_assignments_open = [
                a for a in visible_task_assignments
                if a.status != TaskAssignment.Status.DONE
            ]

            visible_task_assignments_done = [
                a for a in visible_task_assignments
                if a.status == TaskAssignment.Status.DONE
            ]

            project_load_total = sum(
                (a.planned_days or Decimal("0.0"))
                for a in visible_task_assignments_open
            )

    return render(request, "trainings/team_argonos.html", {
        "trainers": trainers,
        "selected": selected,
        "tab": tab,
        "meetings": meetings,
        "objectives_open": objectives_open,
        "objectives_done": objectives_done,
        "recent_sessions": recent_sessions,
        "this_week_start": this_week_start,
        "this_week_meeting": this_week_meeting,
        "this_week_objectives": this_week_objectives,
        "can_create_this_week": can_create_this_week,
        "module_rows": module_rows,
        "modules_count": modules_count,
        "visible_task_assignments": visible_task_assignments,
        "visible_task_assignments_open": visible_task_assignments_open,
        "visible_task_assignments_done": visible_task_assignments_done,
        "project_load_total": project_load_total,
    })



@login_required
def create_one_to_one_argonos(request):
    trainer_id = request.GET.get("trainer")
    trainer = get_object_or_404(Trainer, id=trainer_id, product="ARGONOS")

    today = timezone.localdate()
    week_start = _monday_of_week(today)

    OneToOneMeeting.objects.get_or_create(
        trainer=trainer,
        week_start=week_start,
        defaults={"meeting_date": today},
    )

    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")


@login_required
def add_objective_this_week_argonos(request):
    trainer_id = request.GET.get("trainer") or request.POST.get("trainer")
    if not trainer_id:
        messages.error(request, "Formateur manquant.")
        return redirect("trainings:team_argonos")

    trainer = get_object_or_404(Trainer, id=trainer_id, product="ARGONOS")

    today = timezone.localdate()
    week_start = _monday_of_week(today)

    meeting, _ = OneToOneMeeting.objects.get_or_create(
        trainer=trainer,
        week_start=week_start,
        defaults={"meeting_date": today},
    )

    if request.method == "GET":
        return render(request, "trainings/argon_add_objective.html", {
            "trainer": trainer,
            "week_start": week_start,
            "meeting": meeting,
            "category_choices": ObjectiveCategory.choices,
        })

    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "Titre obligatoire.")
        return redirect(f"{reverse('trainings:add_objective_this_week_argonos')}?trainer={trainer.id}")

    category = (request.POST.get("category") or ObjectiveCategory.GOAL).strip()
    valid_categories = {c[0] for c in ObjectiveCategory.choices}
    if category not in valid_categories:
        category = ObjectiveCategory.GOAL

    due_date = request.POST.get("due_date") or None
    description = (request.POST.get("description") or "").strip()
    actionable = request.POST.get("actionable") == "on"

    objective = OneToOneObjective.objects.create(
        trainer=trainer,
        meeting=meeting,
        title=title,
        category=category,
        status=ObjectiveStatus.TODO,
        actionable=actionable,
        description=description,
        due_date=due_date,
    )

    _create_task_for_objective(objective)

    messages.success(request, "Objectif ajouté ✅")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")


# =========================================================
# Objectifs ArgonOS
# =========================================================

@require_POST
@login_required
def argonos_objective_toggle(request, objective_id: int):
    objective = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(objective.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    if objective.status == ObjectiveStatus.DONE:
        objective.status = ObjectiveStatus.TODO
        messages.info(request, "Objectif rouvert ↩️")
    else:
        objective.status = ObjectiveStatus.DONE
        messages.success(request, "Objectif terminé ✅")

    objective.save(update_fields=["status"])
    _sync_task_from_objective(objective)
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={objective.trainer_id}&tab=1to1")


@require_POST
@login_required
def argonos_objective_delete(request, objective_id: int):
    objective = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(objective.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    trainer_id = objective.trainer_id
    objective.delete()

    messages.success(request, "Objectif supprimé 🗑️")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer_id}&tab=1to1")


@login_required
def argonos_objective_edit(request, objective_id: int):
    objective = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(objective.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Titre obligatoire.")
            return redirect(reverse("trainings:argonos_objective_edit", args=[objective.id]))

        category = (request.POST.get("category") or objective.category).strip()
        valid_categories = {c[0] for c in ObjectiveCategory.choices}
        if category not in valid_categories:
            category = objective.category

        due_date = request.POST.get("due_date") or None
        if due_date == "":
            due_date = None

        objective.title = title
        objective.category = category
        objective.due_date = due_date
        objective.actionable = request.POST.get("actionable") == "on"
        objective.description = (request.POST.get("description") or "").strip()
        objective.save()

        messages.success(request, "Objectif modifié ✏️")
        _sync_task_from_objective(objective)
        return redirect(f"{reverse('trainings:team_argonos')}?trainer={objective.trainer_id}&tab=1to1")

    return render(request, "trainings/argon_edit_objective.html", {
        "o": objective,
        "category_choices": ObjectiveCategory.choices,
    })


# =========================================================
# Kanban objectifs ArgonOS
# =========================================================

@login_required
def argonos_objectives_kanban(request):
    trainer_id = request.GET.get("trainer")

    qs = OneToOneObjective.objects.filter(actionable=True).select_related("trainer", "meeting")
    if trainer_id:
        qs = qs.filter(trainer_id=trainer_id)

    col_todo = qs.filter(status=ObjectiveStatus.TODO).order_by("-created_at")
    col_doing = qs.filter(status=getattr(ObjectiveStatus, "DOING", ObjectiveStatus.TODO)).order_by("-created_at")
    col_done = qs.filter(status=ObjectiveStatus.DONE).order_by("-created_at")

    return render(request, "trainings/argon_objectives_kanban.html", {
        "trainer_id": trainer_id,
        "todo": col_todo,
        "doing": col_doing,
        "done": col_done,
        "trainers": Trainer.objects.filter(product="ARGONOS").order_by("last_name", "first_name"),
    })


@login_required
@require_POST
def argonos_objective_set_status(request, objective_id: int, status: str):
    obj = get_object_or_404(OneToOneObjective, id=objective_id)
    status = (status or "").upper().strip()

    valid = {ObjectiveStatus.TODO, ObjectiveStatus.DONE}
    if hasattr(ObjectiveStatus, "DOING"):
        valid.add(ObjectiveStatus.DOING)

    if status not in valid:
        messages.error(request, "Statut invalide.")
        return redirect("trainings:argonos_objectives_kanban")

    obj.status = status
    obj.save(update_fields=["status"])
    _sync_task_from_objective(obj)

    messages.success(request, "Statut mis à jour ✅")

    trainer_id = request.POST.get("trainer_id") or ""
    suffix = f"?trainer={trainer_id}" if trainer_id else ""
    return redirect(f"{reverse('trainings:argonos_objectives_kanban')}{suffix}")


# =========================================================
# Dashboard manager ArgonOS
# =========================================================

@login_required
@manager_required
def argonos_manager_dashboard(request):
    today = timezone.localdate()
    soon_limit = today + timedelta(days=7)

    filter_type = request.GET.get("filter")
    filtered_objectives = None

    if filter_type:
        base_qs = OneToOneObjective.objects.filter(trainer__product="ARGONOS")

        if filter_type == "overdue":
            filtered_objectives = base_qs.filter(due_date__lt=today).exclude(status=ObjectiveStatus.DONE)
        elif filter_type == "due_soon":
            filtered_objectives = base_qs.filter(due_date__gte=today, due_date__lte=soon_limit).exclude(status=ObjectiveStatus.DONE)
        elif filter_type == "blocked":
            filtered_objectives = base_qs.filter(status=ObjectiveStatus.BLOCKED)
        elif filter_type == "open":
            filtered_objectives = base_qs.exclude(status=ObjectiveStatus.DONE)
        elif filter_type == "done":
            filtered_objectives = base_qs.filter(status=ObjectiveStatus.DONE)

    trainers = Trainer.objects.filter(product="ARGONOS").order_by("last_name", "first_name")
    obj_qs = OneToOneObjective.objects.filter(trainer__product="ARGONOS")

    kpi_total = obj_qs.count()
    kpi_open = obj_qs.exclude(status=ObjectiveStatus.DONE).count()
    kpi_done = obj_qs.filter(status=ObjectiveStatus.DONE).count()
    kpi_blocked = obj_qs.filter(status=ObjectiveStatus.BLOCKED).count()
    kpi_overdue = obj_qs.filter(due_date__lt=today).exclude(status=ObjectiveStatus.DONE).count()
    kpi_due_soon = obj_qs.filter(due_date__gte=today, due_date__lte=soon_limit).exclude(status=ObjectiveStatus.DONE).count()

    per_trainer = trainers.annotate(
        objectives_total=Count("one_to_one_objectives", distinct=True),
        objectives_open=Count(
            "one_to_one_objectives",
            filter=~Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
            distinct=True,
        ),
        objectives_done=Count(
            "one_to_one_objectives",
            filter=Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
            distinct=True,
        ),
        objectives_blocked=Count(
            "one_to_one_objectives",
            filter=Q(one_to_one_objectives__status=ObjectiveStatus.BLOCKED),
            distinct=True,
        ),
        objectives_overdue=Count(
            "one_to_one_objectives",
            filter=Q(one_to_one_objectives__due_date__lt=today) & ~Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
            distinct=True,
        ),
        objectives_due_soon=Count(
            "one_to_one_objectives",
            filter=Q(one_to_one_objectives__due_date__gte=today)
            & Q(one_to_one_objectives__due_date__lte=soon_limit)
            & ~Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
            distinct=True,
        ),
    )

    modules_active = ArgonosModule.objects.filter(is_active=True)
    modules_active_count = modules_active.count()

    mastery_qs = TrainerModuleMastery.objects.filter(trainer__product="ARGONOS", module__is_active=True)
    validated_by_trainer = (
        mastery_qs.values("trainer_id")
        .annotate(validated=Count("id", filter=Q(manager_status="OK") | Q(cert_status="OK") | Q(validated_major__isnull=False)))
    )
    validated_map = {row["trainer_id"]: row["validated"] for row in validated_by_trainer}

    rows = []
    for trainer in per_trainer:
        validated = validated_map.get(trainer.id, 0)
        ratio = round((validated / modules_active_count) * 100) if modules_active_count else None
        rows.append({
            "trainer": trainer,
            "modules_validated": validated,
            "modules_total": modules_active_count,
            "modules_ratio": ratio,
        })

    return render(request, "trainings/argon_manager_dashboard.html", {
        "today": today,
        "soon_limit": soon_limit,
        "filter_type": filter_type,
        "filtered_objectives": filtered_objectives,
        "kpi_total": kpi_total,
        "kpi_open": kpi_open,
        "kpi_done": kpi_done,
        "kpi_blocked": kpi_blocked,
        "kpi_overdue": kpi_overdue,
        "kpi_due_soon": kpi_due_soon,
        "rows": rows,
    })


# =========================================================
# Dashboard CA
# =========================================================

@login_required
@manager_required
def dashboard_ca_view(request):
    today = timezone.localdate()

    PERIOD_CHOICES = [
        ("all", "Tout"),
        ("year", "Année (en cours)"),
        ("quarter", "Trimestre (en cours)"),
        ("month", "Mois (en cours)"),
    ]

    VIEW_CHOICES = [
        ("all", "Tous"),
        ("realise", "Réalisé"),
        ("previsionnel", "Prévisionnel"),
    ]

    training_types = TrainingType.objects.order_by("name")

    training_type_id = (request.GET.get("training_type") or "").strip()
    period = (request.GET.get("period") or "all").strip()
    view_mode = (request.GET.get("view") or "all").strip()
    month_str = (request.GET.get("month") or "").strip()

    qs = (
        Session.objects
        .select_related("training", "training_type", "client")
        .annotate(ca_date=Coalesce("end_date", "start_date"))
    )

    if training_type_id.isdigit():
        tid = int(training_type_id)
        qs = qs.filter(Q(training_type_id=tid) | Q(training__training_type_id=tid))

    start_bound = None
    end_bound = None

    if period == "year":
        start_bound = date(today.year, 1, 1)
        end_bound = date(today.year + 1, 1, 1)
    elif period == "quarter":
        q = (today.month - 1) // 3 + 1
        start_month = 3 * (q - 1) + 1
        start_bound = date(today.year, start_month, 1)
        end_month = start_month + 3
        if end_month <= 12:
            end_bound = date(today.year, end_month, 1)
        else:
            end_bound = date(today.year + 1, end_month - 12, 1)
    elif period == "month":
        start_bound = date(today.year, today.month, 1)
        if today.month == 12:
            end_bound = date(today.year + 1, 1, 1)
        else:
            end_bound = date(today.year, today.month + 1, 1)

    if start_bound and end_bound:
        qs = qs.filter(ca_date__gte=start_bound, ca_date__lt=end_bound)

    if view_mode == "realise":
        qs = qs.filter(ca_date__lte=today)
    elif view_mode == "previsionnel":
        qs = qs.filter(ca_date__gt=today)

    if month_str:
        try:
            y_str, m_str = month_str.split("-")
            y = int(y_str)
            m = int(m_str)
            if 1 <= m <= 12:
                qs = qs.filter(ca_date__year=y, ca_date__month=m)
        except Exception:
            pass

    zero_dec = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))

        

    # =========================
    # KPI formation
    # =========================
    ca_formation_total = qs.aggregate(v=Coalesce(Sum("training_price_ht"), zero_dec))["v"]
    ca_formation_realise = qs.filter(ca_date__lte=today).aggregate(v=Coalesce(Sum("training_price_ht"), zero_dec))["v"]
    ca_formation_previsionnel = qs.filter(ca_date__gt=today).aggregate(v=Coalesce(Sum("training_price_ht"), zero_dec))["v"]

    # =========================
    # KPI déplacements
    # =========================
    travel_total = qs.aggregate(v=Coalesce(Sum("travel_fee_ht"), zero_dec))["v"]
    travel_realise = qs.filter(ca_date__lte=today).aggregate(v=Coalesce(Sum("travel_fee_ht"), zero_dec))["v"]
    travel_previsionnel = qs.filter(ca_date__gt=today).aggregate(v=Coalesce(Sum("travel_fee_ht"), zero_dec))["v"]

    # =========================
    # KPI globaux
    # =========================
    ca_total = qs.aggregate(v=Coalesce(Sum("price_ht"), zero_dec))["v"]
    ca_realise = qs.filter(ca_date__lte=today).aggregate(v=Coalesce(Sum("price_ht"), zero_dec))["v"]
    ca_previsionnel = qs.filter(ca_date__gt=today).aggregate(v=Coalesce(Sum("price_ht"), zero_dec))["v"]

    # =========================
    # Graph évolution : TOTAL global
    # =========================
    month_map: dict[str, Decimal] = {}
    for session in qs.exclude(ca_date__isnull=True):
        d = getattr(session, "ca_date", None)
        if not d:
            continue
        key = d.strftime("%Y-%m")
        month_map[key] = month_map.get(key, Decimal("0.00")) + (session.price_ht or Decimal("0.00"))

    labels_month = []
    values_month = []
    for k in sorted(month_map.keys()):
        labels_month.append(k)
        values_month.append(float(month_map[k]))

    # =========================
    # Répartition produit : CA formation uniquement
    # =========================
    by_type = (
        qs.values("training_type__name")
        .annotate(total=Coalesce(Sum("training_price_ht"), zero_dec))
        .order_by("-total")
    )
    labels_type = [row["training_type__name"] or "Sans type" for row in by_type]
    values_type = [float(row["total"] or 0) for row in by_type]

    total_sessions = qs.count()
    status_rows = qs.values("status").annotate(c=Count("id")).order_by("-c")

    status_counts = []
    for row in status_rows:
        raw = (row["status"] or "").strip()
        status_counts.append({"label": raw if raw else "—", "count": row["c"]})

    sessions = qs.order_by("-ca_date", "-start_date")

    return render(request, "trainings/dashboard_ca.html", {
        "today": today,
        "sessions": sessions,

        "ca_formation_total": ca_formation_total,
        "ca_formation_realise": ca_formation_realise,
        "ca_formation_previsionnel": ca_formation_previsionnel,

        "travel_total": travel_total,
        "travel_realise": travel_realise,
        "travel_previsionnel": travel_previsionnel,

        "ca_total": ca_total,
        "ca_realise": ca_realise,
        "ca_previsionnel": ca_previsionnel,
        "labels_month": labels_month,
        "values_month": values_month,
        "labels_type": labels_type,
        "values_type": values_type,
        "total_sessions": total_sessions,
        "status_counts": status_counts,
        "training_types": training_types,
        "period_choices": PERIOD_CHOICES,
        "view_choices": VIEW_CHOICES,
        "f_training_type": training_type_id,
        "f_period": period,
        "f_view": view_mode,
        "f_month": month_str,
    })


# =========================================================
# Gestion des prestations Mercure
# =========================================================

@login_required
@mercure_only_required
def dashboard_mercure_paiements_view(request):
    today = timezone.localdate()
    trainer = get_trainer_for_user(request.user)

    mercure_trainers = Trainer.objects.filter(
        product=Trainer.PRODUCT_MERCURE
    ).order_by("last_name", "first_name")

    selected_trainer_id = (request.GET.get("trainer") or "").strip()

    invoices_qs = (
        MercureInvoice.objects
        .select_related("session", "session__client", "session__training", "trainer")
        .all()
    )

    contracts_qs = (
        MercureContract.objects
        .select_related("session", "session__client", "session__training", "trainer")
        .all()
    )

    if is_trainer_readonly(request.user) and trainer:
        invoices_qs = invoices_qs.filter(trainer=trainer)
        contracts_qs = contracts_qs.filter(trainer=trainer)
        selected_trainer_id = str(trainer.id)
    elif selected_trainer_id.isdigit():
        tid = int(selected_trainer_id)
        if mercure_trainers.filter(id=tid).exists():
            invoices_qs = invoices_qs.filter(trainer_id=tid)
            contracts_qs = contracts_qs.filter(trainer_id=tid)
        else:
            selected_trainer_id = ""

    zero = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))

    total_facture = invoices_qs.aggregate(v=Coalesce(Sum("amount_ht"), zero))["v"]
    total_paye = invoices_qs.filter(status=MercureInvoiceStatus.PAID).aggregate(v=Coalesce(Sum("amount_ht"), zero))["v"]
    total_non_paye = invoices_qs.exclude(status=MercureInvoiceStatus.PAID).aggregate(v=Coalesce(Sum("amount_ht"), zero))["v"]

    invoices_list = list(invoices_qs.order_by("-received_date", "-created_at"))
    overdue_count = sum(1 for inv in invoices_list if inv.is_overdue)

    contracts_list = list(contracts_qs.order_by("session__start_date"))
    due_soon_count = sum(1 for c in contracts_list if c.is_due_soon)

    return render(request, "trainings/dashboard_mercure_paiements.html", {
        "today": today,
        "invoices": invoices_list,
        "contracts": contracts_list,
        "kpi_total_facture": total_facture,
        "kpi_total_paye": total_paye,
        "kpi_total_non_paye": total_non_paye,
        "kpi_overdue_count": overdue_count,
        "kpi_contract_due_soon": due_soon_count,
        "trainer": trainer,
        "is_manager": not is_trainer_readonly(request.user),
        "mercure_trainers": mercure_trainers,
        "f_trainer": selected_trainer_id,
    })


@login_required
@mercure_only_required
def mercure_invoice_create_view(request):
    today = timezone.localdate()
    trainer = get_trainer_for_user(request.user)

    initial = {}
    if is_trainer_readonly(request.user) and trainer:
        initial["trainer"] = trainer

    sid = request.GET.get("session")
    if sid and sid.isdigit():
        initial["session"] = int(sid)

    if request.method == "POST":
        form = MercureInvoiceForm(request.POST)

        if form.is_valid():
            obj = form.save(commit=False)
            if is_trainer_readonly(request.user) and trainer:
                obj.trainer = trainer
            obj.save()
            messages.success(request, "Facture enregistrée ✅")
            return redirect("trainings:dashboard_mercure_paiements")
    else:
        form = MercureInvoiceForm(initial=initial)
        if is_trainer_readonly(request.user) and trainer:
            form.fields["trainer"].disabled = True

    return render(request, "trainings/mercure_invoice_form.html", {
        "today": today,
        "form": form,
        "mode": "create",
        "trainer": trainer,
    })


@login_required
@mercure_only_required
def mercure_contract_create_view(request):
    today = timezone.localdate()
    trainer = get_trainer_for_user(request.user)

    initial = {}
    if is_trainer_readonly(request.user) and trainer:
        initial["trainer"] = trainer

    sid = request.GET.get("session")
    if sid and sid.isdigit():
        initial["session"] = int(sid)

    if request.method == "POST":
        form = MercureContractForm(request.POST)

        if form.is_valid():
            obj = form.save(commit=False)
            if is_trainer_readonly(request.user) and trainer:
                obj.trainer = trainer
            obj.save()
            messages.success(request, "Contrat enregistré ✅")
            return redirect("trainings:dashboard_mercure_paiements")
    else:
        form = MercureContractForm(initial=initial)
        if is_trainer_readonly(request.user) and trainer:
            form.fields["trainer"].disabled = True

    return render(request, "trainings/mercure_contract_form.html", {
        "today": today,
        "form": form,
        "mode": "create",
        "trainer": trainer,
    })


@login_required
@mercure_only_required
def mercure_invoice_open_view(request, invoice_id: int):
    inv = get_object_or_404(MercureInvoice, pk=invoice_id)

    raw = (inv.document_path or "").strip()
    if not raw:
        raise Http404("Aucun document associé à cette facture.")

    path = os.path.normpath(raw)

    base_dir = getattr(settings, "MERCURE_INVOICES_BASE_DIR", None)
    if base_dir:
        base_norm = os.path.normpath(base_dir)
        if not path.lower().startswith(base_norm.lower()):
            raise Http404("Chemin non autorisé.")

    if os.path.isdir(path):
        try:
            pdfs = sorted(glob.glob(os.path.join(path, "*.pdf")))
        except PermissionError:
            raise Http404("Accès refusé au dossier de facture.")

        if not pdfs:
            raise Http404("Aucun PDF trouvé dans le dossier de facture.")
        file_path = pdfs[0]
    else:
        file_path = path

    if not os.path.exists(file_path):
        raise Http404("Fichier introuvable sur le serveur.")

    try:
        filename = os.path.basename(file_path)
        resp = FileResponse(open(file_path, "rb"), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{smart_str(filename)}"'
        return resp
    except PermissionError:
        raise Http404("Accès refusé au fichier de facture.")


@login_required
@mercure_only_required
def mercure_invoice_detail_view(request, invoice_id: int):
    inv = get_object_or_404(
        MercureInvoice.objects.select_related("session", "session__client", "session__training", "trainer"),
        pk=invoice_id,
    )

    me = get_trainer_for_user(request.user)
    if is_trainer_readonly(request.user) and me and inv.trainer_id != me.id:
        raise PermissionDenied("Accès réservé.")

    return render(request, "trainings/mercure_invoice_detail.html", {
        "inv": inv,
        "today": timezone.localdate(),
    })


@login_required
@mercure_only_required
def mercure_contract_detail_view(request, contract_id: int):
    contract = get_object_or_404(
        MercureContract.objects.select_related("session", "session__client", "session__training", "trainer"),
        pk=contract_id,
    )

    me = get_trainer_for_user(request.user)
    if is_trainer_readonly(request.user) and me and contract.trainer_id != me.id:
        raise PermissionDenied("Accès réservé.")

    return render(request, "trainings/mercure_contract_detail.html", {
        "c": contract,
        "today": timezone.localdate(),
    })


@login_required
def test_pdf(request):
    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: Arial, sans-serif; padding: 24px; }}
        h1 {{ margin: 0 0 10px; }}
        .box {{ border:1px solid #ddd; padding:12px; border-radius:10px; }}
      </style>
    </head>
    <body>
      <h1>Test PDF OK ✅</h1>
      <div class="box">
        <p>Si tu lis ceci dans un PDF, wkhtmltopdf + pdfkit fonctionnent.</p>
        <p><strong>URL :</strong> {request.build_absolute_uri("/")}</p>
      </div>
    </body>
    </html>
    """

    cmd = getattr(settings, "WKHTMLTOPDF_CMD", "").strip()
    if not cmd:
        return HttpResponse("WKHTMLTOPDF_CMD manquant dans settings.py", status=500)

    config = pdfkit.configuration(wkhtmltopdf=cmd)
    try:
        pdf = pdfkit.from_string(html, False, configuration=config, options={
            "encoding": "UTF-8",
            "quiet": "",
        })
    except OSError as e:
        return HttpResponse(f"wkhtmltopdf introuvable/erreur: {e}", status=500)

    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="test.pdf"'
    return resp


# =========================================================
# Pré-requis ArgonOS
# =========================================================

def _session_product_name(session: Session) -> str:
    try:
        if getattr(session, "training_type", None) and getattr(session.training_type, "name", None):
            return (session.training_type.name or "").upper()
    except Exception:
        pass

    try:
        if getattr(session, "training", None) and getattr(session.training, "training_type", None):
            return (session.training.training_type.name or "").upper()
    except Exception:
        pass

    return ""


def _session_training_title(session: Session) -> str:
    try:
        if getattr(session, "training", None) and getattr(session.training, "title", None):
            return session.training.title or ""
    except Exception:
        pass
    return ""


def _needs_initiation_prereq_for_session(session: Session) -> bool:
    product = _session_product_name(session)
    if product != "ARGONOS":
        return False

    title = _session_training_title(session).upper()

    is_dp = "DATA PRÉPARATION" in title or "DATA PREPARATION" in title
    is_de = "DATA EXPLORATION" in title
    is_lvl1 = ("NIVEAU 1" in title) or ("NIV 1" in title) or ("N1" in title) or ("LEVEL 1" in title)

    return is_lvl1 and (is_dp or is_de)


def check_initiation_prereq(session: Session, email: str) -> tuple[bool, str]:
    if not session:
        return False, "Session introuvable."

    if not _needs_initiation_prereq_for_session(session):
        return True, "Pré-requis non applicable."

    email = (email or "").strip()
    if not email:
        return False, "Email requis pour vérifier le pré-requis."

    participant = Participant.objects.filter(email__iexact=email).first()
    if not participant:
        return False, "Participant inconnu : crée-le d'abord."

    initiation_q = Q(session__training__title__icontains="initiation")
    argonos_q = (
        Q(session__training_type__name__iexact="ARGONOS")
        | Q(session__training__training_type__name__iexact="ARGONOS")
    )

    attended = (
        Registration.objects
        .filter(participant=participant)
        .filter(initiation_q)
        .filter(argonos_q)
        .filter(status=RegistrationStatus.PRESENT)
        .exists()
    )

    if attended:
        return True, "✅ Pré-requis validé : Initiation déjà suivie."
    return False, "⛔ Pré-requis non validé : Initiation ArgonOS requise avant DP1/DE1."


@login_required
def api_prereq_initiation(request):
    sid = (request.GET.get("session_id") or "").strip()
    email = (request.GET.get("email") or "").strip()

    if not sid.isdigit():
        return JsonResponse({"needs_prereq": False, "ok": True, "message": ""})

    session = (
        Session.objects.select_related("training", "training_type", "training__training_type")
        .filter(pk=int(sid))
        .first()
    )
    if not session:
        return JsonResponse({"needs_prereq": False, "ok": False, "message": "Session introuvable."})

    needs = _needs_initiation_prereq_for_session(session)
    if not needs:
        return JsonResponse({"needs_prereq": False, "ok": True, "message": ""})

    ok, msg = check_initiation_prereq(session, email)
    return JsonResponse({"needs_prereq": True, "ok": ok, "message": msg})


# =========================================================
# Partners dashboard
# =========================================================

@login_required
def partners_dashboard(request):
    partner_id = (request.GET.get("partner") or "").strip()
    country = (request.GET.get("country") or "").strip()
    training = (request.GET.get("training") or "").strip()

    partners_qs = Client.objects.filter(is_partner=True)

    if country:
        partners_qs = partners_qs.filter(country=country)

    selected_partner = None
    if partner_id.isdigit():
        selected_partner = Client.objects.filter(pk=int(partner_id), is_partner=True).first()

    sessions_qs = (
        Session.objects
        .select_related("client", "training", "training_type", "trainer", "room")
        .filter(client__is_partner=True)
        .order_by("-start_date", "-id")
    )

    if country:
        sessions_qs = sessions_qs.filter(client__country=country)

    if selected_partner:
        sessions_qs = sessions_qs.filter(client=selected_partner)

    if training:
        sessions_qs = sessions_qs.filter(training__title=training)

    total_partners = partners_qs.count() if not selected_partner else 1

    countries_count = (
        partners_qs.exclude(country="")
        .values("country")
        .distinct()
        .count()
    )

    sessions_count = sessions_qs.count()

    participants_total = sessions_qs.aggregate(
        total=Coalesce(Sum("present_count"), Value(0), output_field=IntegerField())
    )["total"]

    participants_by_training = (
        sessions_qs.values("training__title")
        .annotate(
            participants=Coalesce(Sum("present_count"), Value(0), output_field=IntegerField()),
            sessions=Count("id"),
        )
        .order_by("training__title")
    )

    partners_by_country = (
        partners_qs.exclude(country="")
        .values("country")
        .annotate(total=Count("id"))
        .order_by("country")
    )

    country_chart_labels = [row["country"] or "Non renseigné" for row in partners_by_country]
    country_chart_values = [row["total"] for row in partners_by_country]

    participants_training_chart_labels = [
        row["training__title"] or "Sans formation"
        for row in participants_by_training
    ]
    participants_training_chart_values = [row["participants"] or 0 for row in participants_by_training]

    sessions_by_partner = Session.objects.filter(client__is_partner=True).select_related("client")
    if country:
        sessions_by_partner = sessions_by_partner.filter(client__country=country)
    if training:
        sessions_by_partner = sessions_by_partner.filter(training__title=training)

    sessions_by_partner = (
        sessions_by_partner
        .values("client__id", "client__name")
        .annotate(total=Count("id"))
        .order_by("-total", "client__name")
    )

    partner_sessions_chart_labels = [row["client__name"] or "Partenaire" for row in sessions_by_partner]
    partner_sessions_chart_values = [row["total"] for row in sessions_by_partner]
    partner_sessions_chart_ids = [row["client__id"] for row in sessions_by_partner]

    participants_by_partner = Session.objects.filter(client__is_partner=True)
    if country:
        participants_by_partner = participants_by_partner.filter(client__country=country)
    if training:
        participants_by_partner = participants_by_partner.filter(training__title=training)

    participants_by_partner = (
        participants_by_partner
        .values("client__id", "client__name")
        .annotate(
            participants=Coalesce(Sum("present_count"), Value(0), output_field=IntegerField())
        )
        .order_by("-participants", "client__name")
    )

    partner_participants_chart_labels = [row["client__name"] or "Partenaire" for row in participants_by_partner]
    partner_participants_chart_values = [row["participants"] or 0 for row in participants_by_partner]
    partner_participants_chart_ids = [row["client__id"] for row in participants_by_partner]

    selected_partner_breakdown = []
    if selected_partner:
        breakdown_qs = Session.objects.filter(client=selected_partner)
        if training:
            breakdown_qs = breakdown_qs.filter(training__title=training)

        selected_partner_breakdown = list(
            breakdown_qs.values("training__title")
            .annotate(
                participants=Coalesce(Sum("present_count"), Value(0), output_field=IntegerField()),
                sessions=Count("id"),
            )
            .order_by("training__title")
        )

    partner_breakdown_labels = [row["training__title"] or "Sans formation" for row in selected_partner_breakdown]
    partner_breakdown_participants = [row["participants"] or 0 for row in selected_partner_breakdown]
    partner_breakdown_sessions = [row["sessions"] or 0 for row in selected_partner_breakdown]

    partner_options = Client.objects.filter(is_partner=True).order_by("name")

    country_options = (
        Client.objects.filter(is_partner=True)
        .exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )

    context = {
        "partner_options": partner_options,
        "country_options": country_options,
        "selected_partner": selected_partner,
        "selected_partner_id": partner_id,
        "selected_country": country,
        "selected_training": training,
        "total_partners": total_partners,
        "countries_count": countries_count,
        "sessions_count": sessions_count,
        "participants_total": participants_total,
        "participants_by_training": participants_by_training,
        "partners_by_country": partners_by_country,
        "sessions": sessions_qs,
        "country_chart_labels": country_chart_labels,
        "country_chart_values": country_chart_values,
        "participants_training_chart_labels": participants_training_chart_labels,
        "participants_training_chart_values": participants_training_chart_values,
        "partner_sessions_chart_labels": partner_sessions_chart_labels,
        "partner_sessions_chart_values": partner_sessions_chart_values,
        "partner_sessions_chart_ids": partner_sessions_chart_ids,
        "partner_participants_chart_labels": partner_participants_chart_labels,
        "partner_participants_chart_values": partner_participants_chart_values,
        "partner_participants_chart_ids": partner_participants_chart_ids,
        "selected_partner_breakdown": selected_partner_breakdown,
        "partner_breakdown_labels": partner_breakdown_labels,
        "partner_breakdown_participants": partner_breakdown_participants,
        "partner_breakdown_sessions": partner_breakdown_sessions,
    }
    return render(request, "trainings/partners_dashboard.html", context)


# =========================================================
# Partners detail
# =========================================================

@login_required
def partners_detail(request):
    partner_id = (request.GET.get("partner") or "").strip()
    training_filter = (request.GET.get("training") or "").strip()

    partner_options = Client.objects.filter(is_partner=True).order_by("name")
    selected_partner = None
    active_contract = None

    quota_rows = []
    participation_rows = []
    participant_summary = []
    unique_participants_count = 0
    total_consumed_seats = 0

    if partner_id.isdigit():
        selected_partner = Client.objects.filter(pk=int(partner_id), is_partner=True).first()

    if selected_partner:
        active_contract = (
            PartnerContract.objects
            .select_related("plan", "partner")
            .filter(partner=selected_partner, status=PartnerContract.STATUS_ACTIVE)
            .order_by("-start_date")
            .first()
        )

        sessions_qs = (
            Session.objects
            .select_related("client", "training", "trainer")
            .filter(client=selected_partner)
            .order_by("-start_date", "-id")
        )

        if active_contract:
            sessions_qs = sessions_qs.filter(start_date__gte=active_contract.start_date)
            if active_contract.end_date:
                sessions_qs = sessions_qs.filter(start_date__lte=active_contract.end_date)

        if training_filter:
            sessions_qs = sessions_qs.filter(training__title=training_filter)

        registrations_qs = (
            Registration.objects
            .select_related(
                "participant",
                "session",
                "session__training",
                "session__client",
                "session__trainer",
            )
            .filter(session__in=sessions_qs)
            .order_by(
                "participant__last_name",
                "participant__first_name",
                "-session__start_date",
            )
        )

        consumed_by_training_id = defaultdict(int)
        participant_map = defaultdict(list)
        unique_participant_ids = set()

        registrations_list = list(registrations_qs)

        for reg in registrations_list:
            participant = reg.participant
            session = reg.session
            training = getattr(session, "training", None)

            participation_rows.append({
                "participant_name": f"{participant.first_name} {participant.last_name}".strip(),
                "participant_email": participant.email,
                "training_title": training.title if training else "—",
                "session_reference": session.reference or "—",
                "session_date": session.start_date,
                "session_end_date": session.end_date,
                "status": reg.status,
                "trainer_name": (
                    f"{session.trainer.first_name} {session.trainer.last_name}".strip()
                    if session.trainer else "—"
                ),
            })

            unique_participant_ids.add(participant.id)

            participant_map[participant.id].append({
                "training_title": training.title if training else "—",
                "session_reference": session.reference or "—",
                "session_date": session.start_date,
                "status": reg.status,
            })

            if reg.status == RegistrationStatus.PRESENT and training:
                consumed_by_training_id[training.id] += 1
                total_consumed_seats += 1

        unique_participants_count = len(unique_participant_ids)

        for participant_id, items in participant_map.items():
            first_item = items[0]
            reg = next((r for r in registrations_list if r.participant_id == participant_id), None)
            if reg:
                participant_summary.append({
                    "participant_name": f"{reg.participant.first_name} {reg.participant.last_name}".strip(),
                    "participant_email": reg.participant.email,
                    "attended_count": len(items),
                    "latest_training": first_item["training_title"],
                    "latest_session_reference": first_item["session_reference"],
                    "history": items,
                })

        if active_contract:
            seat_rules = (
                active_contract.plan.seat_rules
                .select_related("training")
                .order_by("training__title")
            )

            for rule in seat_rules:
                consumed = consumed_by_training_id.get(rule.training_id, 0)
                remaining = rule.included_seats - consumed
                quota_rows.append({
                    "training_title": rule.training.title,
                    "included_seats": rule.included_seats,
                    "consumed_seats": consumed,
                    "remaining_seats": remaining,
                    "usage_pct": round((consumed / rule.included_seats) * 100) if rule.included_seats else 0,
                })

    training_options = (
        Training.objects
        .filter(session__client__is_partner=True)
        .distinct()
        .order_by("title")
    )

    return render(request, "trainings/partners_detail.html", {
        "partner_options": partner_options,
        "training_options": training_options,
        "selected_partner_id": partner_id,
        "selected_training": training_filter,
        "selected_partner": selected_partner,
        "active_contract": active_contract,
        "quota_rows": quota_rows,
        "participation_rows": participation_rows,
        "participant_summary": participant_summary,
        "unique_participants_count": unique_participants_count,
        "total_consumed_seats": total_consumed_seats,
    })

# =========================================================
# Plan de charge formateurs
# =========================================================


@login_required
@manager_required
def trainer_workload_dashboard(request):
    today = timezone.localdate()

    month_str = (request.GET.get("month") or "").strip()
    product = (request.GET.get("product") or "").strip().upper()
    trainer_id = (request.GET.get("trainer") or "").strip()

    month_start, month_end, selected_month = _month_bounds_from_string(month_str)

    trainers_qs = Trainer.objects.filter(is_active=True).order_by("last_name", "first_name")

    if product in (Trainer.PRODUCT_ARGONOS, Trainer.PRODUCT_MERCURE):
        trainers_qs = trainers_qs.filter(product=product)

    if trainer_id.isdigit():
        trainers_qs = trainers_qs.filter(id=int(trainer_id))

    trainers = list(trainers_qs)

    session_statuses_included = [
        SessionStatus.PLANNED,
        SessionStatus.CONFIRMED,
        SessionStatus.IN_PROGRESS,
        SessionStatus.CLOSED,
    ]

    sessions_qs = (
        Session.objects
        .select_related("training", "training_type", "client", "trainer", "backup_trainer")
        .filter(
            status__in=session_statuses_included,
            start_date__isnull=False,
            start_date__lte=month_end,
        )
        .filter(Q(end_date__isnull=True, start_date__gte=month_start) | Q(end_date__gte=month_start))
    )

    absences_qs = (
        TrainerAbsence.objects
        .select_related("trainer")
        .filter(
            start_date__lte=month_end,
            end_date__gte=month_start,
        )
    )

    workload_entries_qs = (
        TrainerWorkloadEntry.objects
        .select_related("trainer")
        .exclude(status="CANCELED")
        .filter(
            start_date__lte=month_end,
            end_date__gte=month_start,
        )
    )

    task_assignments_qs = TaskAssignment.objects.none()
    if TaskAssignment is not None:
        task_assignments_qs = (
            TaskAssignment.objects
            .select_related("trainer", "task", "task__project")
            .exclude(status=TaskAssignment.Status.CANCELED)
            .filter(
                trainer__is_active=True,
                start_date__lte=month_end,
                end_date__gte=month_start,
            )
        )

    sessions_by_primary = defaultdict(list)
    sessions_by_backup = defaultdict(list)
    absences_by_trainer = defaultdict(list)
    extra_workloads_by_trainer = defaultdict(list)
    assignments_by_trainer = defaultdict(list)

    for s in sessions_qs:
        if s.trainer_id:
            sessions_by_primary[s.trainer_id].append(s)
        if s.backup_trainer_id:
            sessions_by_backup[s.backup_trainer_id].append(s)

    for absence in absences_qs:
        absences_by_trainer[absence.trainer_id].append(absence)

    for entry in workload_entries_qs:
        extra_workloads_by_trainer[entry.trainer_id].append(entry)

    for assignment in task_assignments_qs:
        assignments_by_trainer[assignment.trainer_id].append(assignment)

    month_working_days = _working_days_between(month_start, month_end)

    rows = []

    total_capacity = Decimal("0.0")
    total_capacity_net = Decimal("0.0")
    total_primary = Decimal("0.0")
    total_backup = Decimal("0.0")
    total_extra = Decimal("0.0")
    total_project = Decimal("0.0")
    total_absence = Decimal("0.0")
    total_load = Decimal("0.0")

    for trainer in trainers:
        availability_pct = Decimal(trainer.workload_percent or Decimal("100.00"))
        theoretical_capacity = (Decimal(month_working_days) * availability_pct) / Decimal("100")

        primary_days = Decimal("0.0")
        for s in sessions_by_primary.get(trainer.id, []):
            primary_days += _prorated_days_for_period(
                s.start_date,
                s.end_date,
                s.days_count,
                month_start,
                month_end,
            )

        backup_days = Decimal("0.0")
        for s in sessions_by_backup.get(trainer.id, []):
            prorated = _prorated_days_for_period(
                s.start_date,
                s.end_date,
                s.days_count,
                month_start,
                month_end,
            )
            backup_days += prorated * Decimal("0.5")

        absence_days = Decimal("0.0")
        for absence in absences_by_trainer.get(trainer.id, []):
            absence_days += _prorated_days_for_period(
                absence.start_date,
                absence.end_date,
                absence.days_count,
                month_start,
                month_end,
            )

        extra_days = Decimal("0.0")
        for entry in extra_workloads_by_trainer.get(trainer.id, []):
            extra_days += _prorated_days_for_period(
                entry.start_date,
                entry.end_date,
                entry.days_count,
                month_start,
                month_end,
            )

        project_days = Decimal("0.0")
        for assignment in assignments_by_trainer.get(trainer.id, []):
            project_days += _prorated_days_for_period(
                assignment.start_date,
                assignment.end_date,
                assignment.planned_days,
                month_start,
                month_end,
            )

        net_capacity = theoretical_capacity - absence_days
        if net_capacity < 0:
            net_capacity = Decimal("0.0")

        total_planned_load = primary_days + backup_days + extra_days + project_days

        if net_capacity > 0:
            load_rate = (total_planned_load / net_capacity) * Decimal("100")
        else:
            load_rate = Decimal("0.0") if total_planned_load == 0 else Decimal("999.0")

        rows.append({
            "trainer": trainer,
            "capacity_theoretical": round(theoretical_capacity, 1),
            "absence_days": round(absence_days, 1),
            "capacity_net": round(net_capacity, 1),
            "primary_days": round(primary_days, 1),
            "backup_days": round(backup_days, 1),
            "extra_days": round(extra_days, 1),
            "project_days": round(project_days, 1),
            "total_load": round(total_planned_load, 1),
            "load_rate": round(load_rate, 1),
            "status_label": _workload_status_label(load_rate),
            "primary_sessions_count": len(sessions_by_primary.get(trainer.id, [])),
            "backup_sessions_count": len(sessions_by_backup.get(trainer.id, [])),
            "extra_entries_count": len(extra_workloads_by_trainer.get(trainer.id, [])),
            "project_assignments_count": len(assignments_by_trainer.get(trainer.id, [])),
            "absences_count": len(absences_by_trainer.get(trainer.id, [])),
        })

        total_capacity += theoretical_capacity
        total_capacity_net += net_capacity
        total_primary += primary_days
        total_backup += backup_days
        total_extra += extra_days
        total_project += project_days
        total_absence += absence_days
        total_load += total_planned_load

    if total_capacity_net > 0:
        team_load_rate = (total_load / total_capacity_net) * Decimal("100")
    else:
        team_load_rate = Decimal("0.0") if total_load == 0 else Decimal("999.0")

    overload_count = sum(1 for row in rows if Decimal(str(row["load_rate"])) > Decimal("100"))
    tension_count = sum(
        1 for row in rows
        if Decimal("85") <= Decimal(str(row["load_rate"])) <= Decimal("100")
    )
    underload_count = sum(1 for row in rows if Decimal(str(row["load_rate"])) < Decimal("50"))

    trainer_options = Trainer.objects.filter(is_active=True).order_by("last_name", "first_name")

    return render(request, "trainings/trainer_workload_dashboard.html", {
        "today": today,
        "rows": rows,
        "month_start": month_start,
        "month_end": month_end,
        "selected_month": selected_month,
        "selected_product": product,
        "selected_trainer_id": trainer_id,
        "trainer_options": trainer_options,
        "month_working_days": month_working_days,
        "kpi_total_capacity": round(total_capacity, 1),
        "kpi_total_capacity_net": round(total_capacity_net, 1),
        "kpi_total_primary": round(total_primary, 1),
        "kpi_total_backup": round(total_backup, 1),
        "kpi_total_extra": round(total_extra, 1),
        "kpi_total_project": round(total_project, 1),
        "kpi_total_absence": round(total_absence, 1),
        "kpi_total_load": round(total_load, 1),
        "kpi_team_load_rate": round(team_load_rate, 1),
        "kpi_overload_count": overload_count,
        "kpi_tension_count": tension_count,
        "kpi_underload_count": underload_count,
    })


# =========================
# Control center
# =========================
@login_required
@manager_required
def control_center_view(request):
    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    month_start, month_end, selected_month = _month_bounds_from_string(None)

    # =========================
    # KPI globaux
    # =========================
    sessions_month = Session.objects.filter(
        start_date__isnull=False,
        start_date__gte=month_start,
        start_date__lte=month_end,
    ).count()

    ca_realise = (
        Session.objects
        .filter(end_date__isnull=False, end_date__lte=today)
        .aggregate(
            v=Coalesce(
                Sum("training_price_ht"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .get("v")
    ) or Decimal("0.00")

    ca_previsionnel = (
        Session.objects
        .filter(start_date__isnull=False, start_date__gt=today)
        .aggregate(
            v=Coalesce(
                Sum("training_price_ht"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        .get("v")
    ) or Decimal("0.00")

    satisfaction_avg = (
        Session.objects
        .filter(
            start_date__isnull=False,
            start_date__gte=month_start,
            start_date__lte=month_end,
            client_satisfaction__isnull=False,
        )
        .aggregate(v=models.Avg("client_satisfaction"))
        .get("v")
    )

    # =========================
    # Sessions / delivery
    # =========================
    upcoming_sessions = list(
        Session.objects
        .select_related("training", "client", "trainer")
        .filter(start_date__isnull=False, start_date__gte=today)
        .order_by("start_date")[:6]
    )

    convocation_alerts = list(
        Session.objects
        .select_related("training", "client", "trainer")
        .filter(start_date__isnull=False, start_date__gte=today, start_date__lte=week_end)
        .filter(Q(convocation_alert_closed=False) | Q(convocation_alert_closed__isnull=True))
        .order_by("start_date")[:6]
    )

    pending_reports_count = Session.objects.filter(
        end_date__isnull=False,
        end_date__lt=today,
        report_sent_at__isnull=True,
    ).count()

    pending_accounting_count = Session.objects.filter(
        end_date__isnull=False,
        end_date__lt=today,
        accounting_sheets_sent_at__isnull=True,
    ).count()

    # =========================
    # Team control
    # =========================
    active_trainers = list(
        Trainer.objects
        .filter()
        .order_by("last_name", "first_name")
    )

    trainer_rows = []
    total_load_rate = Decimal("0.0")
    overload_count = 0

    month_working_days = _working_days_between(month_start, month_end)

    session_statuses_included = [
        SessionStatus.PLANNED,
        SessionStatus.CONFIRMED,
        SessionStatus.IN_PROGRESS,
        SessionStatus.CLOSED,
    ]

    sessions_qs = (
        Session.objects
        .select_related("trainer", "backup_trainer")
        .filter(
            status__in=session_statuses_included,
            start_date__isnull=False,
            start_date__lte=month_end,
        )
        .filter(Q(end_date__isnull=True, start_date__gte=month_start) | Q(end_date__gte=month_start))
    )

    absences_qs = (
        TrainerAbsence.objects
        .select_related("trainer")
        .filter(start_date__lte=month_end, end_date__gte=month_start)
    )

    workload_entries_qs = (
        TrainerWorkloadEntry.objects
        .select_related("trainer")
        .exclude(status="CANCELED")
        .filter(start_date__lte=month_end, end_date__gte=month_start)
    )

    task_assignments_qs = TaskAssignment.objects.none()
    if TaskAssignment is not None:
        task_assignments_qs = (
            TaskAssignment.objects
            .select_related("trainer", "task", "task__project")
            .exclude(status=TaskAssignment.Status.CANCELED)
            .filter(
                trainer__isnull=False,
                start_date__lte=month_end,
                end_date__gte=month_start,
            )
        )

    sessions_by_primary = defaultdict(list)
    sessions_by_backup = defaultdict(list)
    absences_by_trainer = defaultdict(list)
    extra_workloads_by_trainer = defaultdict(list)
    assignments_by_trainer = defaultdict(list)

    for s in sessions_qs:
        if s.trainer_id:
            sessions_by_primary[s.trainer_id].append(s)
        if s.backup_trainer_id:
            sessions_by_backup[s.backup_trainer_id].append(s)

    for absence in absences_qs:
        absences_by_trainer[absence.trainer_id].append(absence)

    for entry in workload_entries_qs:
        extra_workloads_by_trainer[entry.trainer_id].append(entry)

    for assignment in task_assignments_qs:
        assignments_by_trainer[assignment.trainer_id].append(assignment)

    for trainer in active_trainers:
        availability_pct = Decimal(getattr(trainer, "workload_percent", Decimal("100.00")) or Decimal("100.00"))
        theoretical_capacity = (Decimal(month_working_days) * availability_pct) / Decimal("100")

        primary_days = Decimal("0.0")
        for s in sessions_by_primary.get(trainer.id, []):
            primary_days += _prorated_days_for_period(
                s.start_date, s.end_date, s.days_count, month_start, month_end
            )

        backup_days = Decimal("0.0")
        for s in sessions_by_backup.get(trainer.id, []):
            backup_days += _prorated_days_for_period(
                s.start_date, s.end_date, s.days_count, month_start, month_end
            ) * Decimal("0.5")

        absence_days = Decimal("0.0")
        for a in absences_by_trainer.get(trainer.id, []):
            absence_days += _prorated_days_for_period(
                a.start_date, a.end_date, a.days_count, month_start, month_end
            )

        extra_days = Decimal("0.0")
        for e in extra_workloads_by_trainer.get(trainer.id, []):
            extra_days += _prorated_days_for_period(
                e.start_date, e.end_date, e.days_count, month_start, month_end
            )

        project_days = Decimal("0.0")
        for a in assignments_by_trainer.get(trainer.id, []):
            project_days += _prorated_days_for_period(
                a.start_date, a.end_date, a.planned_days, month_start, month_end
            )

        net_capacity = theoretical_capacity - absence_days
        if net_capacity < 0:
            net_capacity = Decimal("0.0")

        total_planned = primary_days + backup_days + extra_days + project_days
        if net_capacity > 0:
            load_rate = (total_planned / net_capacity) * Decimal("100")
        else:
            load_rate = Decimal("0.0") if total_planned == 0 else Decimal("999.0")

        status_label = _workload_status_label(load_rate)
        if load_rate > Decimal("100"):
            overload_count += 1

        total_load_rate += load_rate

        trainer_rows.append({
            "trainer": trainer,
            "load_rate": round(load_rate, 1),
            "status_label": status_label,
            "project_assignments_count": len(assignments_by_trainer.get(trainer.id, [])),
            "open_objectives_count": OneToOneObjective.objects.filter(trainer=trainer).exclude(
                status=ObjectiveStatus.DONE
            ).count(),
        })

    trainer_rows = sorted(trainer_rows, key=lambda x: x["load_rate"], reverse=True)[:6]
    team_load_avg = round((total_load_rate / Decimal(len(active_trainers))), 1) if active_trainers else Decimal("0.0")

    # =========================
    # Projects control
    # =========================
    projects_active = 0
    tasks_open = 0
    tasks_blocked = 0
    hot_projects = []

    if Project is not None:
        projects_active = Project.objects.filter(is_active=True).count()

    if Task is not None:
        tasks_open = Task.objects.exclude(status=Task.Status.DONE).count()
        tasks_blocked = Task.objects.filter(status=Task.Status.BLOCKED).count()

        hot_projects = list(
            Project.objects
            .annotate(
                tasks_total_count=Count("tasks"),
                tasks_open_count=Count("tasks", filter=~Q(tasks__status=Task.Status.DONE)),
                tasks_blocked_count=Count("tasks", filter=Q(tasks__status=Task.Status.BLOCKED)),
            )
            .filter(is_active=True)
            .order_by("-tasks_open_count", "-tasks_blocked_count", "name")[:5]
        )

    # =========================
    # Partners / clients
    # =========================
    partners_active = Client.objects.filter(is_partner=True).count()
    sessions_partners_month = Session.objects.filter(
        client__is_partner=True,
        start_date__isnull=False,
        start_date__gte=month_start,
        start_date__lte=month_end,
    ).count()

    # =========================
    # Alerts center
    # =========================
    alert_items = []

    for s in convocation_alerts[:4]:
        alert_items.append({
            "level": "high",
            "label": f"Convocation proche à traiter — {s.reference or 'Session'}",
            "meta": f"{s.client} · {s.start_date.strftime('%d/%m/%Y') if s.start_date else '—'}",
            "url": reverse("trainings:home"),
        })

    if pending_reports_count:
        alert_items.append({
            "level": "medium",
            "label": f"{pending_reports_count} bilan(s) à envoyer",
            "meta": "Sessions clôturées sans bilan envoyé",
            "url": reverse("trainings:home"),
        })

    if pending_accounting_count:
        alert_items.append({
            "level": "medium",
            "label": f"{pending_accounting_count} feuille(s) compta à envoyer",
            "meta": "Sessions terminées sans envoi comptable",
            "url": reverse("trainings:home"),
        })

    if tasks_blocked:
        alert_items.append({
            "level": "medium",
            "label": f"{tasks_blocked} tâche(s) projet bloquée(s)",
            "meta": "À revoir côté Projects",
            "url": "/projects/",
        })

    if overload_count:
        alert_items.append({
            "level": "high",
            "label": f"{overload_count} formateur(s) en surcharge",
            "meta": "Charge mensuelle au-dessus de 100%",
            "url": reverse("trainings:trainer_workload_dashboard"),
        })

        pricing_issues_collective = Session.objects.filter(
        billing_mode=SessionBillingMode.COLLECTIVE,
        training_price_ht=Decimal("0.00"),
    ).count()

    pricing_issues_individual = Session.objects.filter(
        billing_mode=SessionBillingMode.INDIVIDUAL,
        applied_participant_price_ht__isnull=True,
    ).count()

    abroad_missing_travel = Session.objects.filter(
        is_abroad=True,
        travel_fee_ht=Decimal("0.00"),
    ).count()

    if pricing_issues_collective:
        alert_items.append({
            "level": "high",
            "label": f"{pricing_issues_collective} session(s) collective(s) sans tarif session",
            "meta": "Tarification formation à vérifier",
            "url": reverse("trainings:dashboard_ca"),
        })

    if pricing_issues_individual:
        alert_items.append({
            "level": "high",
            "label": f"{pricing_issues_individual} session(s) individuelle(s) sans tarif participant",
            "meta": "Tarification par inscription à vérifier",
            "url": reverse("trainings:dashboard_ca"),
        })

    if abroad_missing_travel:
        alert_items.append({
            "level": "medium",
            "label": f"{abroad_missing_travel} session(s) à l'étranger sans déplacement",
            "meta": "Forfait déplacement manquant",
            "url": reverse("trainings:dashboard_ca"),
        })

    context = {
        "today": today,
        "sessions_month": sessions_month,
        "ca_realise": ca_realise,
        "ca_previsionnel": ca_previsionnel,
        "team_load_avg": team_load_avg,
        "satisfaction_avg": round(satisfaction_avg, 1) if satisfaction_avg is not None else None,
        "alerts_count": len(alert_items),

        "upcoming_sessions": upcoming_sessions,
        "convocation_alerts": convocation_alerts,
        "pending_reports_count": pending_reports_count,
        "pending_accounting_count": pending_accounting_count,

        "trainer_rows": trainer_rows,
        "projects_active": projects_active,
        "tasks_open": tasks_open,
        "tasks_blocked": tasks_blocked,
        "hot_projects": hot_projects,

        "partners_active": partners_active,
        "sessions_partners_month": sessions_partners_month,

        "alert_items": alert_items,
    }

    return render(request, "trainings/control_center.html", context)