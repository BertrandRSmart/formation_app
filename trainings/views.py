from datetime import timedelta, date

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.urls import reverse
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from argonteam.models import (
    OneToOneMeeting,
    OneToOneObjective,
    ObjectiveCategory,
    ObjectiveStatus,
)
from .forms import BulkRegistrationForm, NewParticipantFormSet
from .models import (
    Client,
    Trainer,
    Session,
    Training,
    Participant,
    Registration,
    RegistrationStatus,
)


# =========================================================
# Rôles / droits
# =========================================================

def is_trainer_readonly(user) -> bool:
    """Retourne True si l'utilisateur est dans le groupe FORMATEURS."""
    return user.is_authenticated and user.groups.filter(name="FORMATEURS").exists()


def manager_required(view_func):
    """Bloque l'accès aux utilisateurs du groupe FORMATEURS."""
    def _wrapped(request, *args, **kwargs):
        if is_trainer_readonly(request.user):
            raise PermissionDenied("Accès réservé aux responsables.")
        return view_func(request, *args, **kwargs)
    return _wrapped


# =========================================================
# Helpers (couleur)
# =========================================================

def _color_for_training(training_id: int) -> str:
    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]
    return palette[(training_id or 0) % len(palette)]


# =========================================================
# Pages
# =========================================================

@login_required
def home_view(request):
    """
    Home dashboard.
    - today
    - convocations_alerts: sessions dans <= 15 jours dont l'alerte n'est pas fermée
    """
    today = date.today()
    limit = today + timedelta(days=15)

    qs = Session.objects.select_related("training", "client").filter(
        start_date__gte=today,
        start_date__lte=limit,
    )

    # Champ optionnel (si absent, on ne plante pas)
    try:
        qs = qs.filter(convocation_alert_closed__in=[False, None])
    except Exception:
        pass

    convocations_alerts = qs.order_by("start_date")

    return render(request, "trainings/home.html", {
        "today": today,
        "convocations_alerts": convocations_alerts,
    })


@login_required
def team_home(request):
    """Nouvelle page Équipe (placeholder)."""
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

            # 1) participants existants sélectionnés
            selected = list(form.cleaned_data["existing_participants"])

            # 2) nouveaux participants (créés et auto-liés au client de la session)
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

                # si existait déjà, on peut éventuellement mettre à jour le client si vide
                if p.client_id is None:
                    p.client = session.client
                    p.save(update_fields=["client"])

                selected.append(p)

            # 3) créer les registrations
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
        try:
            selected_session = Session.objects.select_related("training", "client").get(pk=sid)
        except Session.DoesNotExist:
            selected_session = None

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
        # Lieu : salle OU adresse client
        if getattr(s, "on_client_site", False):
            location = getattr(s, "client_address", "") or ""
        else:
            location = s.room.name if getattr(s, "room", None) else ""

        # FullCalendar: end exclusive pour allDay
        # (si end_date manquait, on retombe sur start_date)
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
        # si le champ n'existe pas, on évite de planter
        pass
    return redirect("trainings:home")


# =========================================================
# Dashboard (manager only)
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
# Team Argonos et Mercure
# =========================================================

@login_required
def team(request):
    product = (request.GET.get("product") or Trainer.PRODUCT_ARGONOS).upper()

    if product not in (Trainer.PRODUCT_ARGONOS, Trainer.PRODUCT_MERCURE):
        product = Trainer.PRODUCT_ARGONOS

    trainers = (
        Trainer.objects
        .filter(product=product)
        .order_by("last_name", "first_name")
    )

    label = "ArgonOS" if product == Trainer.PRODUCT_ARGONOS else "Mercure"

    return render(
        request,
        "trainings/team.html",
        {"trainers": trainers, "product": product, "product_label": label},
    )

from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import Trainer, Session
from argonteam.models import OneToOneMeeting, OneToOneObjective, OneToOneStatus


from datetime import timedelta
from django.utils import timezone
from argonteam.models import OneToOneMeeting, OneToOneObjective


from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .models import Trainer, Session

from argonteam.models import (
    OneToOneMeeting,
    OneToOneObjective,
    OneToOneStatus,
    ArgonosModule,
    TrainerModuleMastery,
)

def _monday_of_week(d):
    return d - timedelta(days=d.weekday())


