from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from trainings.models import Session, Trainer, Training

from .models import (
    ContributionKind,
    EvaluationCriterion,
    EvaluationRubric,
    EvaluationScore,
    InternalEvaluation,
    StrategicContribution,
    TrainerAlert,
    ProjectRubric,
    ProjectContributionEvaluation,
)
from .forms import InternalEvaluationForm, EvaluationScoreFormSet, EvaluationCriterionForm

from projects.models import ProjectCategory, Project, ProjectStep
from django.db.models import Sum

from projects.models import ProjectCategory, Project, ProjectStep
from .models import ProjectRubric, ProjectContributionEvaluation, ProjectScore
from .forms import ProjectContributionEvaluationForm, ProjectScoreFormSet

from django.http import JsonResponse, HttpResponse


# ✅ Helpers
def _render(request, template_name, ctx=None):
    return render(request, template_name, ctx or {})


# -------------------------
# Dashboard
# -------------------------


@staff_member_required
def dashboard(request):
    return redirect("trainer_eval:internal_eval_list")

@staff_member_required
def trainer_eval_dashboard(request):
    return redirect("trainer_eval:internal_eval_list")


# -------------------------
# Satisfaction (placeholder)
# -------------------------
@staff_member_required
def session_satisfaction_edit(request, pk):
    return _render(request, "trainer_eval/session_satisfaction_edit.html", {"pk": pk})


# -------------------------
# API: rubrics by training
# -------------------------
@staff_member_required
def rubrics_by_training(request):
    training_id = request.GET.get("training_id")
    if not training_id:
        return JsonResponse({"rubrics": []})

    rubrics = (
        EvaluationRubric.objects
        .filter(training_id=training_id)
        .order_by("-is_active", "-created_at")
    )
    data = [
        {
            "id": r.id,
            "label": f"{r.version_label}" + (" — ACTIVE" if r.is_active else ""),
            "is_active": r.is_active,
        }
        for r in rubrics
    ]
    return JsonResponse({"rubrics": data})


@staff_member_required
def criteria_by_rubric(request):
    rubric_id = request.GET.get("rubric_id")
    if not rubric_id or not rubric_id.isdigit():
        return JsonResponse({"criteria": []})

    criteria = (
        EvaluationCriterion.objects
        .filter(rubric_id=int(rubric_id), is_active=True)
        .order_by("section", "sort_order", "id")
    )

    return JsonResponse({
        "criteria": [
            {
                "id": c.id,
                "section": c.get_section_display(),
                "label": c.label,
                "description": c.description or "",
                "weight": c.weight,
                "max_score": c.max_score,
                "sort_order": c.sort_order,
            }
            for c in criteria
        ]
    })

