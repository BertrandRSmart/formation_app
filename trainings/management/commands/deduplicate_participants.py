from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from trainings.models import Participant, Registration


def norm(value: str | None) -> str:
    return (value or "").strip()


def norm_email(value: str | None) -> str:
    return norm(value).lower()


def make_name_key(participant: Participant) -> tuple[str, str, int | None]:
    return (
        norm(participant.first_name).lower(),
        norm(participant.last_name).lower(),
        participant.client_id,
    )


class Command(BaseCommand):
    help = "Fusionne les doublons de participants en regroupant leurs inscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Applique réellement les fusions. Sans --apply, mode simulation uniquement.",
        )
        parser.add_argument(
            "--by",
            choices=["email", "name_client", "all"],
            default="all",
            help="Méthode de détection : email, nom+prénom+client, ou all.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        strategy = options["by"]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("=== Deduplicate Participants ==="))
        self.stdout.write(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")
        self.stdout.write(f"Strategy: {strategy}")
        self.stdout.write("")

        total_groups = 0
        total_duplicates = 0
        total_registrations_moved = 0
        total_participants_deleted = 0

        if strategy in ("email", "all"):
            g, d, r, p = self._process_email_duplicates(apply_changes=apply_changes)
            total_groups += g
            total_duplicates += d
            total_registrations_moved += r
            total_participants_deleted += p

        if strategy in ("name_client", "all"):
            g, d, r, p = self._process_name_client_duplicates(apply_changes=apply_changes)
            total_groups += g
            total_duplicates += d
            total_registrations_moved += r
            total_participants_deleted += p

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Summary ==="))
        self.stdout.write(f"Groups found: {total_groups}")
        self.stdout.write(f"Duplicate participant rows found: {total_duplicates}")
        self.stdout.write(f"Registrations moved: {total_registrations_moved}")
        self.stdout.write(f"Participants deleted: {total_participants_deleted}")
        self.stdout.write("")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    "Simulation only. Re-run with --apply to perform the merge."
                )
            )

    def _choose_master(self, participants: list[Participant]) -> Participant:
        """
        Choisit la fiche maître :
        - priorité à celle qui a le plus d'inscriptions
        - puis email renseigné
        - puis client renseigné
        - puis plus petit id
        """
        def score(p: Participant):
            regs_count = getattr(p, "_regs_count", 0)
            has_email = 1 if norm_email(p.email) else 0
            has_client = 1 if p.client_id else 0
            return (-regs_count, -has_email, -has_client, p.id)

        return sorted(participants, key=score)[0]

    def _merge_group(self, participants: list[Participant], apply_changes: bool):
        if len(participants) <= 1:
            return 0, 0

        for p in participants:
            p._regs_count = getattr(p, "_regs_count", 0)

        master = self._choose_master(participants)
        duplicates = [p for p in participants if p.id != master.id]

        self.stdout.write(
            self.style.HTTP_INFO(
                f"Master #{master.id} -> {master.first_name} {master.last_name} "
                f"| email={master.email or '—'} | client_id={master.client_id or '—'}"
            )
        )

        registrations_moved = 0
        participants_deleted = 0

        for dup in duplicates:
            self.stdout.write(
                f"  Duplicate #{dup.id} -> {dup.first_name} {dup.last_name} "
                f"| email={dup.email or '—'} | client_id={dup.client_id or '—'}"
            )

            dup_regs = list(
                Registration.objects.filter(participant=dup).select_related("session")
            )

            for reg in dup_regs:
                existing_same_session = Registration.objects.filter(
                    session=reg.session,
                    participant=master,
                ).exclude(pk=reg.pk).first()

                if existing_same_session:
                    self.stdout.write(
                        f"    - Registration #{reg.id} skipped "
                        f"(session #{reg.session_id} already linked to master)"
                    )
                    if apply_changes:
                        reg.delete()
                else:
                    self.stdout.write(
                        f"    - Registration #{reg.id} moved to master "
                        f"(session #{reg.session_id})"
                    )
                    if apply_changes:
                        reg.participant = master
                        reg.save(update_fields=["participant"])
                    registrations_moved += 1

            if apply_changes:
                dup.delete()
            participants_deleted += 1

        if apply_changes:
            self._enrich_master(master, duplicates)

        return registrations_moved, participants_deleted

    def _enrich_master(self, master: Participant, duplicates: list[Participant]) -> None:
        """
        Complète la fiche maître avec des infos manquantes.
        """
        updated_fields = []

        if not norm_email(master.email):
            for dup in duplicates:
                if norm_email(dup.email):
                    master.email = norm_email(dup.email)
                    updated_fields.append("email")
                    break

        if not master.client_id:
            for dup in duplicates:
                if dup.client_id:
                    master.client_id = dup.client_id
                    updated_fields.append("client")
                    break

        if not norm(master.company_service):
            for dup in duplicates:
                if norm(dup.company_service):
                    master.company_service = norm(dup.company_service)
                    updated_fields.append("company_service")
                    break

        if not master.referrer_id:
            for dup in duplicates:
                if dup.referrer_id:
                    master.referrer_id = dup.referrer_id
                    updated_fields.append("referrer")
                    break

        if updated_fields:
            master.save(update_fields=updated_fields)

    def _process_email_duplicates(self, apply_changes: bool):
        self.stdout.write(self.style.WARNING("--- Email duplicates ---"))

        duplicates = (
            Participant.objects.exclude(email__isnull=True)
            .exclude(email__exact="")
            .values("email")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
            .order_by("email")
        )

        total_groups = 0
        total_duplicates = 0
        total_registrations_moved = 0
        total_participants_deleted = 0

        for row in duplicates:
            email = norm_email(row["email"])
            participants = list(
                Participant.objects.filter(email__iexact=email)
                .annotate(_regs_count=Count("registrations"))
                .order_by("id")
            )

            if len(participants) <= 1:
                continue

            total_groups += 1
            total_duplicates += len(participants) - 1

            self.stdout.write("")
            self.stdout.write(f"Email group: {email} ({len(participants)} participants)")

            if apply_changes:
                with transaction.atomic():
                    moved, deleted = self._merge_group(participants, apply_changes=True)
            else:
                moved, deleted = self._merge_group(participants, apply_changes=False)

            total_registrations_moved += moved
            total_participants_deleted += deleted

        return (
            total_groups,
            total_duplicates,
            total_registrations_moved,
            total_participants_deleted,
        )

    def _process_name_client_duplicates(self, apply_changes: bool):
        self.stdout.write(self.style.WARNING("--- Name + client duplicates ---"))

        participants = list(
            Participant.objects.all()
            .annotate(_regs_count=Count("registrations"))
            .order_by("last_name", "first_name", "id")
        )

        groups = defaultdict(list)
        for p in participants:
            key = make_name_key(p)
            if key[0] and key[1]:
                groups[key].append(p)

        total_groups = 0
        total_duplicates = 0
        total_registrations_moved = 0
        total_participants_deleted = 0

        for key, group in groups.items():
            if len(group) <= 1:
                continue

            first_name, last_name, client_id = key

            total_groups += 1
            total_duplicates += len(group) - 1

            self.stdout.write("")
            self.stdout.write(
                f"Name+client group: {first_name} {last_name} / client_id={client_id or '—'} "
                f"({len(group)} participants)"
            )

            if apply_changes:
                with transaction.atomic():
                    moved, deleted = self._merge_group(group, apply_changes=True)
            else:
                moved, deleted = self._merge_group(group, apply_changes=False)

            total_registrations_moved += moved
            total_participants_deleted += deleted

        return (
            total_groups,
            total_duplicates,
            total_registrations_moved,
            total_participants_deleted,
        )