@login_required
def team_argonos(request):
    # ✅ liste formateurs ArgonOS
    trainers = Trainer.objects.filter(product="ARGONOS").order_by("last_name", "first_name")

    # ✅ formateur sélectionné
    trainer_id = request.GET.get("trainer")
    selected = None
    if trainer_id:
        selected = trainers.filter(id=trainer_id).first()
    if not selected and trainers.exists():
        selected = trainers.first()

    # ✅ onglet
    tab = (request.GET.get("tab") or "detail").strip().lower()
    if tab not in ("detail", "1to1"):
        tab = "detail"

    # ✅ données 1to1
    meetings = OneToOneMeeting.objects.none()
    objectives_open = OneToOneObjective.objects.none()
    objectives_done = OneToOneObjective.objects.none()
    recent_sessions = Session.objects.none()

    # ✅ semaine en cours (pour le bloc 1to1)
    today = timezone.localdate()
    this_week_start = _monday_of_week(today)
    this_week_meeting = None
    this_week_objectives = OneToOneObjective.objects.none()
    if this_week_meeting:
        this_week_objectives = (
            this_week_meeting.objectives.all().order_by("-created_at")
        )
    can_create_this_week = False

    # ✅ progression modules (pour l’onglet Détail)
    module_rows = []
    modules_count = 0

    if selected:
        # ---- 1to1 ----
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

        # ---- Modules / mastery ----
        modules = ArgonosModule.objects.filter(is_active=True).order_by("kind", "level", "name")
        modules_count = modules.count()

        existing = TrainerModuleMastery.objects.filter(trainer=selected, module__in=modules)
        existing_by_module_id = {m.module_id: m for m in existing}

        # ✅ option pratique : créer automatiquement les lignes manquantes (idempotent)
        missing = []
        for mod in modules:
            if mod.id not in existing_by_module_id:
                missing.append(TrainerModuleMastery(trainer=selected, module=mod))
        if missing:
            TrainerModuleMastery.objects.bulk_create(missing, ignore_conflicts=True)
            # recharge
            existing = TrainerModuleMastery.objects.filter(trainer=selected, module__in=modules)
            existing_by_module_id = {m.module_id: m for m in existing}

        # construire les lignes affichées
        for mod in modules:
            mastery = existing_by_module_id.get(mod.id)
            module_rows.append({
                "module": mod,
                "mastery": mastery,
            })

    return render(request, "trainings/team_argonos.html", {
        "trainers": trainers,
        "selected": selected,
        "tab": tab,

        # 1to1
        "meetings": meetings,
        "objectives_open": objectives_open,
        "objectives_done": objectives_done,
        "recent_sessions": recent_sessions,
        "this_week_start": this_week_start,
        "this_week_meeting": this_week_meeting,
        "this_week_objectives": this_week_objectives,
        "can_create_this_week": can_create_this_week,

        # modules
        "module_rows": module_rows,
        "modules_count": modules_count,
    })

    this_week_meeting = (
    OneToOneMeeting.objects
    .filter(trainer=selected, week_start=this_week_start)
    .first()
    )
    can_create_this_week = (this_week_meeting is None)

    this_week_objectives = OneToOneObjective.objects.none()
    if this_week_meeting:
        this_week_objectives = this_week_meeting.objectives.all().order_by("-created_at")

from django.shortcuts import get_object_or_404
from argonteam.models import OneToOneMeeting

@login_required
def create_one_to_one_argonos(request):
    trainer_id = request.GET.get("trainer")
    trainer = get_object_or_404(Trainer, id=trainer_id, product="ARGONOS")

    # lundi de la semaine courante
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())

    # créer si pas existant
    OneToOneMeeting.objects.get_or_create(
        trainer=trainer,
        week_start=week_start,
        defaults={"meeting_date": today},
    )

    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")



def _monday_of_week(d):
    return d - timedelta(days=d.weekday())


# trainings/views.py

from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from argonteam.models import (
    OneToOneMeeting,
    OneToOneObjective,
    ObjectiveCategory,
    ObjectiveStatus,
)
from .models import Trainer


def _monday_of_week(d):
    return d - timedelta(days=d.weekday())


from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from argonteam.models import OneToOneMeeting, OneToOneObjective, ObjectiveCategory, ObjectiveStatus
from .models import Trainer


def _monday_of_week(d):
    return d - timedelta(days=d.weekday())


@login_required
def add_objective_this_week_argonos(request):
    """
    GET  -> affiche la page dédiée (argon_add_objective.html)
    POST -> crée l'objectif puis redirige vers team_argonos onglet 1to1
    """
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

    # POST
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

    OneToOneObjective.objects.create(
        trainer=trainer,
        meeting=meeting,
        title=title,
        category=category,
        status=ObjectiveStatus.TODO,
        actionable=actionable,
        description=description,
        due_date=due_date,
    )

    messages.success(request, "Objectif ajouté ✅")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")