@staff_member_required
@transaction.atomic
def internal_eval_add_criterion(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Méthode non autorisée."}, status=405)

    rubric_id = request.POST.get("rubric_id")
    if not rubric_id or not rubric_id.isdigit():
        return JsonResponse({"ok": False, "error": "Rubric invalide."}, status=400)

    rubric = get_object_or_404(EvaluationRubric, pk=int(rubric_id))

    form = EvaluationCriterionForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    criterion = form.save(commit=False)
    criterion.rubric = rubric
    criterion.save()

    return JsonResponse({
        "ok": True,
        "criterion": {
            "id": criterion.id,
            "section": criterion.get_section_display(),
            "label": criterion.label,
            "description": criterion.description or "",
            "weight": criterion.weight,
            "max_score": criterion.max_score,
            "sort_order": criterion.sort_order,
        }
    })

# -------------------------
# Internal Evaluations
# -------------------------

@staff_member_required
@transaction.atomic
def internal_eval_create(request):
    create_criteria = []
    criterion_form = EvaluationCriterionForm()

    if request.method == "POST":
        form = InternalEvaluationForm(request.POST)

        rubric_id = request.POST.get("rubric")
        if rubric_id and str(rubric_id).isdigit():
            create_criteria = list(
                EvaluationCriterion.objects
                .filter(rubric_id=int(rubric_id), is_active=True)
                .order_by("section", "sort_order", "id")
            )

        if form.is_valid():
            evaluation = form.save(commit=False)
            evaluation.created_by = request.user
            evaluation.save()

            scores_to_create = []
            for criterion in create_criteria:
                raw_score = request.POST.get(f"criterion_score_{criterion.id}", "0")
                raw_comment = request.POST.get(f"criterion_comment_{criterion.id}", "")

                try:
                    score_value = int(raw_score or 0)
                except (TypeError, ValueError):
                    score_value = 0

                score_value = max(0, min(score_value, int(criterion.max_score or 5)))

                scores_to_create.append(
                    EvaluationScore(
                        evaluation=evaluation,
                        criterion=criterion,
                        score=score_value,
                        comment=raw_comment or "",
                    )
                )

            if scores_to_create:
                EvaluationScore.objects.bulk_create(scores_to_create)

            if hasattr(evaluation, "recompute_rubric_scores"):
                evaluation.recompute_rubric_scores()
                evaluation.save(update_fields=[
                    "rubric_score_total",
                    "rubric_score_max",
                    "rubric_score_100",
                    "decision",
                ])

            messages.success(request, "✅ Évaluation créée avec les notes par critère.")
            return redirect("trainer_eval:internal_eval_edit", pk=evaluation.pk)

    else:
        initial = {}
        training_id = request.GET.get("training")
        rubric_id = request.GET.get("rubric")

        if training_id and training_id.isdigit():
            initial["training"] = int(training_id)
        if rubric_id and rubric_id.isdigit():
            initial["rubric"] = int(rubric_id)

        form = InternalEvaluationForm(initial=initial)

        selected_rubric_id = initial.get("rubric")
        if selected_rubric_id:
            create_criteria = list(
                EvaluationCriterion.objects
                .filter(rubric_id=selected_rubric_id, is_active=True)
                .order_by("section", "sort_order", "id")
            )

    formset = EvaluationScoreFormSet()

    return render(
        request,
        "trainer_eval/internal_eval_form.html",
        {
            "form": form,
            "formset": formset,
            "mode": "create",
            "create_criteria": create_criteria,
            "criterion_form": criterion_form,
        },
    )

def _product_filter_q(product: str) -> Q:
    """
    Filtre produit basé sur TrainingType.name OU Training.title
    (fallback si les TrainingTypes ne contiennent pas le mot).
    """
    p = (product or "ARGONOS").upper()
    return Q(training__training_type__name__icontains=p) | Q(training__title__icontains=p)


@staff_member_required
def internal_eval_list(request):
    # =========================================================
    # 1) PARAMS (filtres à gauche, SANS trainer)
    # =========================================================
    product = (request.GET.get("product") or "ARGONOS").upper()   # ARGONOS / MERCURE
    q = (request.GET.get("q") or "").strip()
    training_id = request.GET.get("training") or ""
    decision = request.GET.get("decision") or ""
    selected_trainer_id = request.GET.get("trainer") or ""

    # =========================================================
    # 2) BASE queryset : évaluations du produit (tableau à droite)
    # =========================================================
    rows = (
        InternalEvaluation.objects
        .select_related("trainer", "training", "rubric")
        .filter(_product_filter_q(product))
    )

    # filtres globaux
    if training_id.isdigit():
        rows = rows.filter(training_id=int(training_id))

    if decision:
        rows = rows.filter(decision=decision)

    if q:
        rows = rows.filter(
            Q(trainer__first_name__icontains=q) |
            Q(trainer__last_name__icontains=q) |
            Q(training__title__icontains=q) |
            Q(manager_comment__icontains=q) |
            Q(trainer_comment__icontains=q) |
            Q(strengths__icontains=q) |
            Q(improvements__icontains=q)
        )

    # =========================================================
    # 3) Dropdown trainings (selon produit)
    # =========================================================
    trainings = (
        Training.objects
        .filter(Q(training_type__name__icontains=product) | Q(title__icontains=product))
        .order_by("title")
    )

    # =========================================================
    # 4) Liste formateurs : TOUS les formateurs du produit
    #    (même sans éval) via:
    #    - sessions où ils sont trainer OU backup_trainer
    #    - OU évaluations existantes (fallback)
    #
    # ⚠️ IMPORTANT : adapte ces related_name si nécessaire :
    #   - "primary_sessions" = related_name sur Session.trainer
    #   - "backup_sessions"  = related_name sur Session.backup_trainer
    #   (sur ta capture, tu as bien primary_sessions / backup_sessions)
    # =========================================================
    product_q_evals = (
        Q(internal_evaluations__training__training_type__name__icontains=product) |
        Q(internal_evaluations__training__title__icontains=product)
    )

    product_q_sessions = (
        Q(primary_sessions__training__training_type__name__icontains=product) |
        Q(primary_sessions__training__title__icontains=product) |
        Q(backup_sessions__training__training_type__name__icontains=product) |
        Q(backup_sessions__training__title__icontains=product)
    )

    trainers = (
        Trainer.objects
        .filter(product_q_sessions | product_q_evals)
        .distinct()
    )

    # --- compteur d'évals (respecte tes filtres globaux) ---
    count_filter = (
        Q(internal_evaluations__training__training_type__name__icontains=product) |
        Q(internal_evaluations__training__title__icontains=product)
    )

    if training_id.isdigit():
        count_filter &= Q(internal_evaluations__training_id=int(training_id))

    if decision:
        count_filter &= Q(internal_evaluations__decision=decision)

    # optionnel : la recherche filtre aussi la liste des formateurs
    if q:
        trainers = trainers.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))

    trainers = (
        trainers
        .annotate(eval_count=Count("internal_evaluations", filter=count_filter, distinct=True))
        .order_by("last_name", "first_name")
    )

    # =========================================================
    # 5) Sélection formateur (clic sur la carte à gauche)
    # =========================================================
    selected_trainer = None
    if selected_trainer_id.isdigit():
        selected_trainer = Trainer.objects.filter(pk=int(selected_trainer_id)).first()
        if selected_trainer:
            rows = rows.filter(trainer=selected_trainer)

    rows = rows.order_by("-evaluated_on", "-id")

    # =========================================================
    # 6) URLs switch produit / reset trainer
    # =========================================================
    params = request.GET.copy()

    params_no_trainer = params.copy()
    params_no_trainer.pop("trainer", None)

    params_arg = params.copy()
    params_arg["product"] = "ARGONOS"
    params_arg.pop("trainer", None)

    params_mer = params.copy()
    params_mer["product"] = "MERCURE"
    params_mer.pop("trainer", None)

    context = {
        "product": product,
        "q": q,
        "training_id": training_id,
        "decision": decision,
        "decisions": InternalEvaluation._meta.get_field("decision").choices,

        "trainings": trainings,
        "trainers": trainers,
        "selected_trainer": selected_trainer,
        "rows": rows,

        "url_no_trainer": "?" + urlencode(params_no_trainer, doseq=True),
        "url_argonos": "?" + urlencode(params_arg, doseq=True),
        "url_mercure": "?" + urlencode(params_mer, doseq=True),
    }
    return render(request, "trainer_eval/internal_eval_list.html", context)






