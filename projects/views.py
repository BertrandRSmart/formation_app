from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count, Q
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse

from .models import Project, Task, ProjectCategory, TaskAssignment
from .forms import TaskForm, TaskAssignmentForm, ProjectForm


# =========================================================
# Kanban - constantes
# =========================================================

KANBAN_STATUSES = [
    ("todo", "TODO"),
    ("doing", "En cours"),
    ("blocked", "Bloqué"),
    ("done", "Terminé"),
]


# =========================================================
# Vue globale des tâches
# =========================================================

@login_required
def projects_home(request):
    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    cat_id = (request.GET.get("cat") or "").strip()

    categories = ProjectCategory.objects.all().order_by("name")

    projects_qs = (
        Project.objects
        .select_related("category")
        .annotate(
            todo_count=Count("tasks", filter=Q(tasks__status="todo")),
            doing_count=Count("tasks", filter=Q(tasks__status="doing")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks"),
        )
        .order_by("name")
    )

    tasks_qs = Task.objects.select_related("project", "project__category", "assignee").all()

    if cat_id:
        projects_qs = projects_qs.filter(category_id=cat_id)
        tasks_qs = tasks_qs.filter(project__category_id=cat_id)

    if project_id:
        tasks_qs = tasks_qs.filter(project_id=project_id)

    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)

    if priority:
        try:
            tasks_qs = tasks_qs.filter(priority=int(priority))
        except Exception:
            pass

    columns = {key: [] for key, _ in KANBAN_STATUSES}
    for t in tasks_qs.order_by("project__name", "order", "id"):
        columns.get(t.status, columns["todo"]).append(t)

    kanban_cols = [(key, label, columns.get(key, [])) for key, label in KANBAN_STATUSES]

    selected_project = None
    if project_id.isdigit():
        selected_project = Project.objects.filter(id=int(project_id)).first()

    return render(request, "projects/projects_home.html", {
        "projects": projects_qs,
        "selected_project": selected_project,
        "project_id": project_id,
        "q": q,
        "priority": priority,
        "kanban_cols": kanban_cols,
        "categories": categories,
        "cat_id": cat_id,
    })


# =========================================================
# Vue projets
# =========================================================

