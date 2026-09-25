from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts App"

    def ready(self) -> None:
        from auditlog.registry import auditlog

        # Wire up signal handlers (e.g. axes lockout -> security.log)
        from . import signals  # noqa: F401
        from .models import JasminProfile, JasminUser

        # ``password`` and ``last_login`` are EXCLUDED rather than masked — a
        # hash has no audit value, and a login timestamp would bury the real
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

        # Role grants, demotions and deactivations are the first thing an
        # auditor asks about, and nothing else records them durably: the
        # service layer writes one line to auth.log, which rotates.
        #
        # Registration is per model class and auditlog diffs concrete fields
        # only, so this has to be its own call — the roles are on the profile,
        # and a property on JasminUser is invisible to the differ. Role history
        # therefore lives under the profile's content type, not the user's.
        auditlog.register(JasminProfile)
