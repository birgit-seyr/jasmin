from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts App"

    def ready(self) -> None:
        # Wire up signal handlers (e.g. axes lockout -> security.log)
        from . import signals  # noqa: F401
