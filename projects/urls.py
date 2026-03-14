from django.urls import path
from . import views

app_name = "projects"

urlpatterns = [
    # ✅ Kanban TÂCHES
    path("", views.projects_home, name="projects_home"),

    # ✅ Kanban PROJETS
    path("gestion-projets/", views.projects_kanban, name="projects_kanban"),

    # ✅ Tâches
    path("tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:task_id>/edit/", views.task_edit, name="task_edit"),
    path("tasks/<int:task_id>/move/", views.task_move, name="task_move"),
    path("tasks/<int:task_id>/delete/", views.task_delete, name="task_delete"),
    path("tasks/<int:task_id>/quick/", views.task_quick, name="task_quick"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path("tasks/<int:task_id>/assignments/new/", views.task_assignment_create, name="task_assignment_create"),
    path("assignments/<int:assignment_id>/edit/", views.task_assignment_edit, name="task_assignment_edit"),
    path("assignments/<int:assignment_id>/delete/", views.task_assignment_delete, name="task_assignment_delete"),
    ]