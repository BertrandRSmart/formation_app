from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q

from .models import Project, Task
from .forms import TaskForm
from django.urls import reverse
from django.views.decorators.http import require_POST


# =========================================================
# ✅ Kanban (Gestion des tâches)
# =========================================================
KANBAN_STATUSES = [
    ("todo", "TODO"),
    ("doing", "En cours"),
    ("blocked", "Bloqué"),
    ("done", "Terminé"),
]


def _task_accessor_name() -> str:
    """
    Retourne le nom d'accès inverse Project -> Task.
    Exemples : "tasks" (si related_name="tasks") ou "task_set" (par défaut).
    """
    for f in Project._meta.get_fields():
        if f.is_relation and f.one_to_many and getattr(f, "related_model", None) == Task:
            return f.get_accessor_name()
    return "task_set"


@login_required
def projects_home(request):
    # filtres
    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()

    projects_qs = Project.objects.all()
    tasks_qs = Task.objects.select_related("project").all()

    if project_id:
        tasks_qs = tasks_qs.filter(project_id=project_id)

    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)

    # priorité si ton modèle l’a
    if priority:
        try:
            tasks_qs = tasks_qs.filter(priority=priority)
        except Exception:
            pass

    # Colonnes kanban (listes)
    columns = {key: [] for key, _ in KANBAN_STATUSES}
    for t in tasks_qs.order_by("project__name", "id"):
        if t.status in columns:
            columns[t.status].append(t)
        else:
            columns["TODO"].append(t)

    # ✅ Structure template-friendly : (key, label, col)
    kanban_cols = [(key, label, columns.get(key, [])) for key, label in KANBAN_STATUSES]

    # ✅ Compteurs par projet (robuste)
    rel = _task_accessor_name()  # "tasks" ou "task_set" ou autre

    projects = projects_qs.annotate(
        todo_count=Count("tasks", filter=Q(tasks__status="todo")),
        doing_count=Count("tasks", filter=Q(tasks__status="doing")),
        blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
        done_count=Count("tasks", filter=Q(tasks__status="done")),
        total_count=Count("tasks"),
    ).order_by("name")

    selected_project = projects_qs.filter(id=project_id).first() if project_id else None

    return render(
        request,
        "projects/projects_home.html",
        {
            "projects": projects,
            "selected_project": selected_project,
            "project_id": project_id,
            "q": q,
            "priority": priority,
            "columns": columns,
            "kanban_statuses": KANBAN_STATUSES,
            "kanban_cols": kanban_cols,
        },
    )


# =========================================================
# ✅ Page "Gestion des projets"
# =========================================================
@login_required
def projects_kanban(request):
    projects_qs = Project.objects.all().order_by("name")

    raw = Task.objects.values("project_id", "status").annotate(c=Count("id"))
    counts = {}
    for r in raw:
        pid = r["project_id"]
        st = r["status"]
        counts.setdefault(pid, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        if st in counts[pid]:
            counts[pid][st] = r["c"]

    projects = list(projects_qs)
    for p in projects:
        d = counts.get(p.id, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        p.todo_count = d["TODO"]
        p.doing_count = d["IN_PROGRESS"]
        p.blocked_count = d["BLOCKED"]
        p.done_count = d["DONE"]
        p.total_count = p.todo_count + p.doing_count + p.blocked_count + p.done_count

    return render(request, "projects/projects_kanban.html", {"projects": projects})


# =========================================================
# ✅ Actions tâches (stubs)
# =========================================================
@login_required
def task_create(request):
    if request.method == "POST":
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save()
            # optionnel: revenir filtré sur le projet de la tâche créée
            return redirect(f"{reverse('projects:projects_home')}?project={task.project_id}")
    else:
        # pré-remplir le projet si on vient du kanban filtré
        initial = {}
        project_id = request.GET.get("project")
        if project_id:
            initial["project"] = project_id
        form = TaskForm(initial=initial)

    return render(request, "projects/task_form.html", {"form": form, "mode": "create"})


@login_required
def task_edit(request, task_id):
    task = get_object_or_404(Task, id=task_id)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save()
            return redirect(f"{reverse('projects:projects_home')}?project={task.project_id}")
    else:
        form = TaskForm(instance=task)

    return render(request, "projects/task_form.html", {"form": form, "mode": "edit", "task": task})



@login_required
@require_POST
def task_move(request, task_id):
    task = get_object_or_404(Task, id=task_id)

    direction = request.POST.get("direction")  # "left" ou "right"

    # ordre des colonnes (doit correspondre à tes statuts en DB)
    order = [key for key, _ in KANBAN_STATUSES]  # ["todo","doing","blocked","done"]

    try:
        idx = order.index(task.status)
    except ValueError:
        idx = 0

    if direction == "left":
        idx = max(0, idx - 1)
    elif direction == "right":
        idx = min(len(order) - 1, idx + 1)

    task.status = order[idx]
    task.save(update_fields=["status", "updated_at"])

    # retour au kanban en conservant les filtres
    url = reverse("projects:projects_home")
    params = []
    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()

    if q:
        params.append(f"q={q}")
    if priority:
        params.append(f"priority={priority}")
    if project_id:
        params.append(f"project={project_id}")

    if params:
        url += "?" + "&".join(params)

    return redirect(url)

@login_required
@require_POST
def task_delete(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    project_id = task.project_id
    task.delete()

    # Retour au kanban en gardant le filtre projet si possible
    url = reverse("projects:projects_home")
    if project_id:
        url += f"?project={project_id}"
    return redirect(url)