# trainings/views_manage.py
print("✅ LOADED trainings/views_manage.py")

from datetime import date
import csv
import os

from django.contrib import messages
from django.db.models import Q, Count
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from urllib.parse import urlencode

from .models import Session, Registration, Client, Trainer, TrainingType, RegistrationStatus
from .forms_manage import ParticipantForm, RegistrationMiniForm
from .views import manager_required
from django.http import FileResponse, Http404
from .services.invitations import generate_invitation_for_registration

from .services.participants import get_or_create_participant_identity

# =========================================================
# Helpers
# =========================================================

def _current_filter_params(request):
    """
    Construit un dict de params GET à conserver dans les href / redirects.
    On exclut "drawer" (UI), et on garde "session" si présent.
    """
    keys = ("month", "client", "trainer", "product", "status", "q", "session")
    params = {}
    for k in keys:
        v = (request.GET.get(k) or "").strip()
        if v:
            params[k] = v
    return params


def _redirect_to_manage_home(request, **overrides):
    """
    Redirect vers /formations/ en conservant les filtres courants.
    overrides permet d’imposer session=..., etc.
    """
    params = _current_filter_params(request)
    params.update({k: v for k, v in overrides.items() if v not in (None, "", False)})

    base = redirect("trainings:training_manage_home")
    if params:
        return redirect(f"{base.url}?{urlencode(params)}")
    return base


# =========================================================
# Board Sessions
# =========================================================

@manager_required
def training_manage_home(request):
    # ✅ Persist filters in session (avant tout)
    FILTER_KEYS = ("month", "client", "trainer", "product", "status", "q")
    SESSION_KEY = "manage_sessions_filters"

    # Reset explicite
    if request.GET.get("reset") == "1":
        request.session.pop(SESSION_KEY, None)
        return redirect("trainings:training_manage_home")

    # Arrivée sans paramètres => réappliquer les derniers filtres
    # (on évite de boucler si session vide)
    if not request.GET:
        saved = request.session.get(SESSION_KEY) or {}
        if saved:
            return redirect(f"{request.path}?{urlencode(saved)}")

    # Enregistrer les filtres actuels (uniquement ceux renseignés)
    current = {}
    for k in FILTER_KEYS:
        v = (request.GET.get(k) or "").strip()
        if v:
            current[k] = v
    request.session[SESSION_KEY] = current
    request.session.modified = True

    # --- Lire GET ---
    month = (request.GET.get("month") or "").strip()          # "YYYY-MM"
    client_id = (request.GET.get("client") or "").strip()
    trainer_id = (request.GET.get("trainer") or "").strip()
    product_id = (request.GET.get("product") or "").strip()   # ✅ NOUVEAU
    status = (request.GET.get("status") or "").strip()        # upcoming/ongoing/done
    selected_id = (request.GET.get("session") or "").strip()
    q = (request.GET.get("q") or "").strip()

    today = date.today()

    qs = (
        Session.objects
        .select_related("training", "training_type", "client", "trainer")
        .all()
    )

    # --- Filtres ---
    if month:
        try:
            y, m = month.split("-")
            qs = qs.filter(start_date__year=int(y), start_date__month=int(m))
        except ValueError:
            pass

    if client_id.isdigit():
        qs = qs.filter(client_id=int(client_id))

    if trainer_id.isdigit():
        qs = qs.filter(trainer_id=int(trainer_id))

    # ✅ Filtre PRODUIT (TrainingType)
    if product_id.isdigit():
        pid = int(product_id)
        qs = qs.filter(Q(training_type_id=pid) | Q(training__training_type_id=pid))

    if status == "upcoming":
        qs = qs.filter(start_date__gt=today)
    elif status == "ongoing":
        qs = qs.filter(start_date__lte=today, end_date__gte=today)
    elif status == "done":
        qs = qs.filter(end_date__lt=today)

    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(training__title__icontains=q)
            | Q(training__name__icontains=q)
            | Q(client__name__icontains=q)
            | Q(trainer__first_name__icontains=q)
            | Q(trainer__last_name__icontains=q)
        )

    sessions_count = qs.count()
    sessions = list(qs.order_by("-start_date", "-id")[:300])

    # --- Compteur participants par session ---
    session_ids = [s.id for s in sessions]
    participants_count_by_session = {}
    if session_ids:
        counts_qs = (
            Registration.objects
            .filter(session_id__in=session_ids)
            .values("session_id")
            .annotate(c=Count("id"))
        )
        participants_count_by_session = {row["session_id"]: row["c"] for row in counts_qs}

    # --- Session sélectionnée + inscriptions ---
    selected_session = None
    registrations = Registration.objects.none()
    p_form = None

    if selected_id.isdigit():
        selected_session = get_object_or_404(Session, pk=int(selected_id))
        registrations = (
            Registration.objects
            .filter(session=selected_session)
            .select_related("participant")
            .order_by("participant__last_name", "participant__first_name")
        )
        p_form = ParticipantForm()

    # --- Listes filtres ---
    clients = Client.objects.order_by("name")
    trainers = Trainer.objects.order_by("last_name", "first_name")
    months = [f"{today.year}-{mm:02d}" for mm in range(1, 13)]
    training_types = TrainingType.objects.order_by("name")

    return render(request, "trainings/manage_sessions_board.html", {
        "sessions": sessions,
        "sessions_count": sessions_count,
        "participants_count_by_session": participants_count_by_session,

        "selected_session": selected_session,
        "registrations": registrations,
        "selected_id": selected_id,

        "clients": clients,
        "trainers": trainers,
        "training_types": training_types,

        # valeurs filtres (pour template)
        "months": months,
        "today": today,
        "month": month,
        "client_id": client_id,
        "trainer_id": trainer_id,
        "product_id": product_id,
        "status": status,
        "q": q,

        "p_form": p_form,
    })


