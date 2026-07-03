from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shared.tenants"
    verbose_name = "Tenants App"

    # Auditlog is NOT wired for Tenant / TenantSettings / Domain /
    # TenantEmailConfig. Tried 2026-05-20: putting ``auditlog`` into
    # SHARED_APPS as well as TENANT_APPS so we could ``register()``
    # public-schema models here. It fails because
    # ``auditlog.LogEntry`` has a hard FK to
    # ``settings.AUTH_USER_MODEL`` (= ``accounts.JasminUser``, which
    # lives in tenant schemas). Creating ``public.auditlog_logentry``
    # therefore breaks with "relation accounts_jasminuser does not
    # exist". A single global ``AUTH_USER_MODEL`` cannot point at
    # both ``JasminUser`` (tenant) and ``SuperAdmin`` (public), so the
    # gap cannot be closed without forking django-auditlog or
    # building a separate audit table for the public schema.
    #
    # Tenant-lifecycle changes are covered by the structured event
    # log instead — see ``logs/auth.log`` for the
    # ``tenant.created / tenant.updated / tenant.admin_created /
    # user.roles_changed`` lines.
