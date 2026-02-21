import os
from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _safe_filename(s: str) -> str:
    return "".join(c for c in (s or "") if c.isalnum() or c in ("-", "_")).strip() or "session"


def _convocation_dir_for_session(session) -> str:
    ref = session.reference or f"session_{session.pk}"
    folder = os.path.join(settings.MEDIA_ROOT, "convocations", _safe_filename(ref))
    os.makedirs(folder, exist_ok=True)
    return folder


def generate_session_convocation_pdf(session) -> str:
    """
    Génère 1 PDF par session (sans noms participants).
    Retourne le chemin complet du PDF.
    """
    folder = _convocation_dir_for_session(session)
    ref = session.reference or f"session_{session.pk}"

    filename = f"{_safe_filename(ref)}_CONVOCATION.pdf"
    filepath = os.path.join(folder, filename)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4

    # Titre
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 60, "CONVOCATION À UNE FORMATION")

    # Date génération
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 80, f"Générée le : {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Bloc infos session
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 120, "Informations de la session")

    location = session.client_address.strip() if session.on_client_site else (session.room.name if session.room else "")
    teams = (getattr(session, "teams_meeting_url", "") or "").strip()

    lines = [
        f"Référence : {session.reference or '—'}",
        f"Client : {session.client.name}",
        f"Formation : {session.training.title}",
        f"Dates : du {session.start_date.strftime('%d/%m/%Y')} au {session.end_date.strftime('%d/%m/%Y')}",
        f"Formateur : {session.trainer}",
        f"Lieu : {location or '—'}",
        f"Lien Teams (si applicable) : {teams or '—'}",
    ]

    c.setFont("Helvetica", 11)
    y = height - 145
    for line in lines:
        c.drawString(50, y, line)
        y -= 18

    # Notes
    if session.notes:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y - 10, "Notes")
        c.setFont("Helvetica", 11)
        y -= 32
        for line in session.notes.splitlines():
            # Limite simple pour éviter débordement
            c.drawString(50, y, (line or "")[:110])
            y -= 16
            if y < 80:
                c.showPage()
                y = height - 60

    # Pied de page
    c.setFont("Helvetica", 10)
    c.drawString(50, 50, "Merci de vous présenter à l'heure indiquée. En cas d'empêchement, contactez votre référent.")

    c.showPage()
    c.save()
    return filepath


def send_convocation_emails(session, pdf_path: str) -> int:
    """
    Envoie le PDF à tous les participants de la session.
    Pour éviter d'exposer les emails entre eux, on envoie 1 mail par participant.
    Retourne le nombre d'emails envoyés.
    """
    regs = session.registrations.select_related("participant").all()
    emails = [r.participant.email for r in regs if r.participant and r.participant.email]

    location = session.client_address.strip() if session.on_client_site else (session.room.name if session.room else "")
    teams = (getattr(session, "teams_meeting_url", "") or "").strip()

    subject = f"Convocation — {session.training.title} — {session.start_date.strftime('%d/%m/%Y')}"
    body = (
        "Bonjour,\n\n"
        "Veuillez trouver ci-joint la convocation pour la formation.\n\n"
        f"Formation : {session.training.title}\n"
        f"Client : {session.client.name}\n"
        f"Dates : du {session.start_date.strftime('%d/%m/%Y')} au {session.end_date.strftime('%d/%m/%Y')}\n"
        f"Lieu : {location or '—'}\n"
        f"Lien Teams (si applicable) : {teams or '—'}\n\n"
        "Cordialement,\n"
    )

    sent = 0
    for email in emails:
        msg = EmailMessage(subject=subject, body=body, to=[email])
        msg.attach_file(pdf_path)
        msg.send(fail_silently=False)
        sent += 1

    return sent


def generate_and_send_session_convocation(session) -> int:
    """
    Génère le PDF de session + envoie aux participants.
    Met à jour participants_invited_at.
    """
    pdf_path = generate_session_convocation_pdf(session)
    sent = send_convocation_emails(session, pdf_path)

    session.participants_invited_at = timezone.now()
    session.save(update_fields=["participants_invited_at"])

    return sent

generate_and_send_session_convocation = generate_and_send_session_convocation
