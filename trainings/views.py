from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Sum, Count, Value, DecimalField, Q
from django.db.models.functions import Coalesce, TruncMonth
from django.http import FileResponse
from .models import MercureInvoice, MercureContract
from django.db.models import F, ExpressionWrapper, DateField


import os
from django.conf import settings
from django.utils.encoding import smart_str

from .models import MercureInvoice, MercureContract, MercureInvoiceStatus, MercureContractStatus

from django.db.models.functions import Coalesce

from .models import Session
from .models import TrainingType  # si ton modèle existe bien

from decimal import Decimal

from .forms import BulkRegistrationForm, NewParticipantFormSet
from .forms import MercureInvoiceForm, MercureContractForm

from .models import (
    Client,
    Trainer,
    Session,
    Training,
    Participant,
    Registration,
    RegistrationStatus,
)

from argonteam.models import (
    OneToOneMeeting,
    OneToOneObjective,
    ObjectiveCategory,
    ObjectiveStatus,
    OneToOneStatus,  # si utilisé ailleurs
    ArgonosModule,
    TrainerModuleMastery,
)

try:
    from projects.models import Project, Task
except Exception:
    Project = None
    Task = None


# =========================================================
# Rôles / droits
# =========================================================

def is_trainer_readonly(user) -> bool:
    """Retourne True si l'utilisateur est dans le groupe FORMATEURS."""
    return user.is_authenticated and user.groups.filter(name="FORMATEURS").exists()

from functools import wraps

def get_trainer_for_user(user):
    """
    Retrouve le Trainer associé à l'utilisateur.
    - Essaye Trainer.user (si ce champ existe)
    - Sinon fallback sur email
    """
    if not user.is_authenticated:
        return None

    # 1) Si Trainer a un champ 'user'
    try:
        t = Trainer.objects.filter(user=user).first()
        if t:
            return t
    except Exception:
        pass

    # 2) Fallback email
    user_email = (getattr(user, "email", "") or "").strip()
    if user_email:
        try:
            t = Trainer.objects.filter(email__iexact=user_email).first()
            if t:
                return t
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
        # Managers -> OK
        if not is_trainer_readonly(request.user):
            return view_func(request, *args, **kwargs)

        trainer = get_trainer_for_user(request.user)
        if trainer and (getattr(trainer, "product", "") or "").upper() == Trainer.PRODUCT_MERCURE:
            return view_func(request, *args, **kwargs)

        raise PermissionDenied("Accès réservé aux formateurs Mercure et aux responsables.")
    return _wrapped

def manager_required(view_func):
    """Bloque l'accès aux utilisateurs du groupe FORMATEURS."""
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
    """Mappe ObjectiveStatus -> Task.Status"""
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
    """Met à jour la task liée (si existe)."""
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

    # ✅ Alertes FACTURES Mercure (init pour éviter NameError)
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

    # ✅ DROITS Mercure Paiements
    if not is_trainer_readonly(request.user):
        can_access_mercure = True
    else:
        t = get_trainer_for_user(request.user)
        can_access_mercure = bool(
            t and (getattr(t, "product", "") or "").upper() == Trainer.PRODUCT_MERCURE
        )

    # ✅ Alertes FACTURES Mercure : échéance <= 15 jours (et non payées)
    if can_access_mercure or request.user.is_staff:
        invoices_qs = (
            MercureInvoice.objects
            .select_related("trainer", "session", "session__client", "session__training")
            .exclude(status=MercureInvoiceStatus.PAID)
            .exclude(received_date__isnull=True)
            .exclude(payment_alert_closed=True)   # ✅ ICI
            .annotate(
                due_date_db=ExpressionWrapper(
                    F("received_date") + timedelta(days=60),
                    output_field=DateField(),
                )
            )
        )

        # Si formateur readonly Mercure -> ses factures uniquement
        if is_trainer_readonly(request.user):
            t = get_trainer_for_user(request.user)
            if t:
                invoices_qs = invoices_qs.filter(trainer=t)

        invoices_alerts = invoices_qs.filter(
            due_date_db__gte=today,
            due_date_db__lte=limit,
        ).order_by("due_date_db")

    # ✅ rendre le queryset "stable" + compteur fiable
    invoices_alerts_list = list(invoices_alerts)
    invoices_alerts_count = len(invoices_alerts_list)

    convocations_alerts_list = list(convocations_alerts)
    convocations_alerts_count = len(convocations_alerts_list)

    alerts_total = invoices_alerts_count + convocations_alerts_count
    
    return render(request, "trainings/home.html", {
    "today": today,

    # datasets
    "convocations_alerts": convocations_alerts_list,
    "invoices_alerts": invoices_alerts_list,

    # compteurs
    "convocations_alerts_count": convocations_alerts_count,
    "invoices_alerts_count": invoices_alerts_count,
    "alerts_total": alerts_total,

    "can_access_mercure": can_access_mercure,
    })

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
    return render(request, "trainings/agenda.html")


