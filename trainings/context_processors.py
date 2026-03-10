from django.utils import timezone

def global_dates(request):
    return {"today": timezone.localdate()}