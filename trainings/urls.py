print("✅ LOADED trainings/urls.py:", __file__)

from django.urls import path
from . import views
from .views import bulk_registrations
from . import views_manage

app_name = "trainings"

urlpatterns = [
    # Home / pages principales
    path("", views.home_view, name="home"),
    path("agenda/", views.agenda_view, name="agenda"),
    path("dashboard/", views.dashboard_view, name="dashboard"),

    # ✅ Pages Équipe
    
    # ✅ Pages Équipe
    # ✅ Pages Équipe
    path("team/", views.team, name="team"),
    path("team/argonos/", views.team_argonos, name="team_argonos"),
    path("team/argonos/create-1to1/", views.create_one_to_one_argonos, name="create_one_to_one_argonos"),
    path("team/argonos/add-objective/", views.add_objective_this_week_argonos, name="add_objective_this_week_argonos"),
    
    path("team/home/", views.team_home, name="team_home"),

    # Alertes convocations
    path("alerts/convocations/<int:session_id>/dismiss/", views.dismiss_convocation_alert, name="dismiss_convocation_alert"),

    # API
    path("api/sessions/", views.sessions_json, name="sessions_json"),
    path("api/trainings/", views.trainings_by_type_json, name="trainings_by_type_json"),
    path("api/clients/", views.clients_list_json, name="clients_list_json"),
    path("api/trainers/", views.trainers_list_json, name="trainers_list_json"),
    path("api/trainings-legend/", views.trainings_legend_json, name="trainings_legend_json"),

    # Détail session existant
    path("sessions/<int:session_id>/", views.session_detail_view, name="session_detail"),

    # Inscriptions en masse
    path("inscriptions/", bulk_registrations, name="bulk_registrations"),

    # Gestion formations (board)
    path("formations/", views_manage.training_manage_home, name="training_manage_home"),

    # Gestion participants (add/edit/delete)
    path("formations/<int:session_id>/participants/add/", views_manage.session_participant_add, name="session_participant_add"),
    path("formations/<int:session_id>/participants/<int:registration_id>/edit/", views_manage.session_participant_edit, name="session_participant_edit"),
    path("formations/<int:session_id>/participants/<int:registration_id>/delete/", views_manage.session_participant_delete, name="session_participant_delete"),

    # Export CSV
    path("formations/<int:session_id>/export-csv/", views_manage.export_participants_csv, name="export_participants_csv"),
]