@login_required
def session_detail_view(request, session_id: int):
    """Fiche session (lecture seule)"""
    s = get_object_or_404(
        Session.objects.select_related(
            "training", "training_type", "client", "trainer", "backup_trainer", "room"
        ),
        id=session_id,
    )
    return render(request, "trainings/session_detail.html", {"s": s})


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
                    cd.get("company_service")
                ]):
                    continue

                p, _created = Participant.objects.get_or_create(
                    email=cd["email"],
                    defaults={
                        "first_name": cd["first_name"],
                        "last_name": cd["last_name"],
                        "company_service": cd.get("company_service") or "",
                        "client": session.client,
                    },
                )

                if p.client_id is None:
                    p.client = session.client
                    p.save(update_fields=["client"])

                selected.append(p)

            for p in selected:
                Registration.objects.get_or_create(
                    session=session,
                    participant=p,
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
    """Renvoie les sessions pour FullCalendar (avec filtres client/formateur)."""
    client_id = request.GET.get("client_id")
    trainer_id = request.GET.get("trainer_id")

    qs = Session.objects.select_related(
        "training", "training_type", "client", "trainer", "backup_trainer", "room"
    )

    if client_id:
        qs = qs.filter(client_id=client_id)
    if trainer_id:
        qs = qs.filter(trainer_id=trainer_id)

    events = []
    for s in qs:
        if getattr(s, "on_client_site", False):
            location = getattr(s, "client_address", "") or ""
        else:
            location = s.room.name if getattr(s, "room", None) else ""

        end_date = getattr(s, "end_date", None) or s.start_date
        end_exclusive = end_date + timedelta(days=1)

        title = s.reference or (s.training.title if s.training else "Session")
        color = _color_for_training(s.training_id or 0)

        events.append({
            "id": s.id,
            "title": title,
            "start": s.start_date.isoformat(),
            "end": end_exclusive.isoformat(),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "detail_url": f"/sessions/{s.id}/",
            "reference": s.reference or "",
            "work_environment": getattr(s, "work_environment", ""),
            "client": s.client.name if s.client else "",
            "training": s.training.title if s.training else "",
            "training_type": s.training_type.name if getattr(s, "training_type", None) else "",
            "trainer": f"{s.trainer.first_name} {s.trainer.last_name}".strip() if s.trainer else "",
            "backup_trainer": (
                f"{s.backup_trainer.first_name} {s.backup_trainer.last_name}".strip()
                if getattr(s, "backup_trainer", None) else ""
            ),
            "location": location,
            "start_date": s.start_date.strftime("%d/%m/%Y") if s.start_date else "",
            "end_date": end_date.strftime("%d/%m/%Y") if end_date else "",
            "status": getattr(s, "status", ""),
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
    s = get_object_or_404(Session, pk=session_id)
    try:
        s.convocation_alert_closed = True
        s.save(update_fields=["convocation_alert_closed"])
    except Exception:
        pass
    return redirect("trainings:home")


# =========================================================
# Dashboard (manager only) - existant
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
# Team (liste)
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

    if selected:
        meetings = OneToOneMeeting.objects.filter(trainer=selected).order_by("-week_start")

        objectives_open = (
            OneToOneObjective.objects
            .filter(trainer=selected)
            .exclude(status="DONE")
            .order_by("-created_at")
        )

        objectives_done = (
            OneToOneObjective.objects
            .filter(trainer=selected, status="DONE")
            .order_by("-created_at")[:25]
        )

        recent_sessions = Session.objects.filter(trainer=selected).order_by("-start_date")[:10]

        this_week_meeting = (
            OneToOneMeeting.objects
            .filter(trainer=selected, week_start=this_week_start)
            .first()
        )
        can_create_this_week = (this_week_meeting is None)

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
    actionable = (request.POST.get("actionable") == "on")

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

    # ✅ correction du bug : obj -> objective
    _create_task_for_objective(objective)

    messages.success(request, "Objectif ajouté ✅")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")


# =========================================================
# Objectifs ArgonOS : toggle / edit / delete
# =========================================================

@require_POST
@login_required
def argonos_objective_toggle(request, objective_id: int):
    o = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(o.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    if o.status == ObjectiveStatus.DONE:
        o.status = ObjectiveStatus.TODO
        messages.info(request, "Objectif rouvert ↩️")
    else:
        o.status = ObjectiveStatus.DONE
        messages.success(request, "Objectif terminé ✅")

    o.save(update_fields=["status"])
    _sync_task_from_objective(o)
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={o.trainer_id}&tab=1to1")


@require_POST
@login_required
def argonos_objective_delete(request, objective_id: int):
    o = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(o.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    trainer_id = o.trainer_id
    o.delete()

    messages.success(request, "Objectif supprimé 🗑️")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer_id}&tab=1to1")


@login_required
def argonos_objective_edit(request, objective_id: int):
    o = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(o.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Titre obligatoire.")
            return redirect(reverse("trainings:argonos_objective_edit", args=[o.id]))

        category = (request.POST.get("category") or o.category).strip()
        valid_categories = {c[0] for c in ObjectiveCategory.choices}
        if category not in valid_categories:
            category = o.category

        due_date = request.POST.get("due_date") or None
        if due_date == "":
            due_date = None

        o.title = title
        o.category = category
        o.due_date = due_date
        o.actionable = request.POST.get("actionable") == "on"
        o.description = (request.POST.get("description") or "").strip()
        o.save()

        messages.success(request, "Objectif modifié ✏️")
        _sync_task_from_objective(o)
        return redirect(f"{reverse('trainings:team_argonos')}?trainer={o.trainer_id}&tab=1to1")

    return render(request, "trainings/argon_edit_objective.html", {
        "o": o,
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

    per_trainer = (
        trainers.annotate(
            objectives_total=Count("one_to_one_objectives", distinct=True),
            objectives_open=Count("one_to_one_objectives", filter=~Q(one_to_one_objectives__status=ObjectiveStatus.DONE), distinct=True),
            objectives_done=Count("one_to_one_objectives", filter=Q(one_to_one_objectives__status=ObjectiveStatus.DONE), distinct=True),
            objectives_blocked=Count("one_to_one_objectives", filter=Q(one_to_one_objectives__status=ObjectiveStatus.BLOCKED), distinct=True),
            objectives_overdue=Count(
                "one_to_one_objectives",
                filter=Q(one_to_one_objectives__due_date__lt=today) & ~Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
                distinct=True,
            ),
            objectives_due_soon=Count(
                "one_to_one_objectives",
                filter=Q(one_to_one_objectives__due_date__gte=today) & Q(one_to_one_objectives__due_date__lte=soon_limit) & ~Q(one_to_one_objectives__status=ObjectiveStatus.DONE),
                distinct=True,
            ),
        )
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
    for t in per_trainer:
        validated = validated_map.get(t.id, 0)
        ratio = round((validated / modules_active_count) * 100) if modules_active_count else None
        rows.append({
            "trainer": t,
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

# ==============================================================
# Dashboard_ca
# ==============================================================

# ==============================================================
# Dashboard CA (filtres + clic histogramme)
# ==============================================================

@login_required
@manager_required
def dashboard_ca_view(request):
    today = timezone.localdate()

    # ----------------------------
    # 1) Lire les filtres (GET)
    # ----------------------------
    training_type_id = (request.GET.get("training_type") or "").strip()  # ex: "3"
    period = (request.GET.get("period") or "all").strip()               # all|year|quarter|month
    view_mode = (request.GET.get("view") or "all").strip()              # all|realise|previsionnel

    # ✅ clic histogramme : month=YYYY-MM
    month_str = (request.GET.get("month") or "").strip()

    # ----------------------------
    # 2) Base queryset + ca_date (end_date sinon start_date)
    # ----------------------------
    qs = (
        Session.objects
        .select_related("training", "training_type", "client")
        .annotate(ca_date=Coalesce("end_date", "start_date"))
    )

    # ----------------------------
    # 3) Filtre: produit (TrainingType)
    # ----------------------------
    if training_type_id.isdigit():
        qs = qs.filter(training_type_id=int(training_type_id))

    # ----------------------------
    # 4) Filtre: période (bornes sur ca_date)
    # ----------------------------
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

    # ----------------------------
    # 5) Filtre: vue (réalisé / prévisionnel)
    # ----------------------------
    if view_mode == "realise":
        qs = qs.filter(ca_date__lte=today)
    elif view_mode == "previsionnel":
        qs = qs.filter(ca_date__gt=today)

    # ----------------------------
    # 6) Filtre: clic histogramme (mois exact)
    # ----------------------------
    # Exemple: month=2026-03 => ca_date__year=2026, ca_date__month=3
    if month_str:
        try:
            y_str, m_str = month_str.split("-")
            y = int(y_str)
            m = int(m_str)
            if 1 <= m <= 12:
                qs = qs.filter(ca_date__year=y, ca_date__month=m)
        except Exception:
            pass

    # ----------------------------
    # 7) KPI CA
    # ----------------------------
    ZERO_DEC = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))

    ca_total = qs.aggregate(v=Coalesce(Sum("price_ht"), ZERO_DEC))["v"]
    ca_realise = qs.filter(ca_date__lte=today).aggregate(v=Coalesce(Sum("price_ht"), ZERO_DEC))["v"]
    ca_previsionnel = qs.filter(ca_date__gt=today).aggregate(v=Coalesce(Sum("price_ht"), ZERO_DEC))["v"]

    # ----------------------------
    # 8) Graphe 1 : CA par mois (sur le qs filtré)
    # ----------------------------
    month_map: dict[str, Decimal] = {}
    for s in qs.exclude(ca_date__isnull=True):
        d = getattr(s, "ca_date", None)
        if not d:
            continue
        key = d.strftime("%Y-%m")
        month_map[key] = month_map.get(key, Decimal("0.00")) + (s.price_ht or Decimal("0.00"))

    labels_month = []
    values_month = []
    for k in sorted(month_map.keys()):
        labels_month.append(k)
        values_month.append(float(month_map[k]))

    # ----------------------------
    # 9) Graphe 2 : répartition produit (sur le qs filtré)
    # ----------------------------
    by_type = (
        qs.values("training_type__name")
        .annotate(total=Coalesce(Sum("price_ht"), ZERO_DEC))
        .order_by("-total")
    )
    labels_type = [row["training_type__name"] or "Sans type" for row in by_type]
    values_type = [float(row["total"] or 0) for row in by_type]

    # ----------------------------
    # 10) KPI Sessions + table
    # ----------------------------
    total_sessions = qs.count()
    status_rows = qs.values("status").annotate(c=Count("id")).order_by("-c")

    status_counts = []
    for r in status_rows:
        raw = (r["status"] or "").strip()
        status_counts.append({"label": raw if raw else "—", "count": r["c"]})

    sessions = qs.order_by("-ca_date", "-start_date")

    return render(request, "trainings/dashboard_ca.html", {
        "today": today,
        "sessions": sessions,

        "ca_total": ca_total,
        "ca_realise": ca_realise,
        "ca_previsionnel": ca_previsionnel,

        "labels_month": labels_month,
        "values_month": values_month,
        "labels_type": labels_type,
        "values_type": values_type,

        "total_sessions": total_sessions,
        "status_counts": status_counts,

        # état filtres (utile pour l’UI + bouton reset)
        "f_training_type": training_type_id,
        "f_period": period,
        "f_view": view_mode,
        "f_month": month_str,
    })

# =======================================================
# Gestion des prestations Mercure
# =======================================================

def get_trainer_for_user(user):
    """
    Retrouve le Trainer associé à l'utilisateur.
    - Essaye Trainer.user (si ce champ existe)
    - Sinon fallback sur email
    Ne plante jamais si le champ user n'existe pas.
    """
    if not user.is_authenticated:
        return None

    # ✅ 1) Si Trainer a un champ 'user'
    try:
        t = Trainer.objects.filter(user=user).first()
        if t:
            return t
    except Exception:
        # pas de champ user -> on ignore
        pass

    # ✅ 2) Fallback email (si Trainer.email existe et user.email renseigné)
    user_email = (getattr(user, "email", "") or "").strip()
    if user_email:
        try:
            t = Trainer.objects.filter(email__iexact=user_email).first()
            if t:
                return t
        except Exception:
            pass

    return None


from functools import wraps

def mercure_only_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        # Managers -> OK
        if not is_trainer_readonly(request.user):
            return view_func(request, *args, **kwargs)

        # Formateurs -> seulement Mercure
        trainer = get_trainer_for_user(request.user)
        if trainer and (getattr(trainer, "product", "") or "").upper() == Trainer.PRODUCT_MERCURE:
            return view_func(request, *args, **kwargs)

        raise PermissionDenied("Accès réservé aux formateurs Mercure et aux responsables.")
    return _wrapped


@login_required
@mercure_only_required


@login_required
@mercure_only_required
def dashboard_mercure_paiements_view(request):
    today = timezone.localdate()
    trainer = get_trainer_for_user(request.user)

    # ✅ Liste des formateurs Mercure (pour le filtre)
    mercure_trainers = Trainer.objects.filter(
        product=Trainer.PRODUCT_MERCURE
    ).order_by("last_name", "first_name")

    # ✅ Lire filtre GET (uniquement utile pour manager)
    selected_trainer_id = (request.GET.get("trainer") or "").strip()

    # Base queryset
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

    # ✅ Filtre formateur (GET) — managers uniquement, Mercure only
    selected_trainer_id = (request.GET.get("trainer") or "").strip()

    # Si formateur Mercure (readonly), on force ses lignes
    if is_trainer_readonly(request.user) and trainer:
        invoices_qs = invoices_qs.filter(trainer=trainer)
        contracts_qs = contracts_qs.filter(trainer=trainer)
        selected_trainer_id = str(trainer.id)

    # Sinon manager : appliquer filtre si choisi
    elif selected_trainer_id.isdigit():
        tid = int(selected_trainer_id)
        if mercure_trainers.filter(id=tid).exists():  # sécurité: Mercure only
            invoices_qs = invoices_qs.filter(trainer_id=tid)
            contracts_qs = contracts_qs.filter(trainer_id=tid)
        else:
            selected_trainer_id = ""
            
    # ✅ Cas 1 : formateur readonly => on force ses lignes
    if is_trainer_readonly(request.user) and trainer:
        invoices_qs = invoices_qs.filter(trainer=trainer)
        contracts_qs = contracts_qs.filter(trainer=trainer)
        selected_trainer_id = str(trainer.id)  # pour pré-sélectionner l’UI

    # ✅ Cas 2 : manager => applique le filtre choisi (Mercure only)
    elif selected_trainer_id.isdigit():
        tid = int(selected_trainer_id)
        # sécurité : n'autoriser que les formateurs Mercure dans ce filtre
        if mercure_trainers.filter(id=tid).exists():
            invoices_qs = invoices_qs.filter(trainer_id=tid)
            contracts_qs = contracts_qs.filter(trainer_id=tid)
        else:
            selected_trainer_id = ""  # invalide -> reset

    # KPIs
    ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))

    total_facture = invoices_qs.aggregate(v=Coalesce(Sum("amount_ht"), ZERO))["v"]
    total_paye = invoices_qs.filter(status=MercureInvoiceStatus.PAID).aggregate(v=Coalesce(Sum("amount_ht"), ZERO))["v"]
    total_non_paye = invoices_qs.exclude(status=MercureInvoiceStatus.PAID).aggregate(v=Coalesce(Sum("amount_ht"), ZERO))["v"]

    # Overdue (via property => Python)
    invoices_list = list(invoices_qs.order_by("-received_date", "-created_at"))
    overdue_count = sum(1 for inv in invoices_list if inv.is_overdue)

    # Contrats "due soon" (via property => Python)
    contracts_list = list(contracts_qs.order_by("session__start_date"))
    due_soon_count = sum(1 for c in contracts_list if c.is_due_soon)

    return render(request, "trainings/dashboard_mercure_paiements.html", {
        "today": today,

        # datasets
        "invoices": invoices_list,
        "contracts": contracts_list,

        # KPIs
        "kpi_total_facture": total_facture,
        "kpi_total_paye": total_paye,
        "kpi_total_non_paye": total_non_paye,
        "kpi_overdue_count": overdue_count,
        "kpi_contract_due_soon": due_soon_count,

        # contexte
        "trainer": trainer,
        "is_manager": (not is_trainer_readonly(request.user)),

        # ✅ filtres UI
        "mercure_trainers": mercure_trainers,
        "f_trainer": selected_trainer_id,
    })
# trainings/views.py
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import MercureInvoiceForm, MercureContractForm
from .models import Trainer

# ⚠️ on réutilise tes helpers existants :
# - mercure_only_required
# - get_trainer_for_user
# - is_trainer_readonly

@login_required
@mercure_only_required
def mercure_invoice_create_view(request):
    today = timezone.localdate()
    trainer = get_trainer_for_user(request.user)

    initial = {}
    # Pré-remplir trainer si formateur Mercure
    if is_trainer_readonly(request.user) and trainer:
        initial["trainer"] = trainer

    # Pré-remplir session si ?session=ID
    sid = request.GET.get("session")
    if sid and sid.isdigit():
        initial["session"] = int(sid)

    if request.method == "POST":
        form = MercureInvoiceForm(request.POST)
        # si formateur readonly, forcer trainer côté serveur
        if is_trainer_readonly(request.user) and trainer:
            obj = form.save(commit=False)
            obj.trainer = trainer
            obj.save()
            messages.success(request, "Facture enregistrée ✅")
            return redirect("trainings:dashboard_mercure_paiements")

        if form.is_valid():
            form.save()
            messages.success(request, "Facture enregistrée ✅")
            return redirect("trainings:dashboard_mercure_paiements")
    else:
        form = MercureInvoiceForm(initial=initial)

        # si readonly : empêcher de changer trainer côté UI
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

        if is_trainer_readonly(request.user) and trainer:
            obj = form.save(commit=False)
            obj.trainer = trainer
            obj.save()
            messages.success(request, "Contrat enregistré ✅")
            return redirect("trainings:dashboard_mercure_paiements")

        if form.is_valid():
            form.save()
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

import os
import glob
from django.conf import settings
from django.http import FileResponse, Http404
from django.utils.encoding import smart_str

@login_required
@mercure_only_required
def mercure_invoice_open_view(request, invoice_id: int):
    inv = get_object_or_404(MercureInvoice, pk=invoice_id)

    raw = (inv.document_path or "").strip()
    if not raw:
        raise Http404("Aucun document associé à cette facture.")

    path = os.path.normpath(raw)

    # Optionnel : limiter à une base autorisée
    base_dir = getattr(settings, "MERCURE_INVOICES_BASE_DIR", None)
    if base_dir:
        base_norm = os.path.normpath(base_dir)
        if not path.lower().startswith(base_norm.lower()):
            raise Http404("Chemin non autorisé.")

    # ✅ Si c'est un dossier -> on prend le 1er PDF trouvé
    if os.path.isdir(path):
        try:
            pdfs = sorted(glob.glob(os.path.join(path, "*.pdf")))
        except PermissionError:
            raise Http404("Accès refusé au dossier de facture (droits insuffisants).")

        if not pdfs:
            raise Http404("Aucun PDF trouvé dans le dossier de facture.")
        file_path = pdfs[0]
    else:
        file_path = path

    # ✅ Vérif existence + accès
    if not os.path.exists(file_path):
        raise Http404("Fichier introuvable sur le serveur.")

    try:
        filename = os.path.basename(file_path)
        resp = FileResponse(open(file_path, "rb"), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{smart_str(filename)}"'
        return resp
    except PermissionError:
        raise Http404("Accès refusé au fichier de facture (droits insuffisants).")


@login_required
@mercure_only_required
def mercure_invoice_detail_view(request, invoice_id: int):
    inv = get_object_or_404(
        MercureInvoice.objects.select_related("session", "session__client", "session__training", "trainer"),
        pk=invoice_id,
    )

    # ✅ Sécurité : si formateur readonly, uniquement ses lignes
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
    c = get_object_or_404(
        MercureContract.objects.select_related("session", "session__client", "session__training", "trainer"),
        pk=contract_id,
    )

    me = get_trainer_for_user(request.user)
    if is_trainer_readonly(request.user) and me and c.trainer_id != me.id:
        raise PermissionDenied("Accès réservé.")

    return render(request, "trainings/mercure_contract_detail.html", {
        "c": c,
        "today": timezone.localdate(),
    })