@staff_member_required
@transaction.atomic
def internal_eval_edit(request, pk):
    eval_obj = get_object_or_404(InternalEvaluation, pk=pk)

    # Si l'éval n'a pas encore de lignes scores, on les crée depuis la grille
    if eval_obj.rubric and not eval_obj.criterion_scores.exists():
        criteria = eval_obj.rubric.criteria.filter(is_active=True).order_by("section", "sort_order", "id")
        EvaluationScore.objects.bulk_create(
            [EvaluationScore(evaluation=eval_obj, criterion=c, score=0) for c in criteria]
        )

    if request.method == "POST":
        form = InternalEvaluationForm(request.POST, instance=eval_obj)
        formset = EvaluationScoreFormSet(request.POST, instance=eval_obj)

        if form.is_valid() and formset.is_valid():
            obj = form.save(commit=False)
            obj.created_by = obj.created_by or request.user
            obj.save()
            formset.save()

            # (optionnel) recalcul score %
            if hasattr(obj, "recompute_rubric_scores"):
                obj.recompute_rubric_scores()
                obj.save(update_fields=["rubric_score_total", "rubric_score_max", "rubric_score_100", "decision"])

            messages.success(request, "✅ Évaluation mise à jour.")
            return redirect("trainer_eval:internal_eval_list")
    else:
        form = InternalEvaluationForm(instance=eval_obj)
        formset = EvaluationScoreFormSet(instance=eval_obj)

    return render(
        request,
        "trainer_eval/internal_eval_form.html",
        {
            "form": form,
            "formset": formset,
            "mode": "edit",
            "eval_obj": eval_obj,
            "criterion_form": EvaluationCriterionForm(),
        },
    )


