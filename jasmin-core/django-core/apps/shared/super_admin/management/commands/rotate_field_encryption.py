"""Re-encrypt every ``EncryptedCharField`` value with the current
``FIELD_ENCRYPTION_KEY``.

When to run this
----------------
``django-encrypted-model-fields`` reads ``FIELD_ENCRYPTION_KEY`` from
settings. It supports a comma-separated list of keys:

  * The first key is used to ENCRYPT new writes.
  * All keys are tried (in order) to DECRYPT existing reads.

When you rotate the key, every existing ciphertext in the DB was
encrypted with the OLD key. The library falls back through the key
list and still decrypts them — as long as the old key is in the list.
Drop the old key without re-encrypting first and the existing rows
become undecryptable.

The full rotation procedure is:

  1. Generate a new key
     (``python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'``)
     and PREPEND it to ``FIELD_ENCRYPTION_KEY`` in the .env file:
     ``FIELD_ENCRYPTION_KEY=<new>,<old>``
  2. Deploy. From this moment new writes use the new key; old reads
     still work via the old key fallback.
  3. **Run this command**:
     ``python manage.py rotate_field_encryption``
     It iterates every row of every encrypted field and writes it
     back, which re-encrypts with the new (first) key.
  4. After the command finishes cleanly, drop the old key:
     ``FIELD_ENCRYPTION_KEY=<new>``
  5. Deploy again.

Usage
-----
::

    python manage.py rotate_field_encryption --dry-run
    python manage.py rotate_field_encryption

``--dry-run`` reports counts per field without writing. The real run
processes a model+field at a time in chunks; each chunk is its own
transaction so a crash mid-run leaves the DB in a consistent state
(re-running picks up where it left off — every row is idempotent).

What gets touched (6 fields, 4 models)
---------------------------------------

Public schema:
  * ``shared.tenants.TenantEmailConfig.smtp_password``

Tenant schemas (iterated per tenant via ``schema_context``):
  * ``commissioning.Member.account_owner``
  * ``commissioning.Member.iban``
  * ``commissioning.ContactEntity.iban``
  * ``payments.BillingProfile.iban``
  * ``payments.BillingProfile.account_holder``

Why "write it back" re-encrypts
-------------------------------
The field's setter doesn't know whether the value changed — it
re-encrypts on every assignment. So ``obj.iban = obj.iban`` reads
the decrypted value (with whatever key works), then writes it back
encrypted with the first key in the list. Idempotent at the DB
level: re-running this command after success is a no-op except for
the round-trip cost.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from apps.shared.tenants.models import Tenant

logger = logging.getLogger("super_admin")

# (app_label, model_name, [field_names...]) per scope.
# Order intentional: lighter rows first so dry-run feedback is fast.
PUBLIC_SCHEMA_TARGETS: list[tuple[str, str, list[str]]] = [
    ("tenants", "TenantEmailConfig", ["smtp_password"]),
]

TENANT_SCHEMA_TARGETS: list[tuple[str, str, list[str]]] = [
    ("commissioning", "ContactEntity", ["iban"]),
    ("commissioning", "Member", ["account_owner", "iban"]),
    ("payments", "BillingProfile", ["iban", "account_holder"]),
]

# Chunk size for the iterator + transaction-per-chunk pattern.
# 500 keeps each transaction short (sub-second on typical hardware)
# without paying the per-transaction overhead for every row.
CHUNK_SIZE = 500


class Command(BaseCommand):
    help = (
        "Re-encrypt every EncryptedCharField with the current first key "
        "in FIELD_ENCRYPTION_KEY. Run after rotating the key + adding the "
        "new key to the head of the list. See the module docstring for "
        "the full procedure."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts per field without writing.",
        )
        parser.add_argument(
            "--schema",
            default=None,
            help=(
                "Only process this tenant schema (still also processes "
                "the public schema for shared models). Default: all tenants."
            ),
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]
        only_schema = options["schema"]

        total_rows = 0
        total_models = 0

        # Public-schema models (TenantEmailConfig).
        with schema_context("public"):
            for app_label, model_name, field_names in PUBLIC_SCHEMA_TARGETS:
                rows = self._rotate_model(
                    schema_name="public",
                    app_label=app_label,
                    model_name=model_name,
                    field_names=field_names,
                    dry_run=dry_run,
                )
                total_rows += rows
                total_models += 1

        # Tenant-schema models — iterate every tenant.
        tenants_qs = Tenant.objects.exclude(schema_name="public")
        if only_schema:
            tenants_qs = tenants_qs.filter(schema_name=only_schema)

        for tenant in tenants_qs.iterator():
            with schema_context(tenant.schema_name):
                for app_label, model_name, field_names in TENANT_SCHEMA_TARGETS:
                    rows = self._rotate_model(
                        schema_name=tenant.schema_name,
                        app_label=app_label,
                        model_name=model_name,
                        field_names=field_names,
                        dry_run=dry_run,
                    )
                    total_rows += rows
                    total_models += 1

        verb = "Would re-encrypt" if dry_run else "Re-encrypted"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{verb} {total_rows} row(s) across {total_models} " f"model(s)."
            )
        )
        if dry_run:
            self.stdout.write(
                "Run again without --dry-run to actually write the "
                "re-encrypted values."
            )

    def _rotate_model(
        self,
        *,
        schema_name: str,
        app_label: str,
        model_name: str,
        field_names: list[str],
        dry_run: bool,
    ) -> int:
        """Process one model in one schema. Returns the row count touched.

        Iterator-based + transaction-per-chunk so big tables don't load
        into memory and a crash mid-run leaves the DB consistent
        (already-processed rows stay re-encrypted; unprocessed rows
        still decrypt via the old key fallback).
        """
        from django.apps import apps

        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            # App not installed in this schema (e.g. cultivation off
            # in some tenants). Skip silently.
            return 0

        total = model.objects.count()
        if total == 0:
            self.stdout.write(
                f"  [{schema_name}] {app_label}.{model_name}: 0 rows — skipped"
            )
            return 0

        if dry_run:
            self.stdout.write(
                f"  [{schema_name}] {app_label}.{model_name}: "
                f"{total} row(s) would touch fields {field_names}"
            )
            return total

        self.stdout.write(
            f"  [{schema_name}] {app_label}.{model_name}: "
            f"re-encrypting {total} row(s)..."
        )

        processed = 0
        # ``.iterator(chunk_size=...)`` streams rows without loading the
        # full queryset into memory. Pair with transaction-per-chunk
        # below for the consistency guarantee.
        for chunk_start in range(0, total, CHUNK_SIZE):
            with transaction.atomic():
                # ``.only(...pk + field_names)`` keeps each row tiny.
                chunk = model.objects.only("pk", *field_names).order_by("pk")[
                    chunk_start : chunk_start + CHUNK_SIZE
                ]
                for obj in chunk:
                    # Trigger the EncryptedCharField setter for each
                    # field. Reading the attribute decrypts (using
                    # whichever key in the list works); the assignment
                    # re-encrypts with the new first key.
                    for field_name in field_names:
                        setattr(obj, field_name, getattr(obj, field_name))
                    obj.save(update_fields=list(field_names))
                    processed += 1

            # Progress every 10 chunks for big tables.
            if (chunk_start // CHUNK_SIZE) % 10 == 9:
                self.stdout.write(f"    ... {processed}/{total}")

        logger.info(
            "field_encryption.rotated schema=%s model=%s.%s rows=%d fields=%s",
            schema_name,
            app_label,
            model_name,
            processed,
            field_names,
        )
        self.stdout.write(self.style.SUCCESS(f"    done: {processed}/{total} rows"))
        return processed
