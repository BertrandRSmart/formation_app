from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Registration, Session, RegistrationStatus


CAPACITY_10_TITLES = {
    "Initiation",
    "Data Exploration niveau 1",
    "Data Préparation niveau 1",
}

CAPACITY_6_TITLES = {
    "Développeur niveau 1",
    "Admin Système Installation",
}


def _capacity_for_session(session: Session) -> int:
    title = (session.training.title or "").strip()
    if title in CAPACITY_10_TITLES:
        return 10
    if title in CAPACITY_6_TITLES:
        return 6
    return 10


def _recompute_counts(session_id: int) -> None:
    session = Session.objects.select_related("training").get(id=session_id)

    expected = _capacity_for_session(session)

    present = (
        Registration.objects
        .filter(session_id=session_id, status=RegistrationStatus.PRESENT)
        .values("participant_id")
        .distinct()
        .count()
    )

    Session.objects.filter(id=session_id).update(
        expected_participants=expected,
        present_count=present,
    )


@receiver(post_save, sender=Registration)
def registration_saved(sender, instance, **kwargs):
    _recompute_counts(instance.session_id)


@receiver(post_delete, sender=Registration)
def registration_deleted(sender, instance, **kwargs):
    _recompute_counts(instance.session_id)