# -------------------------
# Contributions (placeholder)
# -------------------------
@staff_member_required

@staff_member_required
def contributions_list(request):
    # --- Params (filtres) ---
    q = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    project_id = request.GET.get("project") or ""
    step_id = request.GET.get("step") or ""
    decision = request.GET.get("decision") or ""
    selected_trainer_id = request.GET.get("trainer") or ""

    # --- Base queryset (tableau droite) ---
    rows = (
        ProjectContributionEvaluation.objects
        .select_related("trainer", "project", "step", "rubric", "project__category")
        .all()
    )

    if category_id.isdigit():
        rows = rows.filter(project__category_id=int(category_id))
    if project_id.isdigit():
        rows = rows.filter(project_id=int(project_id))
    if step_id.isdigit():
        rows = rows.filter(step_id=int(step_id))
    if decision:
        rows = rows.filter(decision=decision)

    if q:
        rows = rows.filter(
            Q(trainer__first_name__icontains=q) |
            Q(trainer__last_name__icontains=q) |
            Q(project__name__icontains=q) |
            Q(step__title__icontains=q) |
            Q(manager_comment__icontains=q) |
            Q(trainer_comment__icontains=q) |
            Q(strengths__icontains=q) |
            Q(improvements__icontains=q)
        )

    # --- Dropdowns ---
    categories = ProjectCategory.objects.order_by("name")
    projects = Project.objects.filter(is_active=True).select_related("category").order_by("name")

    steps = ProjectStep.objects.none()
    if project_id.isdigit():
        steps = ProjectStep.objects.filter(project_id=int(project_id)).order_by("order", "id")

    # --- Trainers list (left) + counts ---
    trainer_base = Trainer.objects.filter(project_contribution_evaluations__isnull=False).distinct()

    if q:
        trainer_base = trainer_base.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))

    count_filter = Q(project_contribution_evaluations__isnull=False)
    if category_id.isdigit():
        count_filter &= Q(project_contribution_evaluations__project__category_id=int(category_id))
    if project_id.isdigit():
        count_filter &= Q(project_contribution_evaluations__project_id=int(project_id))
    if step_id.isdigit():
        count_filter &= Q(project_contribution_evaluations__step_id=int(step_id))
    if decision:
        count_filter &= Q(project_contribution_evaluations__decision=decision)

    trainers = (
        trainer_base
        .annotate(contrib_count=Count("project_contribution_evaluations", filter=count_filter, distinct=True))
        .order_by("last_name", "first_name")
    )

    selected_trainer = None
    if selected_trainer_id.isdigit():
        selected_trainer = Trainer.objects.filter(pk=int(selected_trainer_id)).first()
        if selected_trainer:
            rows = rows.filter(trainer=selected_trainer)

    rows = rows.order_by("-evaluated_on", "-id")

    params = request.GET.copy()
    params_no_trainer = params.copy()
    params_no_trainer.pop("trainer", None)

    context = {
        "q": q,
        "category_id": category_id,
        "project_id": project_id,
        "step_id": step_id,
        "decision": decision,
        "decisions": ProjectContributionEvaluation._meta.get_field("decision").choices,

        "categories": categories,
        "projects": projects,
        "steps": steps,

        "trainers": trainers,
        "selected_trainer": selected_trainer,
        "rows": rows,

        "url_no_trainer": "?" + urlencode(params_no_trainer, doseq=True),
    }
    response = render(request, "trainer_eval/contributions_list.html", context)

    # ✅ affiche le template réellement utilisé (dans la page)
    try:
        used = " | ".join([t.name for t in response.templates if getattr(t, "name", None)])
    except Exception:
        used = "unknown"

    # injecter dans le contexte après render -> on refait une render propre
    context["template_used"] = used
    return render(request, "trainer_eval/contributions_list.html", context)


