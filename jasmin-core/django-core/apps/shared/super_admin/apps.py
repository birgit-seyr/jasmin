from django.apps import AppConfig


class SuperAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shared.super_admin"
    verbose_name = "Super Admin App"

    # No auditlog registration here — see the long-form note in
    # ``apps/shared/tenants/apps.py``. Same root cause:
    # ``auditlog.LogEntry`` cannot live in the public schema while
    # ``AUTH_USER_MODEL`` resolves to a tenant-scoped table.
