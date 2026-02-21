from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.forms.models import BaseInlineFormSet

from .models import OneToOneMeeting, OneToOneObjective


def _has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except FieldDoesNotExist:
        return False


# On détecte le champ qui représente "fait/terminé"
# (tu peux en ajouter d'autres si besoin)
if _has_field(OneToOneObjective, "done"):
    OBJ_DONE_FIELD = "done"
elif _has_field(OneToOneObjective, "status"):
    OBJ_DONE_FIELD = "status"
elif _has_field(OneToOneObjective, "is_done"):
    OBJ_DONE_FIELD = "is_done"
elif _has_field(OneToOneObjective, "completed"):
    OBJ_DONE_FIELD = "completed"
else:
    OBJ_DONE_FIELD = None


class OneToOneObjectiveInlineFormSet(BaseInlineFormSet):
    """Sécurise le lien meeting -> objectif (inline)."""
    def save_new(self, form, commit=True):
        obj = form.save(commit=False)
        obj.meeting = self.instance
        if commit:
            obj.save()
            form.save_m2m()
        return obj


class OneToOneObjectiveInline(admin.TabularInline):
    model = OneToOneObjective
    formset = OneToOneObjectiveInlineFormSet
    extra = 0
    show_change_link = True

    def get_fields(self, request, obj=None):
        fields = ["title"]
        if OBJ_DONE_FIELD:
            fields.append(OBJ_DONE_FIELD)
        return fields


@admin.register(OneToOneMeeting)
class OneToOneMeetingAdmin(admin.ModelAdmin):
    list_display = ("trainer", "week_start", "created_at")
    list_filter = ("week_start", "trainer")
    search_fields = ("trainer__first_name", "trainer__last_name")
    ordering = ("-week_start",)
    inlines = [OneToOneObjectiveInline]


@admin.register(OneToOneObjective)
class OneToOneObjectiveAdmin(admin.ModelAdmin):
    def get_list_display(self, request):
        base = ["meeting", "title"]
        if OBJ_DONE_FIELD:
            base.append(OBJ_DONE_FIELD)
        return tuple(base)

    def get_list_filter(self, request):
        if OBJ_DONE_FIELD:
            return (OBJ_DONE_FIELD,)
        return tuple()

    search_fields = ("title", "meeting__trainer__first_name", "meeting__trainer__last_name")
    ordering = ("-id",)