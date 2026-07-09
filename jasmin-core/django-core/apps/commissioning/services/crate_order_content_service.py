from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet

from ..errors import CrateNotFound
from ..models import Crate, CrateOrderContent, Order
from ..utils.iso_week_utils import date_from_order, week_day_to_date
from ..utils.tax_rate_utils import effective_crate_tax_rate
from .crate_summary import build_crate_summary_row, summarize_crate_items


class CrateOrderContentService:
    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _period_filter(
        year: int,
        delivery_week: int,
        day_number: int,
        reseller,
    ) -> Q:
        """Build the base Q filter for order_content->order and direct order paths."""
        return Q(
            order_content__isnull=False,
            order_content__order__year=year,
            order_content__order__delivery_week=delivery_week,
            order_content__order__day_number=day_number,
            order_content__order__reseller=reseller,
        ) | Q(
            order__isnull=False,
            order__year=year,
            order__delivery_week=delivery_week,
            order__day_number=day_number,
            order__reseller=reseller,
        )

    @staticmethod
    def _serialize(crate_order_content: CrateOrderContent) -> dict[str, Any]:
        """Serialize a CrateOrderContent into a flat dict.

        Money fields go out as canonical 2dp strings with ``line_netto``
        computed once in Decimal on the backend (via
        ``build_crate_summary_row``), matching the DN/invoice crate
        summary — never as JSON floats.
        """
        tax_rate = (
            crate_order_content.tax_rate
            if crate_order_content.tax_rate is not None
            else effective_crate_tax_rate(
                crate_order_content.crate_type,
                CrateOrderContentService._date_from_crate_order_content(
                    crate_order_content
                ),
            )
        )
        return build_crate_summary_row(
            crate_type_id=crate_order_content.crate_type_id,
            crate_type_name=crate_order_content.crate_type.name,
            amount=crate_order_content.amount,
            price=crate_order_content.price_per_unit,
            rabatt=crate_order_content.rabatt,
            tax_rate=tax_rate,
            extras={"note": crate_order_content.note},
        )

    @staticmethod
    def _date_from_crate_order_content(crate_order_content: CrateOrderContent) -> date:
        """Derive the calendar date from a CrateOrderContent's order chain.

        Falls back to today when no order is reachable.
        """
        order = crate_order_content.order or (
            crate_order_content.order_content.order
            if crate_order_content.order_content
            else None
        )
        return date_from_order(order)

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    @staticmethod
    def get_crates_summary_for_period(
        year: int,
        delivery_week: int,
        day_number: int,
        reseller,
    ) -> list[dict[str, Any]]:
        """Get aggregated crate summary for a specific period and reseller.

        Groups by (crate_type, price_per_unit, rabatt, tax_rate) via
        ``summarize_crate_items`` so the displayed price / rabatt / tax_rate are
        the exact per-group values and ``line_netto`` is the SUM of the grouped
        rows' per-row nets — matching the delivery-note / invoice crate summary,
        rather than a lossy ``max()`` aggregate that misrepresents a crate type
        whose lines mix prices / rates.
        """
        filter_q = CrateOrderContentService._period_filter(
            year, delivery_week, day_number, reseller
        )

        rows = CrateOrderContent.objects.filter(filter_q).select_related("crate_type")

        pricing_date = week_day_to_date(year, delivery_week, day_number)

        def _resolve_tax_rate(crate_type):
            return effective_crate_tax_rate(crate_type, pricing_date)

        summary = summarize_crate_items(rows, resolve_tax_rate=_resolve_tax_rate)
        # Hide fully-returned / net-zero crate groups (mirrors the prior
        # total-amount > 0 filter).
        return [row for row in summary if row["amount"] and row["amount"] > 0]

    @staticmethod
    @transaction.atomic
    def create_crate_order_content(
        crate_type_id,
        amount: Decimal,
        year: int,
        delivery_week: int,
        day_number: int,
        reseller,
        price_per_unit: Decimal | None = None,
        rabatt: int | None = None,
        note: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a new crate order content record, finding or creating the Order."""
        order, _created = Order.objects.get_or_create(
            reseller_id=reseller,
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            defaults={"created_by": kwargs.pop("created_by", None)},
        )
        # Lock the order row to serialize concurrent crate additions
        order = Order.objects.select_for_update().get(pk=order.pk)

        pricing_date = week_day_to_date(year, delivery_week, day_number)
        try:
            crate = Crate.objects.get(id=crate_type_id)
        except Crate.DoesNotExist as exc:
            raise CrateNotFound(
                f"Crate {crate_type_id!r} does not exist",
                details={"id": str(crate_type_id)},
            ) from exc
        pricing = crate.get_pricing_on_date(pricing_date)
        # BL-7: distinguish "not provided" (None) from an explicit 0 — a money
        # field must not treat a legitimate zero-deposit crate as unset. Mirrors
        # the `is None` tax_rate check below; `not Decimal("0")` is True and would
        # silently overwrite an intentional 0 with the dated pricing.
        if price_per_unit is None and pricing:
            price_per_unit = pricing.price

        # tax_rate is NOT NULL — resolve from crate pricing or tenant default
        # when the caller didn't pass an explicit value.
        if "tax_rate" not in kwargs or kwargs.get("tax_rate") is None:
            kwargs["tax_rate"] = effective_crate_tax_rate(crate, pricing_date)

        crate_order_content = CrateOrderContent.objects.create(
            order=order,
            crate_type_id=crate_type_id,
            amount=amount,
            price_per_unit=price_per_unit,
            rabatt=rabatt,
            note=note,
            **kwargs,
        )

        result = CrateOrderContentService._serialize(crate_order_content)
        result["order_id"] = order.id
        # Mirror the OrderContent path (_serialize_order_metadata) and the
        # refresh metadata block: the frontend formats the order number as
        # "{prefix}-{display_number}" and seeds those two fields identically
        # from the create response and from a reload. A crates-first save must
        # therefore carry display_number (e.g. "39v") + prefix — not the raw
        # number (which showed "39" instead of "39v") and not a missing prefix
        # (which rendered "undefined-39" until the next reload).
        result["order_number"] = order.display_number
        result["order_number_prefix"] = order.prefix
        return result

    @staticmethod
    @transaction.atomic
    def update_crate_order_content_by_crate_type(
        crate_type_id: str,
        year: int,
        delivery_week: int,
        day_number: int,
        reseller: str,
        update_data: dict,
    ) -> dict[str, Any]:
        """Update all CrateOrderContent records matching crate_type + order context."""
        filter_q = CrateOrderContentService._period_filter(
            year, delivery_week, day_number, reseller
        )
        crate_order_contents = CrateOrderContent.objects.filter(
            filter_q, crate_type_id=crate_type_id
        )

        if not crate_order_contents.exists():
            raise CrateOrderContent.DoesNotExist(
                "No CrateOrderContent found for the given crate type and period."
            )

        allowed_fields = {"amount", "price_per_unit", "rabatt", "note"}
        for crate_order_content in crate_order_contents:
            for field in allowed_fields:
                if field in update_data:
                    setattr(crate_order_content, field, update_data[field])
            crate_order_content.save()

        # Return single record matching the updated crate type
        summary = CrateOrderContentService.get_crates_summary_for_period(
            year, delivery_week, day_number, reseller
        )
        return next(
            (item for item in summary if str(item["crate_type"]) == str(crate_type_id)),
            summary[0] if summary else {},
        )

    @staticmethod
    @transaction.atomic
    def delete_crate_order_content_by_crate_type(
        crate_type_id: str,
        year: int | None = None,
        delivery_week: int | None = None,
        day_number: int | None = None,
        reseller: str | None = None,
        order_id: str | None = None,
        scope: Callable[[QuerySet], QuerySet] | None = None,
    ) -> bool:
        """Delete all CrateOrderContent records for a crate type within an order context.

        ``scope`` is an optional queryset transform the caller supplies to bind
        the otherwise reseller-blind ``order_id`` branch to an authorization
        boundary — e.g. ``scope_to_reseller(qs, request, path="order__reseller")``
        — so an ``order_id``-keyed delete can never reach another reseller's
        content (cross-reseller IDOR guard). It is applied ONLY to the
        ``order_id`` branch; the period branch is already reseller-scoped by
        ``_period_filter`` (which covers both the ``order`` and
        ``order_content`` linkage paths) so re-scoping it would wrongly skip
        ``order_content``-linked rows.
        """
        if order_id:
            qs = CrateOrderContent.objects.filter(
                crate_type_id=crate_type_id, order_id=order_id
            )
            if scope is not None:
                qs = scope(qs)
        elif year and delivery_week and day_number is not None and reseller:
            filter_q = CrateOrderContentService._period_filter(
                year, delivery_week, day_number, reseller
            )
            qs = CrateOrderContent.objects.filter(filter_q, crate_type_id=crate_type_id)
        else:
            return False

        deleted_count, _ = qs.delete()
        return deleted_count > 0
