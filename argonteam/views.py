from argonteam.forms import OneToOneObjectiveForm

from django.views.decorators.http import require_POST
from argonteam.models import OneToOneMeeting
from datetime import timedelta
from django.utils import timezone

def _monday_of_week(d):
    return d - timedelta(days=d.weekday())

@login_required
@require_POST
def add_objective_this_week_argonos(request):
    trainer_id = request.GET.get("trainer")
    trainer = get_object_or_404(Trainer, id=trainer_id, product="ARGONOS")

    today = timezone.localdate()
    week_start = _monday_of_week(today)

    meeting, _ = OneToOneMeeting.objects.get_or_create(
        trainer=trainer,
        week_start=week_start,
    )

    form = OneToOneObjectiveForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.meeting = meeting
        obj.save()

    return redirect(f"{reverse('trainings:team_argonos')}?trainer={trainer.id}&tab=1to1")