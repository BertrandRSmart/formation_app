from datetime import date

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from trainings.models import Session, Trainer
from .forms import (
    InternalEvaluationForm,
    SessionSatisfactionForm,
    StrategicContributionForm,
    TrainerAlertForm,
)
from .models import InternalEvaluation, StrategicContribution, TrainerAlert


# =========================================================
# Satisfaction sessions (Session.client_satisfaction /20)
# =========================================================

@staff_member_required
def session_satisfaction_list(request):
    sessions = (
        Session.objects
        .select_related("training", "trainer")
        .order_by("-start_date")[:250]
    )
    return render(request, "trainer_eval/session_satisfaction_list.html", {"sessions": sessions})


@staff_member_required
def session_satisfaction_edit(request, pk: int):
    session = get_object_or_404(
        Session.objects.select_related("training", "trainer"),
        pk=pk
    )

    if request.method == "POST":
        form = SessionSatisfactionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            return redirect("trainer_eval:session_satisfaction_list")
    else:
        form = SessionSatisfactionForm(instance=session)

    return render(
        request,
        "trainer_eval/session_satisfaction_form.html",
        {"form": form, "session": session},
    )


# =========================================================
# Évaluations internes
# =========================================================

@staff_member_required
def internal_eval_list(request):
    qs = (
        InternalEvaluation.objects
        .select_related("trainer", "training", "evaluator")
        .order_by("-evaluated_on")[:300]
    )
    return render(request, "trainer_eval/internal_eval_list.html", {"items": qs})


@staff_member_required
def internal_eval_create(request):
    if request.method == "POST":
        form = InternalEvaluationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.evaluator = request.user
            obj.save()
            return redirect("trainer_eval:internal_eval_list")
    else:
        form = InternalEvaluationForm(initial={"evaluated_on": timezone.localdate()})

    return render(request, "trainer_eval/internal_eval_form.html", {"form": form, "obj": None})


@staff_member_required
def internal_eval_edit(request, pk: int):
    obj = get_object_or_404(InternalEvaluation, pk=pk)

    if request.method == "POST":
        form = InternalEvaluationForm(request.POST, instance=obj)
        if form.is_valid():
            obj2 = form.save(commit=False)
            obj2.evaluator = request.user
            obj2.save()
            return redirect("trainer_eval:internal_eval_list")
    else:
        form = InternalEvaluationForm(instance=obj)

    return render(request, "trainer_eval/internal_eval_form.html", {"form": form, "obj": obj})


# =========================================================
# Contributions stratégiques
# =========================================================

@staff_member_required
def contributions_list(request):
    items = (
        StrategicContribution.objects
        .select_related("trainer", "training", "created_by")
        .order_by("-date")[:400]
    )
    return render(request, "trainer_eval/contributions_list.html", {"items": items})


@staff_member_required
def contributions_create(request):
    if request.method == "POST":
        form = StrategicContributionForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            return redirect("trainer_eval:contributions_list")
    else:
        form = StrategicContributionForm(initial={"date": timezone.localdate()})

    return render(request, "trainer_eval/contributions_form.html", {"form": form, "obj": None})


@staff_member_required
def contributions_edit(request, pk: int):
    obj = get_object_or_404(StrategicContribution, pk=pk)

    if request.method == "POST":
        form = StrategicContributionForm(request.POST, instance=obj)
        if form.is_valid():
            obj2 = form.save(commit=False)
            obj2.created_by = request.user
            obj2.save()
            return redirect("trainer_eval:contributions_list")
    else:
        form = StrategicContributionForm(instance=obj)

    return render(request, "trainer_eval/contributions_form.html", {"form": form, "obj": obj})


# =========================================================
# Alertes formateurs
# =========================================================

@staff_member_required
def alerts_list(request):
    items = (
        TrainerAlert.objects
        .select_related("trainer", "training", "created_by")
        .order_by("-triggered_on")[:400]
    )
    return render(request, "trainer_eval/alerts_list.html", {"items": items})


@staff_member_required
def alerts_create(request):
    if request.method == "POST":
        form = TrainerAlertForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            return redirect("trainer_eval:alerts_list")
    else:
        form = TrainerAlertForm(initial={"triggered_on": timezone.localdate()})

    return render(request, "trainer_eval/alerts_form.html", {"form": form, "obj": None})


