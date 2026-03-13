# trainings/services/invitations.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import pdfkit
from django.conf import settings
from django.template.loader import render_to_string
from django.templatetags.static import static

from trainings.models import Registration, Session


@dataclass
class InvitationResult:
    folder_rel: str
    folder_abs: str
    pdf_files: list[str]
    emails_file: str


def _safe_filename(s: str) -> str:
    s = (s or "").strip()
    keep = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            keep.append(ch)
    out = "".join(keep).strip().replace("  ", " ").replace(" ", "_")
    return out or "file"


def _location_address_only(session: Session) -> str:
    """Adresse uniquement (chez client -> client_address, sinon room.location)."""
    if getattr(session, "on_client_site", False):
        return (getattr(session, "client_address", "") or "").strip()
    room = getattr(session, "room", None)
    return (getattr(room, "location", "") or "").strip() if room else ""


def _get_wkhtml_config() -> pdfkit.configuration:
    wk = (getattr(settings, "WKHTMLTOPDF_CMD", "") or "").strip()
    if not wk:
        raise RuntimeError("WKHTMLTOPDF_CMD manquant dans settings.py")
    return pdfkit.configuration(wkhtmltopdf=wk)


def generate_invitations_for_session(*, session: Session, lang: str, base_url: str) -> InvitationResult:
    """
    Génère 1 PDF par participant pour une session, dans MEDIA_ROOT/convocations/<reference>/
    + un fichier emails_<lang>.txt (emails uniques des participants).

    Templates attendus :
      trainings/templates/trainings/invitations/convocation_fr.html
      trainings/templates/trainings/invitations/convocation_en.html
    """
    lang = (lang or "fr").lower().strip()
    if lang not in ("fr", "en"):
        lang = "fr"

    template_name = f"trainings/invitations/convocation_{lang}.html"

    config = _get_wkhtml_config()

    # Dossier de sortie
    reference = _safe_filename(session.reference or f"session_{session.id}")
    folder_rel = f"convocations/{reference}"
    folder_abs = os.path.join(str(settings.MEDIA_ROOT), folder_rel)
    Path(folder_abs).mkdir(parents=True, exist_ok=True)

    # Inscriptions / participants
    regs = (
        Registration.objects.select_related("participant")
        .filter(session=session)
        .order_by("participant__last_name", "participant__first_name")
    )

    # Adresse + lien Google Maps
    
    address = _location_address_only(session)
    
    map_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}" if address else ""

    # emails.txt
    emails = []
    for r in regs:
        em = (getattr(r.participant, "email", "") or "").strip()
        if em:
            emails.append(em)
    emails_unique = sorted(set(emails), key=lambda x: x.lower())

    emails_filename = f"emails_{lang}.txt"
    emails_path = os.path.join(folder_abs, emails_filename)
    with open(emails_path, "w", encoding="utf-8") as f:
        f.write("\n".join(emails_unique) + ("\n" if emails_unique else ""))

    # Options wkhtmltopdf (A4 plein cadre + assets)
    options = {
    "encoding": "UTF-8",
    "quiet": "",
    "page-size": "A4",
    "margin-top": "0mm",
    "margin-right": "0mm",
    "margin-bottom": "0mm",
    "margin-left": "0mm",

    # IMPORTANT pour les couleurs + CSS "print"
    "print-media-type": "",
    "background": "",

    # évite les déformations / sauts de page bizarres
    "disable-smart-shrinking": "",
    "dpi": "96",
    "zoom": "1",

    # assets
    "enable-local-file-access": "",
    "load-error-handling": "ignore",
    "load-media-error-handling": "ignore",
    }

    # Horaires (si tu veux les rendre dynamiques plus tard, remplace ici)
    schedule_am = "09:00-12:00"
    schedule_pm = "13:30-16:30"

    # Logo en URL absolue (servi par Django /static/)
    # -> place le fichier ici: trainings/static/trainings/logo-ArgonOS.png
    base_url = (base_url or "").rstrip("/") + "/"
    logo_url = base_url.rstrip("/") + static("trainings/logo-ArgonOS.png")

    pdf_files: list[str] = []
    today = date.today()

    for r in regs:
        p = r.participant

        ctx = {
            "today": today,
            "session": session,
            "participant": p,
            "schedule_am": schedule_am,
            "schedule_pm": schedule_pm,
            "location_address": address,
            "map_url": map_url,
            "logo_url": logo_url,
        }

        html = render_to_string(template_name, ctx)

        last = _safe_filename(getattr(p, "last_name", "") or "")
        first = _safe_filename(getattr(p, "first_name", "") or "")
        pdf_name = f"Convocation_{last}_{first}_{lang.upper()}.pdf"
        pdf_path = os.path.join(folder_abs, pdf_name)

        pdfkit.from_string(html, pdf_path, configuration=config, options=options)
        pdf_files.append(pdf_name)

    return InvitationResult(
        folder_rel=folder_rel,
        folder_abs=folder_abs,
        pdf_files=pdf_files,
        emails_file=emails_filename,
    )

def generate_invitation_for_registration(*, registration: Registration, lang: str, base_url: str) -> str:
    """
    Génère 1 seul PDF pour une inscription donnée.
    Retourne le chemin absolu du PDF généré.
    """
    lang = (lang or "fr").lower().strip()
    if lang not in ("fr", "en"):
        lang = "fr"

    session = registration.session
    participant = registration.participant
    template_name = f"trainings/invitations/convocation_{lang}.html"

    config = _get_wkhtml_config()

    reference = _safe_filename(session.reference or f"session_{session.id}")
    folder_rel = f"convocations/{reference}"
    folder_abs = os.path.join(str(settings.MEDIA_ROOT), folder_rel)
    Path(folder_abs).mkdir(parents=True, exist_ok=True)

    address = _location_address_only(session)
    map_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}" if address else ""

    options = {
        "encoding": "UTF-8",
        "quiet": "",
        "page-size": "A4",
        "margin-top": "0mm",
        "margin-right": "0mm",
        "margin-bottom": "0mm",
        "margin-left": "0mm",
        "print-media-type": "",
        "background": "",
        "disable-smart-shrinking": "",
        "dpi": "96",
        "zoom": "1",
        "enable-local-file-access": "",
        "load-error-handling": "ignore",
        "load-media-error-handling": "ignore",
    }

    schedule_am = "09:00-12:00"
    schedule_pm = "13:30-16:30"

    base_url = (base_url or "").rstrip("/") + "/"
    logo_url = base_url.rstrip("/") + static("trainings/logo-ArgonOS.png")

    ctx = {
        "today": date.today(),
        "session": session,
        "participant": participant,
        "schedule_am": schedule_am,
        "schedule_pm": schedule_pm,
        "location_address": address,
        "map_url": map_url,
        "logo_url": logo_url,
    }

    html = render_to_string(template_name, ctx)

    last = _safe_filename(getattr(participant, "last_name", "") or "")
    first = _safe_filename(getattr(participant, "first_name", "") or "")
    pdf_name = f"Convocation_{last}_{first}_{lang.upper()}.pdf"
    pdf_path = os.path.join(folder_abs, pdf_name)

    pdfkit.from_string(html, pdf_path, configuration=config, options=options)
    return pdf_path