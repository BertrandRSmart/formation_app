from __future__ import annotations

from typing import Optional

from django.db.models import Q

from trainings.models import Participant


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _norm_email(value: str | None) -> str:
    return _norm(value).lower()


def find_existing_participant(
    *,
    first_name: str,
    last_name: str,
    email: str = "",
    client_id: int | None = None,
) -> Optional[Participant]:
    """
    Recherche un participant existant selon une logique métier simple :
    1. email exact si renseigné
    2. sinon nom + prénom + client
    """
    first_name = _norm(first_name)
    last_name = _norm(last_name)
    email = _norm_email(email)

    if email:
        existing = (
            Participant.objects
            .select_related("client", "referrer")
            .filter(email__iexact=email)
            .order_by("id")
            .first()
        )
        if existing:
            return existing

    qs = Participant.objects.select_related("client", "referrer").filter(
        first_name__iexact=first_name,
        last_name__iexact=last_name,
    )

    if client_id:
        qs = qs.filter(client_id=client_id)

    return qs.order_by("id").first()


def get_or_create_participant_identity(
    *,
    first_name: str,
    last_name: str,
    email: str = "",
    client_id: int | None = None,
    company_service: str = "",
    referrer_id: int | None = None,
) -> tuple[Participant, bool]:
    """
    Retourne (participant, created)

    - Réutilise une fiche existante si trouvée
    - Sinon crée un nouveau participant
    - Met à jour certaines infos manquantes sur une fiche existante
    """
    first_name = _norm(first_name)
    last_name = _norm(last_name)
    email = _norm_email(email)
    company_service = _norm(company_service)

    existing = find_existing_participant(
        first_name=first_name,
        last_name=last_name,
        email=email,
        client_id=client_id,
    )

    if existing:
        updated_fields = []

        if not existing.email and email:
            existing.email = email
            updated_fields.append("email")

        if existing.client_id is None and client_id:
            existing.client_id = client_id
            updated_fields.append("client")

        if not _norm(existing.company_service) and company_service:
            existing.company_service = company_service
            updated_fields.append("company_service")

        if existing.referrer_id is None and referrer_id:
            existing.referrer_id = referrer_id
            updated_fields.append("referrer")

        if updated_fields:
            existing.save(update_fields=updated_fields)

        return existing, False

    participant = Participant.objects.create(
        client_id=client_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        company_service=company_service,
        referrer_id=referrer_id,
    )
    return participant, True