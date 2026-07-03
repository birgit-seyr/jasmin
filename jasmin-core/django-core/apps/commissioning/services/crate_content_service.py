"""Shared logic for crate-content viewsets.

Three viewsets (:class:`CrateOrderContentViewSet`,
:class:`CrateDeliveryNoteContentViewSet`,
:class:`CrateContentInvoiceResellerViewSet`) all maintain crate quantities the
same way: they sum ``amount`` over a scoped queryset, compute the delta to a
desired new total, and either adjust an existing "manual adjustment" row,
delete it if it zeroes out, or create a new one for the difference.

This service centralises that algorithm so the viewsets only need to declare
the scope, the adjustment-row scope, and the FK kwargs for new rows.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet, Sum

from core.db_locks import acquire_advisory_xact_lock


class CrateContentService:
    @staticmethod
    @transaction.atomic
    def apply_total_amount_change(
        *,
        scope_qs: QuerySet,
        adjustment_qs: QuerySet | None,
        new_total_amount: int,
        update_fields: dict[str, Any],
        create_kwargs: dict[str, Any],
        model_class: type,
        lock_key: str,
    ) -> None:
        """Force ``Sum('amount')`` over ``scope_qs`` to equal ``new_total_amount``.

        Steps:
        1. Acquire a Postgres advisory lock keyed by ``lock_key`` so
           concurrent writers on the same parent (Invoice / DeliveryNote +
           crate_type) serialise. Without this, two simultaneous edits
           both read the same ``current_total``, both compute the same
           delta, and both create offsetting adjustment rows — silently
           doubling the correction. No UNIQUE constraint catches that.
        2. Bulk-update ``update_fields`` (price_per_unit, rabatt, [tax_rate]) on
           every row in ``scope_qs``.
        3. Re-aggregate ``Sum('amount')`` and compute the delta.
        4. If delta is zero, return.
        5. Otherwise look up an existing manual-adjustment row in
           ``adjustment_qs`` (defaults to ``scope_qs``):
           - if found: add the delta. If the row reaches 0, delete it; else save.
           - if not found: create a new row with ``create_kwargs`` + delta + update_fields.

        ``create_kwargs`` should carry the FKs (e.g. ``order=order, crate_type=crate_type``).
        ``lock_key`` should uniquely identify the parent scope, e.g.
        ``f"crate_totals:InvoiceReseller:{invoice.id}:{crate_type.id}"``.
        Caller wraps in its own transaction if needed (this method already opens one).
        """
        acquire_advisory_xact_lock(lock_key)

        scope_qs.update(**update_fields)

        current_total = scope_qs.aggregate(total=Sum("amount"))["total"] or 0
        difference = int(new_total_amount) - int(current_total)
        if difference == 0:
            return

        adjustment = (
            (adjustment_qs if adjustment_qs is not None else scope_qs)
            .select_for_update()
            .first()
        )
        note = f"{'+' if difference > 0 else ''}{difference}"

        if adjustment is not None:
            adjustment.amount += difference
            if adjustment.amount == 0:
                adjustment.delete()
                return
            for field, value in update_fields.items():
                setattr(adjustment, field, value)
            adjustment.note = note
            adjustment.save()
            return

        model_class.objects.create(
            **create_kwargs,
            amount=difference,
            **update_fields,
            note=note,
        )
