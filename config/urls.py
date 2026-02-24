from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from trainings.views import bulk_registrations

urlpatterns = [
    # Test
    path("ping/", lambda request: HttpResponse("PING OK ✅")),

    # ✅ Projects (Kanban)
    path("projects/", include(("projects.urls", "projects"), namespace="projects")),

    path("trainer-eval/", include("trainer_eval.urls")),


    # Admin custom
    path(
        "admin/trainings/inscriptions/",
        admin.site.admin_view(bulk_registrations),
        name="bulk_registrations_admin",
    ),

    # Admin Django
    path("admin/", admin.site.urls),

    # Auth
    path("accounts/", include("django.contrib.auth.urls")),

    # Site (home + trainings)
    path("", include("trainings.urls")),
]