from django.urls import path
from . import views
from .views import bulk_registrations
from . import views_manage

app_name = "trainings"

urlpatterns = [
    # Home / pages principales
    path("", views.home_view, name="home"),
    path("agenda/", views.agenda_view, name="agenda"),
    path("dashboard/", views.dashboard_view, name="dashboard"),

    # ✅ Pages Équipe
    
    # ✅ Pages Équipe
    # ✅ Pages Équipe
    path("team/", views.team, name="team"),
    path("team/argonos/", views.team_argonos, name="team_argonos"),
    path("team/argonos/create-1to1/", views.create_one_to_one_argonos, name="create_one_to_one_argonos"),
    path("team/argonos/add-objective/", views.add_objective_this_week_argonos, name="add_objective_this_week_argonos"),
    
    path("team/home/", views.team_home, name="team_home"),

    # Alertes convocations
    path("alerts/convocations/<int:session_id>/dismiss/", views.dismiss_convocation_alert, name="dismiss_convocation_alert"),

    # API
    path("api/sessions/", views.sessions_json, name="sessions_json"),
    path("api/trainings/", views.trainings_by_type_json, name="trainings_by_type_json"),
    path("api/clients/", views.clients_list_json, name="clients_list_json"),
    path("api/trainers/", views.trainers_list_json, name="trainers_list_json"),
    path("api/trainings-legend/", views.trainings_legend_json, name="trainings_legend_json"),

    # Détail session existant
    path("sessions/<int:session_id>/", views.session_detail_view, name="session_detail"),

    # Inscriptions en masse
    path("inscriptions/", bulk_registrations, name="bulk_registrations"),

    # Gestion formations (board)
    path("formations/", views_manage.training_manage_home, name="training_manage_home"),

    # Gestion participants (add/edit/delete)
    path("formations/<int:session_id>/participants/add/", views_manage.session_participant_add, name="session_participant_add"),
    path("formations/<int:session_id>/participants/<int:registration_id>/edit/", views_manage.session_participant_edit, name="session_participant_edit"),
    path("formations/<int:session_id>/participants/<int:registration_id>/delete/", views_manage.session_participant_delete, name="session_participant_delete"),

    # Export CSV
    path("formations/<int:session_id>/export-csv/", views_manage.export_participants_csv, name="export_participants_csv"),
]

from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from argonteam.models import (
    OneToOneMeeting,
    OneToOneObjective,
    ObjectiveCategory,
    ObjectiveStatus,
)

from django.views.decorators.http import require_POST

def _objective_valid_categories():
    return {c[0] for c in ObjectiveCategory.choices}

def _objective_valid_statuses():
    return {s[0] for s in ObjectiveStatus.choices}

from django.views.decorators.http import require_POST
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from argonteam.models import OneToOneObjective, ObjectiveStatus


@require_POST
@login_required
def argonos_objective_toggle(request, objective_id: int):
    obj = get_object_or_404(OneToOneObjective, pk=objective_id)

    # petit garde-fou si tu veux limiter à ArgonOS
    if getattr(obj.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    obj.status = ObjectiveStatus.TODO if obj.status == ObjectiveStatus.DONE else ObjectiveStatus.DONE
    obj.save(update_fields=["status"])

    messages.success(request, "Statut mis à jour ✅")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={obj.trainer_id}&tab=1to1")


@require_POST
@login_required
def argonos_objective_delete(request, objective_id: int):
    obj = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(obj.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    trainer_id = obj.trainer_id
    obj.delete()

    messages.success(request, "Objectif supprimé 🗑️")
    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer_id}&tab=1to1")


@login_required
def argonos_objective_edit(request, objective_id: int):
    obj = get_object_or_404(OneToOneObjective, pk=objective_id)

    if getattr(obj.trainer, "product", "") != "ARGONOS":
        messages.error(request, "Objectif non ArgonOS.")
        return redirect("trainings:team_argonos")

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()
        due_date = request.POST.get("due_date") or None
        actionable = request.POST.get("actionable") == "on"

        if not title:
            messages.error(request, "Titre obligatoire.")
            return redirect(reverse("trainings:argonos_objective_edit", args=[obj.id]))

        obj.title = title
        obj.description = description
        obj.due_date = due_date
        obj.actionable = actionable
        obj.save(update_fields=["title", "description", "due_date", "actionable"])

        messages.success(request, "Objectif modifié ✏️")
        return redirect(f"{reverse('trainings:team_argonos')}?trainer={obj.trainer_id}&tab=1to1")

    # GET
    return render(request, "trainings/argon_edit_objective.html", {"o": obj})