print("✅ LOADED trainings/views_manage.py")

from datetime import date
import csv

from django.contrib import messages
from django.db.models import Q, Count
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Session, Registration, Client, Trainer
from .forms_manage import ParticipantForm, RegistrationMiniForm
from .views import manager_required


@manager_required
def training_manage_home(request):
    month = request.GET.get("month") or ""        # "YYYY-MM"
    client_id = request.GET.get("client") or ""
    trainer_id = request.GET.get("trainer") or ""
    status = request.GET.get("status") or ""      # upcoming / ongoing / done
    selected_id = request.GET.get("session") or ""
    q = (request.GET.get("q") or "").strip()

    qs = Session.objects.all()
    today = date.today()

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
    if session_ids:
        counts_qs = (
            Registration.objects
            .filter(session_id__in=session_ids)
            .values("session_id")
            .annotate(c=Count("id"))
        )
        participants_count_by_session = {row["session_id"]: row["c"] for row in counts_qs}
    else:
        participants_count_by_session = {}

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
        # Formulaire “Inscription” (participant)
        p_form = ParticipantForm()

    # --- Listes filtres ---
    clients = Client.objects.order_by("name")
    trainers = Trainer.objects.order_by("last_name", "first_name")
    months = [f"{today.year}-{mm:02d}" for mm in range(1, 13)]

    return render(request, "trainings/manage_sessions_board.html", {
        "sessions": sessions,
        "sessions_count": sessions_count,
        "participants_count_by_session": participants_count_by_session,

        "selected_session": selected_session,
        "registrations": registrations,
        "selected_id": selected_id,

        "clients": clients,
        "trainers": trainers,
        "month": month,
        "client_id": client_id,
        "trainer_id": trainer_id,
        "status": status,
        "q": q,
        "months": months,
        "today": today,

        "p_form": p_form,
    })


@manager_required
def session_participant_add(request, session_id):
    session = get_object_or_404(Session, pk=session_id)

    if request.method == "POST":
        p_form = ParticipantForm(request.POST)
        if p_form.is_valid():
            participant = p_form.save()
            Registration.objects.create(session=session, participant=participant)
            messages.success(request, "Participant ajouté à la session ✅")
        else:
            messages.error(request, "Formulaire invalide. Vérifie les champs.")
        return redirect(f"/formations/?session={session.id}")

    return redirect(f"/formations/?session={session.id}")


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
            r_form.save()
            messages.success(request, "Participant mis à jour ✅")
            return redirect(f"/formations/?session={session.id}")
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
    messages.success(request, "Participant retiré de la session ✅")
    return redirect(f"/formations/?session={session.id}")


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
