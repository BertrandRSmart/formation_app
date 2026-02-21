from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render, get_object_or_404, redirect

from .models import Project, Task


# =========================================================
# ✅ Kanban TÂCHES (simple)
# URL: /projects/
# =========================================================
@login_required
def projects_home(request):
    projects = Project.objects.all().order_by("name")

    # filtres
    q = (request.GET.get("q") or "").strip()
    project_id = (request.GET.get("project") or request.GET.get("project_id") or "").strip()

    tasks_qs = Task.objects.all()

    if project_id:
        tasks_qs = tasks_qs.filter(project_id=project_id)

    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)

    columns = {
        "todo": tasks_qs.filter(status="TODO").order_by("-id"),
        "doing": tasks_qs.filter(status="IN_PROGRESS").order_by("-id"),
        "blocked": tasks_qs.filter(status="BLOCKED").order_by("-id"),
        "done": tasks_qs.filter(status="DONE").order_by("-id"),
    }

    return render(request, "projects/projects_home.html", {
        "projects": projects,
        "project_id": project_id,
        "q": q,
        "columns": columns,
    })


# =========================================================
# ✅ Kanban PROJETS (projets à gauche + tâches à droite)
# URL: /projects/gestion-projets/
# =========================================================
@login_required
def projects_kanban(request):
    projects = list(Project.objects.all().order_by("name"))

    # filtres
    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()

    tasks_qs = Task.objects.all()

    if project_id:
        tasks_qs = tasks_qs.filter(project_id=project_id)

    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)

    # si ton modèle Task n'a pas priority, on ignore sans casser
    if priority:
        try:
            tasks_qs = tasks_qs.filter(priority=priority)
        except Exception:
            pass

    columns = {
        "todo": tasks_qs.filter(status="TODO").order_by("-id"),
        "doing": tasks_qs.filter(status="IN_PROGRESS").order_by("-id"),
        "blocked": tasks_qs.filter(status="BLOCKED").order_by("-id"),
        "done": tasks_qs.filter(status="DONE").order_by("-id"),
    }

    # ✅ Compteurs par projet (sur toutes les tâches)
    raw = Task.objects.values("project_id", "status").annotate(c=Count("id"))
    counts = {}
    for row in raw:
        pid = row["project_id"]
        st = row["status"]
        counts.setdefault(pid, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        if st in counts[pid]:
            counts[pid][st] = row["c"]

    for p in projects:
        d = counts.get(p.id, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        p.todo_count = d["TODO"]
        p.doing_count = d["IN_PROGRESS"]
        p.blocked_count = d["BLOCKED"]
        p.done_count = d["DONE"]

    return render(request, "projects/projects_kanban.html", {
        "projects": projects,
        "project_id": project_id,
        "q": q,
        "priority": priority,
        "columns": columns,
    })


# =========================================================
# ✅ CRUD tâches (stubs / à brancher sur tes forms si besoin)
# =========================================================
@login_required
def task_create(request):
    # Si tu as déjà une version qui marche, garde-la.
    # Ici on laisse une redirection simple pour éviter les crashes.
    return redirect("projects:projects_home")


@login_required
def task_edit(request, task_id):
    return redirect("projects:projects_home")


@login_required
def task_move(request, task_id):
    return redirect("projects:projects_home")


@login_required
def task_delete(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    task.delete()
    return redirect("projects:projects_home")


from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from .models import Project, Task


# =========================================================
# ✅ Kanban (Gestion des tâches)
# =========================================================
@login_required
def projects_home(request):
    # ✅ Page que tu montres (tâches + colonne projets à gauche)
    projects = list(Project.objects.all().order_by("name"))

    q = (request.GET.get("q") or "").strip()
    priority = (request.GET.get("priority") or "").strip()
    project_id = (request.GET.get("project") or "").strip()

    tasks_qs = Task.objects.all()

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

    columns = {
        "todo": tasks_qs.filter(status="TODO").order_by("-id"),
        "doing": tasks_qs.filter(status="IN_PROGRESS").order_by("-id"),
        "blocked": tasks_qs.filter(status="BLOCKED").order_by("-id"),
        "done": tasks_qs.filter(status="DONE").order_by("-id"),
    }

    # compteurs par projet (pour la colonne projets à gauche)
    raw = Task.objects.values("project_id", "status").annotate(c=Count("id"))
    counts = {}
    for r in raw:
        pid = r["project_id"]
        st = r["status"]
        counts.setdefault(pid, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        if st in counts[pid]:
            counts[pid][st] = r["c"]

    for p in projects:
        d = counts.get(p.id, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        p.todo_count = d["TODO"]
        p.doing_count = d["IN_PROGRESS"]
        p.blocked_count = d["BLOCKED"]
        p.done_count = d["DONE"]

    return render(request, "projects/projects_home.html", {
        "projects": projects,
        "project_id": project_id,
        "q": q,
        "priority": priority,
        "columns": columns,
    })



# =========================================================
# ✅ Kanban (Gestion projets) : colonne projets + compteurs
# =========================================================
@login_required
def projects_kanban(request):
    # ✅ Page DIFFERENTE : gestion des projets (cartes projets)
    projects = list(Project.objects.all().order_by("name"))

    # même compteurs
    raw = Task.objects.values("project_id", "status").annotate(c=Count("id"))
    counts = {}
    for r in raw:
        pid = r["project_id"]
        st = r["status"]
        counts.setdefault(pid, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        if st in counts[pid]:
            counts[pid][st] = r["c"]

    for p in projects:
        d = counts.get(p.id, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        p.todo_count = d["TODO"]
        p.doing_count = d["IN_PROGRESS"]
        p.blocked_count = d["BLOCKED"]
        p.done_count = d["DONE"]
        p.total_count = p.todo_count + p.doing_count + p.blocked_count + p.done_count

    return render(request, "projects/projects_kanban.html", {
        "projects": projects
    })

    # ✅ compteurs par projet (sur toutes les tâches)
    raw = Task.objects.values("project_id", "status").annotate(c=Count("id"))
    counts = {}
    for row in raw:
        pid = row["project_id"]
        st = row["status"]
        counts.setdefault(pid, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        if st in counts[pid]:
            counts[pid][st] = row["c"]

    for p in projects:
        d = counts.get(p.id, {"TODO": 0, "IN_PROGRESS": 0, "BLOCKED": 0, "DONE": 0})
        p.todo_count = d["TODO"]
        p.doing_count = d["IN_PROGRESS"]
        p.blocked_count = d["BLOCKED"]
        p.done_count = d["DONE"]

    return render(request, "projects/projects_kanban.html", {
        "projects": projects,
        "project_id": project_id,
        "q": q,
        "priority": priority,
        "columns": columns,
    })