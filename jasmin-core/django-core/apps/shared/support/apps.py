from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shared.support"
    verbose_name = "Support Tickets"
    # NOTE: no auditlog.register() here. auditlog is a TENANT_APP whose
    # LogEntry table does not exist in the public schema, so registering a
    # public-schema model would raise on write. Super-admin mutations are
    # audited via the ``super_admin`` logger instead (see admin_viewsets.py).