@staff_member_required
@transaction.atomic
def contributions_create(request):
    if request.method == "POST":
        form = ProjectContributionEvaluationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()

            # ✅ Génère les scores depuis la grille (si une rubric est choisie)
            if obj.rubric and not obj.criterion_scores.exists():
                criteria = (
                    obj.rubric.criteria
                    .filter(is_active=True)
                    .order_by("section", "sort_order", "id")
                )
                ProjectScore.objects.bulk_create(
                    [ProjectScore(evaluation=obj, criterion=c, score=0) for c in criteria]
                )

            messages.success(request, "✅ Contribution créée. Tu peux maintenant noter les critères.")
            return redirect("trainer_eval:contributions_edit", pk=obj.pk)
    else:
        form = ProjectContributionEvaluationForm()

    formset = ProjectScoreFormSet()
    return render(
        request,
        "trainer_eval/contributions_form.html",
        {"form": form, "formset": formset, "mode": "create"},
    )


@staff_member_required
@transaction.atomic
def contributions_edit(request, pk):
    obj = get_object_or_404(ProjectContributionEvaluation, pk=pk)

    # ✅ Si pas encore de lignes scores, on les crée depuis la grille
    if obj.rubric and not obj.criterion_scores.exists():
        criteria = obj.rubric.criteria.filter(is_active=True).order_by("section", "sort_order", "id")
        ProjectScore.objects.bulk_create(
            [ProjectScore(evaluation=obj, criterion=c, score=0) for c in criteria]
        )

    if request.method == "POST":
        form = ProjectContributionEvaluationForm(request.POST, instance=obj)
        formset = ProjectScoreFormSet(request.POST, instance=obj)

        if form.is_valid() and formset.is_valid():
            o = form.save(commit=False)
            o.created_by = o.created_by or request.user
            o.save()
            formset.save()

            # ✅ recalcul score % + décision
            if hasattr(o, "recompute_rubric_scores"):
                o.recompute_rubric_scores()
                o.save(update_fields=["rubric_score_total", "rubric_score_max", "rubric_score_100", "decision"])

            messages.success(request, "✅ Contribution mise à jour.")
            return redirect("trainer_eval:contributions_list")
    else:
        form = ProjectContributionEvaluationForm(instance=obj)
        formset = ProjectScoreFormSet(instance=obj)

    return render(
        request,
        "trainer_eval/contributions_form.html",
        {"form": form, "formset": formset, "mode": "edit", "obj": obj},
    )
# -------------------------
# Alerts (placeholder)
# -------------------------
@staff_member_required
def alerts_list(request):
    return _render(request, "trainer_eval/alerts_list.html")

@staff_member_required
def alerts_create(request):
    return _render(request, "trainer_eval/alerts_form.html", {"mode": "create"})

@staff_member_required
def alerts_edit(request, pk):
    return _render(request, "trainer_eval/alerts_form.html", {"mode": "edit", "pk": pk})


@staff_member_required
def project_steps_by_project(request):
    project_id = request.GET.get("project_id")
    if not project_id or not project_id.isdigit():
        return JsonResponse({"steps": []})

    steps = ProjectStep.objects.filter(project_id=int(project_id)).order_by("order", "id")
    return JsonResponse({
        "steps": [{"id": s.id, "label": s.title, "status": s.status} for s in steps]
    })

@staff_member_required
def project_rubrics_by_category(request):
    category_id = request.GET.get("category_id") or ""
    qs = ProjectRubric.objects.all()

    if category_id.isdigit():
        qs = qs.filter(Q(category_id=int(category_id)) | Q(category__isnull=True))

    qs = qs.order_by("-is_active", "-created_at")

    return JsonResponse({
        "rubrics": [
            {
                "id": r.id,
                "label": f"{r.version_label}" + (" — ACTIVE" if r.is_active else ""),
                "is_active": r.is_active,
            }
            for r in qs
        ]
    })