@login_required
def projects_kanban(request):
    cat_id = (request.GET.get("cat") or "").strip()
    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "active").strip()

    categories = ProjectCategory.objects.all().order_by("name")

    projects_qs = (
        Project.objects
        .select_related("category", "owner")
        .annotate(
            todo_count=Count("tasks", filter=Q(tasks__status="todo")),
            doing_count=Count("tasks", filter=Q(tasks__status="doing")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks"),
        )
        .order_by("category__name", "name")
    )

    if status_filter == "active":
        projects_qs = projects_qs.filter(is_active=True)
    elif status_filter == "archived":
        projects_qs = projects_qs.filter(is_active=False)
    # "all" => pas de filtre supplémentaire

    if cat_id:
        projects_qs = projects_qs.filter(category_id=cat_id)

    if q:
        projects_qs = projects_qs.filter(name__icontains=q)

    projects = list(projects_qs)

    return render(request, "projects/projects_kanban.html", {
        "projects": projects,
        "categories": categories,
        "cat_id": cat_id,
        "q": q,
        "status_filter": status_filter,
    })


# =========================================================
# Détail projet
# =========================================================

@login_required
def project_detail(request, project_id: int):
    project = get_object_or_404(
        Project.objects.select_related("category", "owner"),
        id=project_id,
    )

    tasks_qs = (
        Task.objects
        .select_related("project", "assignee")
        .prefetch_related("assignments__trainer")
        .filter(project=project)
        .order_by("order", "id")
    )

    columns = {key: [] for key, _ in KANBAN_STATUSES}
    for t in tasks_qs:
        columns.get(t.status, columns["todo"]).append(t)

    kanban_cols = [(key, label, columns.get(key, [])) for key, label in KANBAN_STATUSES]

    return render(request, "projects/project_detail.html", {
        "project": project,
        "tasks": tasks_qs,
        "kanban_cols": kanban_cols,
    })


# =========================================================
# Gestion des projets
# =========================================================

@login_required
def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("projects:projects_kanban")
    else:
        form = ProjectForm()

    return render(request, "projects/project_form.html", {
        "form": form,
        "mode": "create",
    })


@login_required
def project_edit(request, project_id: int):
    project = get_object_or_404(Project, id=project_id)

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect("projects:projects_kanban")
    else:
        form = ProjectForm(instance=project)

    return render(request, "projects/project_form.html", {
        "form": form,
        "mode": "edit",
        "project": project,
    })


@login_required
@require_POST
def project_archive(request, project_id: int):
    project = get_object_or_404(Project, id=project_id)
    project.is_active = False
    project.save(update_fields=["is_active"])
    return redirect("projects:projects_kanban")


@login_required
@require_POST
def project_unarchive(request, project_id: int):
    project = get_object_or_404(Project, id=project_id)
    project.is_active = True
    project.save(update_fields=["is_active"])
    return redirect("projects:projects_kanban")


@login_required
@require_POST
def project_delete(request, project_id: int):
    project = get_object_or_404(Project, id=project_id)
    project.delete()
    return redirect("projects:projects_kanban")


# =========================================================
# Actions tâches
# =========================================================

@login_required
def task_create(request):
    if request.method == "POST":
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save()

            next_url = request.POST.get("next_url", "").strip()
            if next_url:
                return redirect(next_url)

            return redirect(f"{reverse('projects:projects_home')}?project={task.project_id}")
    else:
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

            next_url = request.POST.get("next_url", "").strip()
            if next_url:
                return redirect(next_url)

            return redirect(f"{reverse('projects:projects_home')}?project={task.project_id}")
    else:
        form = TaskForm(instance=task)

    return render(request, "projects/task_form.html", {
        "form": form,
        "mode": "edit",
        "task": task,
    })


@login_required
@require_POST
def task_move(request, task_id):
    task = get_object_or_404(Task, id=task_id)

    direction = request.POST.get("direction")
    source = (request.POST.get("source") or "").strip()

    order = [key for key, _ in KANBAN_STATUSES]

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

    if source == "project_detail":
        return redirect("projects:project_detail", project_id=task.project_id)

    url = reverse("projects:projects_home")
    params = []

    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    cat_id = (request.GET.get("cat") or "").strip()

    if q:
        params.append(f"q={q}")
    if priority:
        params.append(f"priority={priority}")
    if project_id:
        params.append(f"project={project_id}")
    if cat_id:
        params.append(f"cat={cat_id}")

    if params:
        url += "?" + "&".join(params)

    return redirect(url)


@login_required
@require_POST
def task_delete(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    project_id = task.project_id
    source = (request.POST.get("source") or "").strip()
    task.delete()

    if source == "project_detail":
        return redirect("projects:project_detail", project_id=project_id)

    url = reverse("projects:projects_home")
    if project_id:
        url += f"?project={project_id}"
    return redirect(url)


# =========================================================
# Affectations de tâches
# =========================================================

@login_required
def task_assignment_create(request, task_id: int):
    task = get_object_or_404(
        Task.objects.select_related("project"),
        id=task_id,
    )

    if request.method == "POST":
        form = TaskAssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.task = task
            assignment.created_by = request.user
            assignment.save()
            return redirect("projects:project_detail", project_id=task.project_id)
    else:
        form = TaskAssignmentForm(initial={"task": task})

    return render(request, "projects/task_assignment_form.html", {
        "form": form,
        "task": task,
        "project": task.project,
        "mode": "create",
    })


@login_required
def task_assignment_edit(request, assignment_id: int):
    assignment = get_object_or_404(
        TaskAssignment.objects.select_related("task", "task__project", "trainer"),
        id=assignment_id,
    )

    if request.method == "POST":
        form = TaskAssignmentForm(request.POST, instance=assignment)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.task = assignment.task
            updated.save()
            return redirect("projects:project_detail", project_id=assignment.task.project_id)
    else:
        form = TaskAssignmentForm(instance=assignment)

    return render(request, "projects/task_assignment_form.html", {
        "form": form,
        "assignment": assignment,
        "task": assignment.task,
        "project": assignment.task.project,
        "mode": "edit",
    })


@login_required
@require_POST
def task_assignment_delete(request, assignment_id: int):
    assignment = get_object_or_404(
        TaskAssignment.objects.select_related("task", "task__project"),
        id=assignment_id,
    )
    project_id = assignment.task.project_id
    assignment.delete()
    return redirect("projects:project_detail", project_id=project_id)


@require_GET
@login_required
def task_quick(request, task_id: int):
    t = get_object_or_404(
        Task.objects.select_related("project", "assignee"),
        id=task_id
    )

    return JsonResponse({
        "id": t.id,
        "title": t.title,
        "project": t.project.name,
        "status": t.get_status_display(),
        "priority": t.priority,
        "assignee": t.assignee.username if t.assignee else None,
        "due_date": t.due_date.strftime("%d/%m/%Y") if t.due_date else None,
        "description": t.description or "",
        "estimated_days": float(t.estimated_days or 0),
    })