@staff_member_required
def alerts_edit(request, pk: int):
    obj = get_object_or_404(TrainerAlert, pk=pk)

    if request.method == "POST":
        form = TrainerAlertForm(request.POST, instance=obj)
        if form.is_valid():
            obj2 = form.save(commit=False)
            obj2.created_by = request.user
            obj2.save()
            return redirect("trainer_eval:alerts_list")
    else:
        form = TrainerAlertForm(instance=obj)

    return render(request, "trainer_eval/alerts_form.html", {"form": form, "obj": obj})


# =========================================================
# Dashboard comparatif (2 blocs : ArgonOS/autres vs Mercure)
# =========================================================

@staff_member_required
def trainer_eval_dashboard(request):
    year_start = date(date.today().year, 1, 1)

    # Sessions depuis le 1er janvier
    sessions_stats = (
        Session.objects
        .filter(start_date__gte=year_start)
        .values("trainer_id")
        .annotate(
            sessions_count=Count("id"),
            sat_avg=Avg("client_satisfaction"),
        )
    )
    sessions_map = {row["trainer_id"]: row for row in sessions_stats}

    # Évaluations internes depuis le 1er janvier
    evals_stats = (
        InternalEvaluation.objects
        .filter(evaluated_on__gte=year_start)
        .values("trainer_id")
        .annotate(eval_avg=Avg("total_score_30"))
    )
    evals_map = {row["trainer_id"]: row for row in evals_stats}

    # Contributions depuis le 1er janvier
    contrib_stats = (
        StrategicContribution.objects
        .filter(date__gte=year_start)
        .values("trainer_id")
        .annotate(points_sum=Sum("points"))
    )
    contrib_map = {row["trainer_id"]: row for row in contrib_stats}

    # Alertes actives
    alerts_stats = (
        TrainerAlert.objects
        .filter(status="ACTIVE")
        .values("trainer_id")
        .annotate(alerts_active=Count("id"))
    )
    alerts_map = {row["trainer_id"]: row for row in alerts_stats}

    trainers = Trainer.objects.all().order_by("last_name", "first_name")

    rows = []
    for t in trainers:
        s = sessions_map.get(t.id, {})
        e = evals_map.get(t.id, {})
        c = contrib_map.get(t.id, {})
        a = alerts_map.get(t.id, {})

        sat_avg = float(s.get("sat_avg") or 0)
        eval_avg = float(e.get("eval_avg") or 0)
        points = int(c.get("points_sum") or 0)
        sessions_count = int(s.get("sessions_count") or 0)
        alerts_active = int(a.get("alerts_active") or 0)

        # Score global v1 (0-100)
        sat100 = (sat_avg / 20) * 100 if sat_avg else 0
        eval100 = (eval_avg / 30) * 100 if eval_avg else 0
        contrib100 = min(points, 100)

        score = (0.45 * sat100) + (0.35 * eval100) + (0.20 * contrib100)
        score = score - (alerts_active * 5)
        score = max(0, round(score, 1))

        # Niveau indicatif
        if score >= 85:
            level = "Expert"
        elif score >= 70:
            level = "Intermédiaire"
        else:
            level = "Débutant"

        rows.append({
            "trainer": t,
            "sessions_count": sessions_count,
            "sat_avg": round(sat_avg, 2) if sat_avg else None,
            "eval_avg": round(eval_avg, 2) if eval_avg else None,
            "points": points,
            "alerts_active": alerts_active,
            "score": score,
            "level": level,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)

    # ✅ Split produit : Mercure en bas, autres en haut
    mercure_rows = [
        r for r in rows
        if str(getattr(r["trainer"], "product", "")).strip().upper() == "MERCURE"
    ]
    other_rows = [
        r for r in rows
        if str(getattr(r["trainer"], "product", "")).strip().upper() != "MERCURE"
    ]

    return render(request, "trainer_eval/dashboard.html", {
        "year_start": year_start,
        "other_rows": other_rows,
        "mercure_rows": mercure_rows,
    })