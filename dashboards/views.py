from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import render
from django.utils import timezone
from django.urls import reverse

from trainings.models import Session



@staff_member_required
def dashboard_home(request):
    today = timezone.localdate()

    qs = Session.objects.all()

    total_sessions = qs.count()
    upcoming_sessions = qs.filter(start_date__gte=today).count()

    by_status = list(
        qs.values("status")
          .annotate(n=Count("id"))
          .order_by("status")
    )

    avg_satisfaction = qs.exclude(client_satisfaction__isnull=True).aggregate(
        avg=Avg("client_satisfaction")
    )["avg"]

    totals = qs.aggregate(
        expected=Sum("expected_participants"),
        present=Sum("present_count"),
    )
    expected_total = totals["expected"] or 0
    present_total = totals["present"] or 0
    presence_rate = (present_total / expected_total * 100) if expected_total else None

    # --- Alertes (version simple : sessions qui démarrent aujourd'hui) ---
    sessions_today = qs.filter(start_date=today).select_related("client", "training")

    convocation_alerts = []
    for s in sessions_today:
        convocation_alerts.append({
            "title": getattr(s, "title", None) or str(s),
            "client": getattr(s, "client", ""),
            "training": getattr(s, "training", ""),
            "start": s.start_date,
            "end": s.end_date,
            "admin_url": reverse("admin:trainings_session_change", args=[s.id]),
        })

    context = {
        "today": today,
        "convocation_alerts": convocation_alerts,

        "total_sessions": total_sessions,
        "upcoming_sessions": upcoming_sessions,
        "by_status": by_status,
        "avg_satisfaction": avg_satisfaction,
        "expected_total": expected_total,
        "present_total": present_total,
        "presence_rate": presence_rate,

        # si tu n'as pas encore labels_type/values_type, ça n'explosera pas grâce au default dans le template
        "labels_type": [],
        "values_type": [],
    }

    return render(request, "dashboards/home.html", context)
