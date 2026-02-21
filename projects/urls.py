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
]