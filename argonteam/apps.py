from django.apps import AppConfig

class ArgonteamConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "argonteam"

    def ready(self):
        # ✅ charge les signals proprement
        from . import signals  # noqa