from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts App"

    def ready(self) -> None:
        from auditlog.registry import auditlog

        # Wire up signal handlers (e.g. axes lockout -> security.log)
        from . import signals  # noqa: F401
        from .models import JasminUser

        # Role grants, demotions and deactivations are the first thing an
        # auditor asks about, and nothing durable recorded them: the service
        # layer writes one line to auth.log, which rotates.
        #
        # ``password`` and ``last_login`` are EXCLUDED rather than masked — a
        # hash has no audit value, and a login timestamp would bury the role
        # changes in noise, as would ``updated_at`` on every save. The PII
        # columns are masked on the same bias as ``Member`` and
        # ``BillingProfile``: raw values must not land in diffs retained
        # indefinitely. What masking misses, erasure still reaches —
        # ``GDPRService._scrub_auditlog_entries`` takes the user directly.
        auditlog.register(
            JasminUser,
            exclude_fields=["password", "last_login", "updated_at"],
            mask_fields=[
                "email",
                "username",
                "first_name",
                "last_name",
                "last_login_ip",
            ],
        )
