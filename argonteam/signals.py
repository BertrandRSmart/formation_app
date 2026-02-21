from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OneToOneMeeting, OneToOneStatus, OneToOneObjective, ObjectiveStatus

# Import Projects (optionnel)
try:
    from projects.models import Project, Task
except Exception:
    Project = None
    Task = None


def _get_or_create_argonos_project():
    """Projet Kanban dédié aux objectifs ArgonOS."""
    if Project is None:
        return None
    name = "Développement Formateurs ArgonOS"
    project, _ = Project.objects.get_or_create(name=name)
    return project


def _create_task(project, objective, meeting):
    """
    Crée une Task sans toucher à assignee (qui attend un User).
    """
    if Task is None or project is None:
        return None

    title = f"[1to1] {objective.title}"
    desc = (
        f"Objectif 1 to 1 — semaine du {meeting.week_start}\n"
        f"Formateur : {meeting.trainer}\n"
        f"Catégorie : {objective.get_category_display()}\n\n"
        f"Détails :\n{getattr(objective, 'description', '') or ''}\n"
    )

    data = {}

    # project
    if hasattr(Task, "project"):
        data["project"] = project

    # title/name
    if hasattr(Task, "title"):
        data["title"] = title
    elif hasattr(Task, "name"):
        data["name"] = title

    # description/notes
    if hasattr(Task, "description"):
        data["description"] = desc
    elif hasattr(Task, "notes"):
        data["notes"] = desc

    # status (adapte si ton Task.status n'est pas TODO)
    if hasattr(Task, "status"):
        data["status"] = "TODO"

    # due date
    if getattr(objective, "due_date", None):
        if hasattr(Task, "due_date"):
            data["due_date"] = objective.due_date
        elif hasattr(Task, "deadline"):
            data["deadline"] = objective.due_date

    # ✅ NE PAS mettre assignee
    # ✅ NE PAS mettre trainer
    return Task.objects.create(**data)


@receiver(post_save, sender=OneToOneMeeting)
def create_tasks_when_validated(sender, instance: OneToOneMeeting, **kwargs):
    """
    Quand un 1 to 1 passe en VALIDÉ :
    - pour chaque objectif actionable=True sans created_task_id
    - créer une Task dans le Kanban
    - stocker l'id dans objective.created_task_id
    """
    if Project is None or Task is None:
        return

    if instance.status != OneToOneStatus.VALIDATED:
        return

    project = _get_or_create_argonos_project()
    if project is None:
        return

    qs = instance.objectives.filter(actionable=True, created_task_id__isnull=True)
    for obj in qs:
        task = _create_task(project, obj, instance)
        if task:
            obj.created_task_id = task.id
            obj.save(update_fields=["created_task_id"])


def _normalize_status(value: str) -> str:
    if not value:
        return ""
    v = str(value).strip().upper()
    v = (
        v.replace("É", "E").replace("È", "E").replace("Ê", "E")
         .replace("À", "A").replace("Ù", "U").replace("Ç", "C")
    )
    return v


DONE_STATUSES = {
    "DONE", "TERMINATED", "TERMINE", "COMPLETED", "CLOSED", "FINISHED", "END",
}

# ✅ IMPORTANT : on déclare ce receiver seulement si Task existe
if Task is not None:

    @receiver(post_save, sender=Task)
    def sync_objectives_when_task_done(sender, instance: "Task", **kwargs):
        """
        Quand une Task passe en Terminé (DONE),
        on met l'objectif lié (created_task_id) en DONE.
        """
        if not hasattr(instance, "status"):
            return

        status_norm = _normalize_status(getattr(instance, "status", ""))

        if status_norm not in DONE_STATUSES:
            return

        (OneToOneObjective.objects
            .filter(created_task_id=instance.id)
            .exclude(status=ObjectiveStatus.DONE)
            .update(status=ObjectiveStatus.DONE)
        )