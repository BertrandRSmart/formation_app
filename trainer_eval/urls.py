from django.urls import path
from . import views

app_name = "trainer_eval"

urlpatterns = [
    path("satisfaction/", views.session_satisfaction_list, name="session_satisfaction_list"),
    path("satisfaction/<int:pk>/edit/", views.session_satisfaction_edit, name="session_satisfaction_edit"),

    path("internal-evaluations/", views.internal_eval_list, name="internal_eval_list"),
    path("internal-evaluations/new/", views.internal_eval_create, name="internal_eval_create"),
    path("internal-evaluations/<int:pk>/edit/", views.internal_eval_edit, name="internal_eval_edit"),

    path("contributions/", views.contributions_list, name="contributions_list"),
    path("contributions/new/", views.contributions_create, name="contributions_create"),
    path("contributions/<int:pk>/edit/", views.contributions_edit, name="contributions_edit"),

    path("alerts/", views.alerts_list, name="alerts_list"),
    path("alerts/new/", views.alerts_create, name="alerts_create"),
    path("alerts/<int:pk>/edit/", views.alerts_edit, name="alerts_edit"),

    path("dashboard/", views.trainer_eval_dashboard, name="dashboard"),
]