# =========================================================
# Participants
# =========================================================


@manager_required
def session_participant_add(request, session_id):
    from .views import check_initiation_prereq  # import local pour éviter les soucis de circular import

    session = get_object_or_404(
        Session.objects.select_related("training", "training_type", "training__training_type"),
        pk=session_id
    )

    if request.method == "POST":
        p_form = ParticipantForm(request.POST)

        if p_form.is_valid():
            cd = p_form.cleaned_data

            first_name = cd.get("first_name") or ""
            last_name = cd.get("last_name") or ""
            email = cd.get("email") or ""
            company_service = cd.get("company_service") or ""
            client = cd.get("client")
            referrer = cd.get("referrer")

            # on lit le flag envoyé par le bouton "Forcer l’inscription"
            force_prerequisite = (request.POST.get("force_prerequisite") == "1")

            # vérification prérequis uniquement si on ne force pas
            if not force_prerequisite:
                ok, msg = check_initiation_prereq(session, email)
                if not ok:
                    messages.error(request, msg)
                    return _redirect_to_manage_home(request, session=session.id)

            participant, created_participant = get_or_create_participant_identity(
                first_name=first_name,
                last_name=last_name,
                email=email,
                client_id=client.id if client else None,
                company_service=company_service,
                referrer_id=referrer.id if referrer else None,
            )

            # éviter les doublons d'inscription
            reg, created_registration = Registration.objects.get_or_create(
                session=session,
                participant=participant,
                defaults={"status": RegistrationStatus.INVITED},
            )

            if created_registration:
                reg.save()  # force le calcul initial
                session.recalculate_prices(save=True)

                if created_participant:
                    if force_prerequisite:
                        messages.warning(
                            request,
                            "Nouveau participant créé et ajouté avec dérogation de prérequis ⚠️"
                        )
                    else:
                        messages.success(request, "Nouveau participant créé et ajouté à la session ✅")
                else:
                    if force_prerequisite:
                        messages.warning(
                            request,
                            "Participant existant réutilisé et ajouté avec dérogation de prérequis ⚠️"
                        )
                    else:
                        messages.success(request, "Participant existant réutilisé et ajouté à la session ✅")
            else:
                session.recalculate_prices(save=True)
                messages.info(request, "Ce participant est déjà inscrit à cette session.")

        else:
            messages.error(request, "Formulaire invalide. Vérifie les champs.")

    return _redirect_to_manage_home(request, session=session.id)
    
