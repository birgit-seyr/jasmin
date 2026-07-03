import logging

from django.utils import timezone
from django_tenants.utils import schema_context, schema_exists

from .errors import SchemaAlreadyExists
from .models import Domain, Tenant, TenantSettings
from .provisioning import (
    normalize_domain,
    validate_admin_password,
    validate_schema_name,
)

logger = logging.getLogger(__name__)


class TenantService:
    def provision_tenant(
        self,
        *,
        schema_name: str,
        name: str,
        domain: str,
        tenant_language: str = "",
        admin_email: str,
        admin_password: str,
        admin_first_name: str = "",
        admin_last_name: str = "",
    ) -> dict:
        """Full tenant provisioning in one call.

        Steps:
          1. Create Tenant + Domain + TenantSettings in the public schema
             (creating the Tenant also auto-creates + migrates the tenant
             schema via django-tenants' ``auto_create_schema=True``).
          2. Create the admin user inside the new tenant schema.

        Self-cleaning: schema-creation/migration DDL commits on its own
        connection and can't be rolled back by a Python transaction, so on ANY
        failure after the Tenant row exists this drops the tenant
        (``delete(force_drop=True)`` → ``DROP SCHEMA CASCADE`` + cascades the
        Domain/TenantSettings rows) before re-raising — never leaving an
        orphaned schema or a half-provisioned, admin-less tenant.

        Default reference data (PaymentCycles + Storage rows) is seeded by
        ``apps/commissioning/migrations/0002_finalized_protection_and_reference_data.py``
        (its ``_seed`` RunPython step), and the default OfferGroup singleton by
        ``apps/commissioning/migrations/0014_offergroup_is_default_and_more.py``;
        both run as part of ``migrate_schemas --tenant`` for every new schema —
        idempotent on existing tenants, no separate fixture file to keep in sync.
        """
        # Validate on the shared sink so EVERY caller (HTTP serializer, dev
        # seeder) gets the same guards — not just the one that happens to run an
        # input serializer first.
        schema_name = validate_schema_name(schema_name)
        domain = normalize_domain(domain)
        validate_admin_password(admin_password)
        # Refuse a pre-existing schema up front: otherwise create_schema would
        # no-op (skip migration), the admin-user step would then fail, and the
        # self-cleaning DROP below would destroy a schema this call never created.
        if schema_exists(schema_name):
            raise SchemaAlreadyExists(
                f"schema '{schema_name}' already exists",
                details={"schema_name": schema_name},
            )

        tenant = None
        try:
            with schema_context("public"):
                tenant = Tenant.objects.create(
                    schema_name=schema_name,
                    name=name,
                    tenant_language=tenant_language or "",
                )
                Domain.objects.create(domain=domain, tenant=tenant, is_primary=True)
                # Versioned settings row: every tenant needs one current
                # (valid_until=NULL) TenantSettings so payments / billing /
                # member-flow code can rely on ``get_current_settings``
                # returning something. All fields have sensible defaults.
                TenantSettings.objects.create(
                    tenant=tenant,
                    valid_from=timezone.now(),
                )

            logger.info(f"Created tenant '{name}' (schema={schema_name})")

            with schema_context(tenant.schema_name):
                from apps.accounts.models import JasminUser

                admin_user = JasminUser.objects.create_user(
                    email=admin_email,
                    password=admin_password,
                    first_name=admin_first_name,
                    last_name=admin_last_name,
                    is_active=True,
                    account_status="active",
                    roles=["admin"],
                )
                logger.info(f"Created admin user '{admin_email}' for tenant '{name}'")
        except Exception:
            # Any failure after the Tenant row exists would otherwise strand a
            # fully-migrated orphan schema (and possibly an admin-less, locked-out
            # tenant). Drop it (row + schema + cascaded Domain/TenantSettings).
            # Re-fetch in the public schema — django-tenants forbids deleting a
            # tenant from another tenant's schema_context.
            if tenant is not None and tenant.pk:
                try:
                    with schema_context("public"):
                        Tenant.objects.get(pk=tenant.pk).delete(force_drop=True)
                except Exception:
                    logger.exception(
                        "Failed to clean up orphaned tenant schema=%s after "
                        "provisioning failure",
                        schema_name,
                    )
            raise

        return {
            "tenant": tenant,
            "admin_user": admin_user,
        }
