# config/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

from trainings.views import bulk_registrations

urlpatterns = [
    # Test
    path("ping/", lambda request: HttpResponse("PING OK ✅")),

    # Trainer eval (AVANT le include trainings)
    path("trainer-eval/", include(("trainer_eval.urls", "trainer_eval"), namespace="trainer_eval")),

    # Projects
    path("projects/", include(("projects.urls", "projects"), namespace="projects")),

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

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)