@manager_required
def session_participant_edit(request, session_id, registration_id):
    session = get_object_or_404(Session, pk=session_id)
    reg = get_object_or_404(
        Registration.objects.select_related("participant"),
        pk=registration_id,
        session=session
    )

    if request.method == "POST":
        p_form = ParticipantForm(request.POST, instance=reg.participant)
        r_form = RegistrationMiniForm(request.POST, instance=reg)

        if p_form.is_valid() and r_form.is_valid():
            p_form.save()
            reg = r_form.save()
            session.recalculate_prices(save=True)
            messages.success(request, "Participant mis à jour ✅")
            return _redirect_to_manage_home(request, session=session.id)

        messages.error(request, "Formulaire invalide. Vérifie les champs.")
    else:
        p_form = ParticipantForm(instance=reg.participant)
        r_form = RegistrationMiniForm(instance=reg)

    return render(request, "trainings/manage_participant_form.html", {
        "session": session,
        "reg": reg,
        "p_form": p_form,
        "r_form": r_form,
        "mode": "edit",
    })


@manager_required
@require_POST
def session_participant_delete(request, session_id, registration_id):
    session = get_object_or_404(Session, pk=session_id)
    reg = get_object_or_404(Registration, pk=registration_id, session=session)
    reg.delete()
    session.recalculate_prices(save=True)
    messages.success(request, "Participant retiré de la session ✅")

    return _redirect_to_manage_home(request, session=session.id)


@manager_required
def export_participants_csv(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    regs = (
        Registration.objects
        .filter(session=session)
        .select_related("participant")
        .order_by("participant__last_name", "participant__first_name")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="participants_session_{session_id}.csv"'

    writer = csv.writer(response)
    writer.writerow(["Nom", "Prénom", "Email"])

    for r in regs:
        p = r.participant
        writer.writerow([p.last_name, p.first_name, p.email])

    return response


@manager_required
@require_POST
def session_participant_set_status(request, session_id, registration_id):
    reg = get_object_or_404(Registration, pk=registration_id, session_id=session_id)
    status = (request.POST.get("status") or "").strip()

    valid = {c[0] for c in RegistrationStatus.choices}
    if status not in valid:
        messages.error(request, "Statut invalide.")
        return _redirect_to_manage_home(request, session=session_id)

    reg.status = status

    if status == RegistrationStatus.CANCELED and not reg.canceled_at:
        reg.canceled_at = date.today()

    if status != RegistrationStatus.CANCELED:
        reg.canceled_at = None

    reg.save()
    session = reg.session
    session.recalculate_prices(save=True)

    messages.success(request, "Statut mis à jour ✅")

    return _redirect_to_manage_home(request, session=session_id)

@manager_required
def session_participant_invitation(request, session_id, registration_id, lang):
    session = get_object_or_404(Session, pk=session_id)
    reg = get_object_or_404(
        Registration.objects.select_related("participant", "session"),
        pk=registration_id,
        session=session,
    )

    lang = (lang or "fr").lower().strip()
    if lang not in ("fr", "en"):
        lang = "fr"

    try:
        pdf_path = generate_invitation_for_registration(
            registration=reg,
            lang=lang,
            base_url=request.build_absolute_uri("/"),
        )
    except Exception as e:
        messages.error(request, f"Erreur génération convocation : {e}")
        return _redirect_to_manage_home(request, session=session.id)

    if not os.path.exists(pdf_path):
        raise Http404("PDF introuvable.")

    filename = os.path.basename(pdf_path)
    response = FileResponse(open(pdf_path, "rb"), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response