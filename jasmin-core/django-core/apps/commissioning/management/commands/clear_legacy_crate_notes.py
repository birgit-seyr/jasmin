"""One-shot: clear the "+N" / "-N" notes the crate amount adjustment wrote.

The adjustment that keeps a crate line at the amount the office sets used to
write the difference it applied as the row's note: ``+2`` on a row it raised,
``-1`` on one it lowered. The crate summaries now show each line's note, so
those notes would read as the office's own. This clears every order,
delivery-note and invoice crate note that is exactly such a difference — a
sign, then a whole number without a leading zero — and leaves any other text.

A finalized row, and a row of a finalized document, keeps its note: ``note``
is not among the columns a finalized crate row may change (neither the
models' ``ALLOWED_FINALIZED_UPDATES`` nor the protection triggers list it).
The command counts those rows instead.

Idempotent: a second run finds nothing left to clear.

Usage:
    python manage.py clear_legacy_crate_notes                  # all tenants
    python manage.py clear_legacy_crate_notes --tenant <slug>  # one tenant
    python manage.py clear_legacy_crate_notes --dry-run        # count only
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django_tenants.utils import schema_context

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
)
from apps.shared.tenants.models import Tenant

LEGACY_NOTE_PATTERN = r"^[+-][1-9][0-9]*$"

CrateRowModel = (
    type[CrateOrderContent]
    | type[CrateDeliveryNoteContent]
    | type[CrateContentInvoiceReseller]
)


def _crate_models() -> list[tuple[CrateRowModel, Q]]:
    """Each crate row model, with what makes one of its rows finalized: the
    row itself or the document it belongs to."""
    return [
        (
            CrateOrderContent,
            Q(is_finalized=True)
            | Q(order__is_finalized=True)
            | Q(order_content__order__is_finalized=True),
        ),
        (
            CrateDeliveryNoteContent,
            Q(is_finalized=True) | Q(delivery_note__is_finalized=True),
        ),
        (
            CrateContentInvoiceReseller,
            Q(is_finalized=True) | Q(invoice__is_finalized=True),
        ),
    ]


class Command(BaseCommand):
    help = (
        'Clear the "+N" / "-N" notes the crate amount adjustment wrote on '
        "draft order, delivery-note and invoice crate rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            help="Limit to one tenant (schema_name). Default: all active tenants.",
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count the notes that would be cleared without clearing them.",
        )

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant")
        if tenant_slug:
            tenants = Tenant.objects.filter(schema_name=tenant_slug)
            if not tenants.exists():
                raise CommandError(f"No tenant with schema '{tenant_slug}'.")
        else:
            tenants = Tenant.objects.filter(is_active=True).exclude(
                schema_name="public"
            )

        dry_run = options["dry_run"]
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                suffix = " (dry run)" if dry_run else ""
                self.stdout.write(f"Tenant {tenant.schema_name}{suffix}:")
                self._clear_tenant(dry_run)

    def _clear_tenant(self, dry_run: bool) -> None:
        verb = "would clear" if dry_run else "cleared"
        with transaction.atomic():
            for model, finalized in _crate_models():
                legacy = model.objects.filter(note__regex=LEGACY_NOTE_PATTERN)
                skipped = legacy.filter(finalized).count()
                draft = legacy.exclude(finalized)
                cleared = draft.count() if dry_run else draft.update(note=None)
                self.stdout.write(
                    f"  {model.__name__}: {verb} {cleared}, "
                    f"skipped {skipped} finalized"
                )
