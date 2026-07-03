from __future__ import annotations

import math
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..constants import (
    get_default_tax_rate_articles,
    get_default_tax_rate_crates,
)
from ..errors import (
    FinalizedError,
    NotEnoughStock,
    OrderContentNotFound,
)
from ..models import (
    CrateContentInvoiceReseller,
    CrateOrderContent,
    Forecast,
    InvoiceResellerContent,
    MovementShareArticle,
    Offer,
    Order,
    OrderContent,
    OrdersDeliveryDay,
    Storage,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
)
from ..utils.iso_week_utils import date_from_order
from ..utils.tax_rate_utils import resolve_article_tax_rate, resolve_crate_tax_rate
from .snapshot_service import SnapshotService


class OrderContentService:
    """Service for creating, updating, and deleting order contents."""

    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _get_offer_name(offer: Offer | None) -> str | None:
        if not offer:
            return None
        if offer.sort:
            return f"{offer.share_article.name} - {offer.sort}"
        return offer.share_article.name

    _get_tax_rate = staticmethod(resolve_article_tax_rate)

    @staticmethod
    def _amount_per_pu_or_one(offer: Offer | None) -> Decimal | int:
        if offer and offer.amount_per_pu:
            return offer.amount_per_pu
        return 1

    @staticmethod
    def _crate_count(amount: Decimal, pu_divisor: Decimal | int) -> int:
        """Whole crates needed to hold ``amount`` at ``pu_divisor`` per crate.

        Rounds UP: a partial crate still needs a physical crate (and is billed
        as a returnable-deposit unit). ``CrateOrderContent.amount`` is an
        IntegerField, so the previous bare ``amount / pu_divisor`` assignment
        relied on implicit ``int()`` truncation, silently dropping the partial
        crate (2.1 → 2). Inputs are already ``Decimal`` (model fields) so there
        is no float drift.
        """
        return math.ceil(Decimal(amount) / Decimal(pu_divisor))

    @staticmethod
    def _serialize_order_content(order_content: OrderContent) -> dict[str, Any]:
        """Serialize an OrderContent into a flat dict for API responses."""
        offer = order_content.offer
        return {
            "id": order_content.id,
            # Explicit flag so the frontend never has to infer "is this a
            # real row or a placeholder?" from the shape of other fields.
            # See _serialize_unused_offer for the placeholder counterpart.
            "is_placeholder": False,
            "order_id": order_content.order_id,
            "order_number": order_content.order.display_number,
            "order_number_prefix": order_content.order.prefix,
            "order_is_finalized": order_content.order.is_finalized,
            "order_note": order_content.order.note or "",
            "harvesting_day": order_content.order.harvesting_day,
            "packing_day": order_content.order.packing_day,
            "washing_day": order_content.order.washing_day,
            "last_possible_ordering_day": order_content.order.last_possible_ordering_day,
            "offer": offer.id if offer else None,
            "offer_name": OrderContentService._get_offer_name(offer),
            "offer_available_amount": offer.amount if offer else None,
            "amount_per_pu": offer.amount_per_pu if offer else None,
            "offer_share_article_name": (offer.share_article.name if offer else None),
            "share_article": (
                order_content.share_article_id if order_content.share_article else None
            ),
            "share_article_name": (
                order_content.share_article.name
                if order_content.share_article
                else None
            ),
            "amount": order_content.amount,
            "ordered_amount": (
                order_content.amount / OrderContentService._amount_per_pu_or_one(offer)
            ),
            "size": order_content.size,
            "sort": order_content.sort,
            "note": order_content.note,
            "unit": order_content.unit,
            "price_per_unit": order_content.price_per_unit,
            "price_1": offer.price_1 if offer else None,
            "price_2": offer.price_2 if offer else None,
            "price_3": offer.price_3 if offer else None,
            "rabatt": order_content.rabatt,
            "tax_rate": (
                order_content.tax_rate
                if order_content.tax_rate is not None
                else resolve_article_tax_rate(
                    order_content, date_from_order(order_content.order)
                )
            ),
            "washing": order_content.washing,
            "cleaning": order_content.cleaning,
            "comes_from_long_term_storage": order_content.comes_from_long_term_storage,
        }

    @staticmethod
    def _serialize_unused_offer(offer: Offer) -> dict[str, Any]:
        """Serialize an Offer that has no matching OrderContent yet.

        The list endpoint mixes these placeholder rows with real OrderContent
        rows so the table can render every available offer in one shot. To
        keep the two row types unambiguous downstream:
          - `is_placeholder = True` is the authoritative flag (the frontend
            routes a save on a placeholder row to CREATE, not UPDATE).
          - `id` carries the offer's id so the row has a unique React key in
            the table; the placeholder flag is what disambiguates it from a
            real OrderContent id, NOT the id field itself.
        """
        return {
            "id": offer.id,
            "is_placeholder": True,
            "order_id": None,
            "order_number": None,
            "order_number_prefix": None,
            "order_is_finalized": False,
            "harvesting_day": None,
            "packing_day": None,
            "washing_day": None,
            "last_possible_ordering_day": None,
            "delivery_note_id": None,
            "delivery_note_number": None,
            "delivery_note_prefix": None,
            "delivery_note_is_finalized": False,
            "invoice_id": None,
            "invoice_number": None,
            "invoice_prefix": None,
            "has_invoice": False,
            "has_finalized_invoice": False,
            "offer": offer.id,
            "offer_name": OrderContentService._get_offer_name(offer),
            "offer_available_amount": offer.amount,
            "amount_per_pu": offer.amount_per_pu,
            "offer_share_article_name": offer.share_article.name,
            "share_article": None,
            "share_article_name": None,
            "amount": None,
            "ordered_amount": None,
            # Carry size/sort/unit through from the offer so a CREATE built
            # from this placeholder row passes the DRF serializer's required-
            # field checks (the service-layer fallback in
            # `create_order_with_content_and_crates` runs AFTER serializer
            # validation, so empty values here would surface as a 400).
            "size": offer.size,
            "sort": offer.sort,
            "note": None,
            "unit": offer.unit,
            "price_per_unit": None,
            "price_1": offer.price_1,
            "price_2": offer.price_2,
            "price_3": offer.price_3,
            "rabatt": None,
            "tax_rate": resolve_article_tax_rate(offer, timezone.now().date()),
            "washing": offer.washing,
            "cleaning": offer.cleaning,
            "comes_from_long_term_storage": offer.comes_from_long_term_storage,
        }

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    @staticmethod
    def _serialize_order_metadata(order, invoice_content) -> dict[str, Any]:
        """Top-level order identity + delivery-note / invoice state for a period.

        Surfaced independently of OrderContent rows so the Orders page can
        render and progress a CRATES-ONLY order (an order with crates but no
        share-article content). Uses the same ``order_*`` / ``delivery_note_*``
        / ``invoice_*`` keys the per-row serialization emits, so the frontend
        reads it identically.
        """
        delivery_note = getattr(order, "delivery_note", None)
        return {
            "order_id": order.id,
            "order_number": order.display_number,
            "order_number_prefix": order.prefix,
            "order_is_finalized": order.is_finalized,
            "order_note": order.note or "",
            "harvesting_day": order.harvesting_day,
            "packing_day": order.packing_day,
            "washing_day": order.washing_day,
            "delivery_note_id": delivery_note.id if delivery_note else None,
            "delivery_note_number": (
                delivery_note.display_number if delivery_note else None
            ),
            "delivery_note_prefix": delivery_note.prefix if delivery_note else None,
            "delivery_note_is_finalized": (
                delivery_note.is_finalized if delivery_note else False
            ),
            "invoice_id": invoice_content.invoice.id if invoice_content else None,
            "invoice_number": (
                invoice_content.invoice.display_number if invoice_content else None
            ),
            "invoice_prefix": (
                invoice_content.invoice.prefix if invoice_content else None
            ),
            "has_invoice": invoice_content is not None,
            "has_finalized_invoice": (
                invoice_content.invoice.is_finalized if invoice_content else False
            ),
        }

    @staticmethod
    def get_offers_and_order_content(
        reseller,
        year: int,
        delivery_week: int,
        day_number: int,
    ) -> dict[str, Any]:
        """Return merged list of order contents and unused offers for a reseller/week/day_number."""
        offers = (
            Offer.objects.filter(
                year=year,
                delivery_week=delivery_week,
                offer_group__reseller=reseller,
                is_finalized=True,
            )
            .select_related("share_article")
            .order_by("share_article__name")
        )

        order_contents = OrderContent.objects.filter(
            order__reseller=reseller,
            order__year=year,
            order__delivery_week=delivery_week,
            order__day_number=day_number,
        ).select_related(
            "offer",
            "offer__share_article",
            "share_article",
            "order",
            "order__delivery_note",
        )

        # Look up the Order for this period directly — it exists independently
        # of OrderContent rows (a CRATES-ONLY order has zero of them), so its
        # identity is surfaced at the top level below rather than only per row.
        order = (
            Order.objects.filter(
                reseller=reseller,
                year=year,
                delivery_week=delivery_week,
                day_number=day_number,
            )
            .select_related("delivery_note")
            .first()
        )

        # Look up OrdersDeliveryDay defaults for comparison in frontend
        odd = OrdersDeliveryDay.objects.filter(day_number=day_number).first()
        odd_defaults = {
            "default_harvesting_day": odd.default_harvesting_day if odd else None,
            "default_packing_day": odd.default_packing_day if odd else None,
            "default_washing_day": odd.default_washing_day if odd else None,
            "default_cleaning_day": odd.default_cleaning_day if odd else None,
            "default_last_possible_ordering_day": (
                odd.default_last_possible_ordering_day if odd else None
            ),
            "default_last_possible_ordering_time": (
                odd.default_last_possible_ordering_time.isoformat()
                if odd and odd.default_last_possible_ordering_time
                else None
            ),
        }

        used_offer_ids = set(order_contents.values_list("offer_id", flat=True))
        unused_offers = offers.exclude(id__in=used_offer_ids)

        # Batch-fetch invoice data for all delivery notes to avoid N+1
        delivery_note_ids = [
            order_content.order.delivery_note.id
            for order_content in order_contents
            if getattr(order_content.order, "delivery_note", None)
        ]
        # Include the order's own delivery note so a crates-only order (no
        # order_contents to harvest it from) still resolves its invoice below.
        if order is not None and getattr(order, "delivery_note", None):
            delivery_note_ids.append(order.delivery_note.id)
        invoice_by_delivery_note: dict[
            int, InvoiceResellerContent | CrateContentInvoiceReseller
        ] = {}
        if delivery_note_ids:
            invoice_contents = (
                InvoiceResellerContent.objects.filter(
                    delivery_note_contents__delivery_note_id__in=delivery_note_ids
                )
                .select_related("invoice")
                .distinct()
            )
            for invoice_content in invoice_contents:
                for (
                    delivery_note_id
                ) in invoice_content.delivery_note_contents.values_list(
                    "delivery_note_id", flat=True
                ):
                    if delivery_note_id in delivery_note_ids:
                        invoice_by_delivery_note[delivery_note_id] = invoice_content
            # Crate-only delivery notes link to their invoice only via the crate
            # provenance M2M. Both content types expose ``.invoice`` — all the
            # downstream serialization reads — so a crate content is a drop-in.
            crate_invoice_contents = (
                CrateContentInvoiceReseller.objects.filter(
                    crate_delivery_note_contents__delivery_note_id__in=delivery_note_ids
                )
                .select_related("invoice")
                .distinct()
            )
            for crate_invoice_content in crate_invoice_contents:
                for (
                    delivery_note_id
                ) in crate_invoice_content.crate_delivery_note_contents.values_list(
                    "delivery_note_id", flat=True
                ):
                    if (
                        delivery_note_id in delivery_note_ids
                        and delivery_note_id not in invoice_by_delivery_note
                    ):
                        invoice_by_delivery_note[delivery_note_id] = (
                            crate_invoice_content
                        )

        result: list[dict[str, Any]] = []

        for order_content in order_contents:
            delivery_note = getattr(order_content.order, "delivery_note", None)

            invoice_content = (
                invoice_by_delivery_note.get(delivery_note.id)
                if delivery_note
                else None
            )

            item = OrderContentService._serialize_order_content(order_content)
            # Augment with delivery note & invoice fields
            item.update(
                {
                    "delivery_note_id": delivery_note.id if delivery_note else None,
                    "delivery_note_number": (
                        delivery_note.display_number if delivery_note else None
                    ),
                    "delivery_note_prefix": (
                        delivery_note.prefix if delivery_note else None
                    ),
                    "delivery_note_is_finalized": (
                        delivery_note.is_finalized if delivery_note else False
                    ),
                    "invoice_id": (
                        invoice_content.invoice.id if invoice_content else None
                    ),
                    "invoice_number": (
                        invoice_content.invoice.display_number
                        if invoice_content
                        else None
                    ),
                    "invoice_prefix": (
                        invoice_content.invoice.prefix if invoice_content else None
                    ),
                    "has_invoice": invoice_content is not None,
                    "has_finalized_invoice": (
                        invoice_content.invoice.is_finalized
                        if invoice_content
                        else False
                    ),
                }
            )
            result.append(item)

        for offer in unused_offers:
            result.append(OrderContentService._serialize_unused_offer(offer))

        order_block = None
        if order is not None:
            order_delivery_note = getattr(order, "delivery_note", None)
            order_invoice_content = (
                invoice_by_delivery_note.get(order_delivery_note.id)
                if order_delivery_note
                else None
            )
            order_block = OrderContentService._serialize_order_metadata(
                order, order_invoice_content
            )

        return {
            "items": result,
            "order": order_block,
            "orders_delivery_day_defaults": odd_defaults,
        }

    @staticmethod
    @transaction.atomic
    def create_order_with_content_and_crates(
        reseller,
        year: int,
        delivery_week: int,
        day_number: int,
        offer: Offer | None = None,
        share_article=None,
        amount: Decimal | None = None,
        size: str | None = None,
        unit: str | None = None,
        price_per_unit: Decimal | None = None,
        rabatt: int | None = None,
        sort: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        # Default fields from offer when not explicitly provided
        if offer:
            if unit is None:
                unit = offer.unit
            if size is None:
                size = offer.size
            if sort is None:
                sort = offer.sort

        pu_divisor = OrderContentService._amount_per_pu_or_one(offer)

        # Lock the offer row to prevent race conditions on availability
        if offer:
            offer = Offer.objects.select_for_update().get(pk=offer.pk)

        if offer and not offer.check_availability(amount / pu_divisor):
            raise NotEnoughStock(
                f"Not enough stock available. Available: {offer.amount}, "
                f"Requested: {amount}",
                code="order_content.insufficient_stock",
                details={
                    "offer_id": str(offer.id),
                    "available": float(offer.amount or 0),
                    "requested": float(amount),
                },
            )

        order, created = Order.objects.get_or_create(
            reseller=reseller,
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            defaults={"created_by": kwargs.pop("created_by", None)},
        )

        # Populate day_number fields from kwargs or OrdersDeliveryDay defaults
        day_fields = [
            "harvesting_day",
            "packing_day",
            "washing_day",
            "cleaning_day",
            "last_possible_ordering_day",
        ]
        if created:
            odd = OrdersDeliveryDay.objects.filter(day_number=day_number).first()
            for field in day_fields:
                value = kwargs.pop(field, None)
                if value is None and odd:
                    # OrdersDeliveryDay carries a ``default_<field>``
                    # column for every entry in ``day_fields``; no
                    # safety default — a typo in ``day_fields`` should
                    # crash here rather than silently fall through
                    # with ``None``.
                    value = getattr(odd, f"default_{field}")
                setattr(order, field, value)
            order.save()
        else:
            updated = False
            for field in day_fields:
                value = kwargs.pop(field, None)
                if value is not None and getattr(order, field) != value:
                    setattr(order, field, value)
                    updated = True
            if updated:
                order.save()

        # tax_rate is NOT NULL on OrderableItem — resolve from the canonical
        # chain (offer/share_article pricing → tenant default → hardcoded)
        # when the caller didn't pass an explicit value.
        tax_rate = kwargs.get("tax_rate")
        if tax_rate is None:
            tax_rate = resolve_article_tax_rate(
                SimpleNamespace(offer=offer, share_article=share_article),
                date_from_order(order),
                default=get_default_tax_rate_articles(),
            )

        order_content = OrderContent.objects.create(
            order=order,
            offer=offer,
            share_article=share_article,
            amount=amount,
            size=size,
            unit=unit,
            price_per_unit=price_per_unit,
            rabatt=rabatt,
            sort=sort,
            tax_rate=tax_rate,
            washing=kwargs.get("washing", offer.washing if offer else False),
            cleaning=kwargs.get("cleaning", offer.cleaning if offer else False),
            comes_from_long_term_storage=kwargs.get(
                "comes_from_long_term_storage",
                offer.comes_from_long_term_storage if offer else False,
            ),
        )

        if offer is not None:
            crate_type = offer.used_crate
            if crate_type is not None:
                pricing_date = date_from_order(order)
                pricing = crate_type.get_pricing_on_date(pricing_date)
                CrateOrderContent.objects.filter(order_content=order_content).delete()
                # BL-6: only spawn a crate row for a non-zero line — mirrors the
                # update path's `if new_amount > 0` guard so create + update leave
                # identical crate artefacts (a zero-amount line gets no dead
                # amount-0 crate row + no stray empty VAT bucket downstream).
                if amount and amount > 0:
                    # Same canonical chain as above:
                    # crate pricing → tenant default → hardcoded constant.
                    crate_tax_rate = resolve_crate_tax_rate(
                        crate_type,
                        pricing_date,
                        default=get_default_tax_rate_crates(),
                    )
                    CrateOrderContent.objects.create(
                        order_content=order_content,
                        crate_type=crate_type,
                        amount=OrderContentService._crate_count(amount, pu_divisor),
                        price_per_unit=pricing.price if pricing else None,
                        tax_rate=crate_tax_rate,
                    )
            offer.update_available_amount(amount / pu_divisor)

        # Single canonical entry point — mirrors the ShareContent side
        # (``recompute_shares``). Composes wipe + rebuild via the
        # low-level ``create_all_theoretical_objects`` + ``create_movements``
        # primitives. Deferred import to avoid a circular dependency
        # (recompute → order_content_service).
        from .recompute import recompute_order_contents

        recompute_order_contents([order_content.id])

        return OrderContentService._serialize_order_content(order_content)

    @staticmethod
    @transaction.atomic
    def update_order_content(
        order_content_id: str,
        amount: Decimal,
        **kwargs,
    ) -> dict[str, Any]:
        """Update order content and adjust offer availability.
        If the ID is actually an offer (unused-offer stub), create a new order content.
        """
        try:
            order_content = OrderContent.objects.get(id=order_content_id)
        except OrderContent.DoesNotExist:
            # The ID may be an offer ID from an unused-offer stub — create instead
            try:
                offer = Offer.objects.get(id=order_content_id)
                kwargs.pop("offer", None)
                return OrderContentService.create_order_with_content_and_crates(
                    offer=offer, amount=amount, **kwargs
                )
            except Offer.DoesNotExist as exc:
                raise OrderContentNotFound(
                    f"Order content {order_content_id} not found",
                    details={"order_content_id": order_content_id},
                ) from exc

        if order_content.is_finalized:
            raise FinalizedError(
                "Cannot update finalized order content",
                code="order_content.finalized",
            )

        offer = order_content.offer

        if offer is not None:
            # Lock the offer row to prevent race conditions on availability
            offer = Offer.objects.select_for_update().get(pk=offer.pk)
            old_amount = order_content.amount or Decimal("0")
            new_amount = amount if amount is not None else Decimal("0")
            amount_difference = new_amount - old_amount
            pu_divisor = OrderContentService._amount_per_pu_or_one(offer)

            if amount_difference > 0 and not offer.check_availability(
                amount_difference / pu_divisor
            ):
                raise NotEnoughStock(
                    f"Not enough additional stock available. Available: {offer.amount}, "
                    f"Additional needed: {amount_difference}",
                    code="order_content.insufficient_stock",
                    details={
                        "offer_id": str(offer.id),
                        "available": float(offer.amount or 0),
                        "additional_needed": float(amount_difference),
                    },
                )

            offer.amount -= amount_difference / pu_divisor
            offer.save(update_fields=["amount"])
            # Re-point the cached relation to the freshly-locked offer so the
            # serialized response carries the NEW available amount — the row
            # was loaded with a stale ``order_content.offer`` (its ``amount``
            # predates this update), which made the frontend show an outdated
            # ``offer_available_amount`` until the next refetch.
            order_content.offer = offer

            crate_type = offer.used_crate
            if crate_type is not None:
                pricing_date = date_from_order(order_content.order)
                pricing = crate_type.get_pricing_on_date(pricing_date)
                CrateOrderContent.objects.filter(order_content=order_content).delete()
                if new_amount > 0:
                    # Mirror the create path: `tax_rate` is NOT NULL on the
                    # CrateOrderContent table, so resolve it via the same
                    # crate pricing → tenant default → hardcoded constant
                    # chain used in create_order_with_content_and_crates.
                    crate_tax_rate = resolve_crate_tax_rate(
                        crate_type,
                        pricing_date,
                        default=get_default_tax_rate_crates(),
                    )
                    CrateOrderContent.objects.create(
                        order_content=order_content,
                        crate_type=crate_type,
                        amount=OrderContentService._crate_count(new_amount, pu_divisor),
                        price_per_unit=pricing.price if pricing else None,
                        tax_rate=crate_tax_rate,
                    )

        order_content.amount = amount if amount is not None else Decimal("0")
        for key, value in kwargs.items():
            setattr(order_content, key, value)
        order_content.save()

        # Same canonical entry as the create path. The helper wipes the
        # existing theoreticals + ORDERCONTENT movements before
        # rebuilding, so the per-OC ``_recreate_*`` helpers we used to
        # call inline are now superseded.
        from .recompute import recompute_order_contents

        recompute_order_contents([order_content.id])

        return OrderContentService._serialize_order_content(order_content)

    @staticmethod
    @transaction.atomic
    def delete_order_content(order_content_id: str) -> dict[str, bool]:
        """Delete order content, restore offer availability, and delete order if empty."""
        try:
            order_content = OrderContent.objects.get(id=order_content_id)
        except OrderContent.DoesNotExist as exc:
            raise OrderContentNotFound(
                "Order content not found",
                details={"order_content_id": order_content_id},
            ) from exc

        # Capture movements before cascade-delete so we can fix future
        # inventories. BOTH halves: the ORDERCONTENT rows AND the theoretical
        # HARVEST/PURCHASE/WASH/CLEAN movements (order_content=NULL, linked via
        # their Theoretical* parent). Deleting the content cascade-kills the
        # theoretical rows + their movements, so a dimension whose theoreticals
        # vanish would otherwise keep a stale actual correction (entity total ≠
        # counted) — mirror recompute_for_order_contents and re-derive below.
        from django.db.models import Q

        from .theoretical_objects import recalculate_actual_corrections

        affected_movements = list(
            MovementShareArticle.objects.filter(
                Q(order_content=order_content)
                | Q(theoretical_harvest__order_content=order_content)
                | Q(theoretical_purchase__order_content=order_content)
                | Q(theoretical_wash_amount__order_content=order_content)
                | Q(theoretical_clean_amount__order_content=order_content)
            )
        )

        offer = order_content.offer
        amount_to_restore = order_content.amount
        order = order_content.order

        if offer and offer.amount is not None:
            # Lock the offer row to prevent race conditions on availability
            offer = Offer.objects.select_for_update().get(pk=offer.pk)
            # ``Offer.amount`` is in PU. The create/update paths debit it by
            # ``amount / pu_divisor``; restore must use the SAME unit, else
            # stock drifts upward by ``amount_per_pu`` on every delete.
            pu_divisor = OrderContentService._amount_per_pu_or_one(offer)
            offer.amount += (amount_to_restore or Decimal("0")) / pu_divisor
            offer.save(update_fields=["amount"])

        order_pk = order.pk
        order_content.delete()

        # Cascade future inventories for all affected entities + re-derive the
        # actual harvest/purchase corrections for the now-removed theoretical
        # dimensions (their theoretical_sum just dropped).
        if affected_movements:
            SnapshotService.cascade_for_movements(affected_movements)
            recalculate_actual_corrections(affected_movements)

        # ``OrderContent.delete()`` (model-level) already auto-deletes the
        # order when it was the last child — see TestEmptyParentAutoCleanup.
        # Don't touch the stale ``order`` reference; just check whether the
        # row is still in the DB.
        if not Order.objects.filter(pk=order_pk).exists():
            return {"order_deleted": True}

        # Defensive: if the model didn't auto-delete (e.g. a CrateOrderContent
        # remains), do nothing — the next deletion will trigger the cascade.
        return {"order_deleted": False}

    @transaction.atomic
    def recompute_for_order_contents(
        self, order_contents: list[OrderContent] | Any
    ) -> list[Any]:
        """Wipe + rebuild theoreticals and ORDERCONTENT movements for the
        given OrderContents.

        Idempotent — safe to call any time the inputs change. Locks the
        OrderContent rows for the duration of the transaction to prevent
        concurrent rebuilds from racing.

        Returns the list of touched OrderContent ids.
        """
        order_content_ids = [
            order_content.id if hasattr(order_content, "id") else order_content
            for order_content in order_contents
        ]
        if not order_content_ids:
            return []

        # Serialize concurrent recomputes for the same OrderContent. Lock in
        # deterministic (id) order so overlapping recomputes serialise without
        # AB/BA-deadlocking (OrderContent declares no Meta.ordering).
        list(
            OrderContent.objects.select_for_update()
            .filter(id__in=order_content_ids)
            .order_by("id")
        )

        loaded_order_contents = list(
            OrderContent.objects.filter(id__in=order_content_ids).select_related(
                "order",
                "share_article",
                "offer",
            )
        )
        if not loaded_order_contents:
            return []

        # Capture the OLD movements BEFORE the wipe so the rebuild can
        # re-cascade every storage an amount-down / stock-driven relocation /
        # packing-day shift strands. BOTH halves are captured: the ORDERCONTENT
        # rows AND the theoretical HARVEST/PURCHASE/WASH/CLEAN movements — the
        # latter carry order_content=NULL (their source FK is ``theoretical_*``),
        # so they are reached via their Theoretical* parent's order_content link.
        # The rebuild's own cascades only cover the NEW storages.
        from django.db.models import Q

        from .theoretical_objects import recalculate_actual_corrections

        old_movements = list(
            MovementShareArticle.objects.filter(
                Q(order_content__in=loaded_order_contents)
                | Q(theoretical_harvest__order_content__in=loaded_order_contents)
                | Q(theoretical_purchase__order_content__in=loaded_order_contents)
                | Q(theoretical_wash_amount__order_content__in=loaded_order_contents)
                | Q(theoretical_clean_amount__order_content__in=loaded_order_contents)
            )
        )

        TheoreticalHarvest.objects.filter(
            order_content__in=loaded_order_contents
        ).delete()
        TheoreticalPurchase.objects.filter(
            order_content__in=loaded_order_contents
        ).delete()
        TheoreticalWashAmount.objects.filter(
            order_content__in=loaded_order_contents
        ).delete()
        TheoreticalCleanAmount.objects.filter(
            order_content__in=loaded_order_contents
        ).delete()

        MovementShareArticle.objects.filter(
            order_content__in=loaded_order_contents,
            movement_type="ORDERCONTENT",
        ).delete()

        # Single-pass cascade (mirrors ShareContentService.recompute_for_shares):
        # collect every movement the rebuild touches and cascade ONCE at the
        # end, so the per-entity ``current_balance:*`` advisory locks are
        # acquired in one canonically-sorted pass instead of three separate
        # passes (theoretical → new → old) whose concatenation could AB/BA-
        # deadlock against a concurrent overlapping acquirer.
        deferred_movements: list[MovementShareArticle] = []
        OrderContentService.create_all_theoretical_objects(
            loaded_order_contents, collect_movements=deferred_movements
        )
        OrderContentService.create_movements(
            loaded_order_contents, collect_movements=deferred_movements
        )

        if old_movements:
            deferred_movements.extend(old_movements)
            # Re-derive actual harvest/purchase corrections for the OLD
            # theoretical dimensions too — create_theoretical_objects only
            # recalcs the NEW theoretical movements' dimensions, so a dimension
            # whose theoreticals dropped to zero / relocated would keep a stale
            # correction (entity total ≠ counted). (ORDERCONTENT keys match no
            # actual correction, so they are harmless no-ops here.)
            recalculate_actual_corrections(
                old_movements, collect_movements=deferred_movements
            )

        if deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

        return [order_content.id for order_content in loaded_order_contents]

    @staticmethod
    @transaction.atomic
    def create_all_theoretical_objects(
        order_contents: list[OrderContent],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> dict[str, list]:
        """Create all theoretical objects in a single optimized operation.

        ``collect_movements`` defers the snapshot cascade to the caller —
        see ``theoretical_objects.create_theoretical_objects``.
        """
        from .theoretical_objects import (
            TheoreticalSourceData,
            build_theoretical_objects_from_rows,
        )

        # Ensure related objects are prefetched to avoid N+1
        order_content_ids = [
            order_content.id for order_content in order_contents if order_content.id
        ]
        if order_content_ids:
            order_contents = list(
                OrderContent.objects.filter(id__in=order_content_ids).select_related(
                    "order", "offer", "offer__share_article", "share_article"
                )
            )

        # Batch the per-line Forecast lookup (was one query per order content).
        # The per-line filter omitted ``unit`` and used ``.first()`` (which, with
        # no Meta.ordering on Forecast, orders by pk), so index by the
        # (year, week, share_article, size) tuple keeping the lowest-pk row —
        # exactly what ``.filter(...).first()`` returned. ``size`` is only a
        # dict key here, so NULL sizes match cleanly (no ``size__in`` NULL drop).
        forecast_article_ids: set = set()
        forecast_years: set = set()
        forecast_weeks: set = set()
        for order_content in order_contents:
            share_article = order_content.resolve_share_article()
            if not share_article:
                continue
            forecast_article_ids.add(share_article.id)
            forecast_years.add(order_content.order.year)
            forecast_weeks.add(order_content.order.delivery_week)

        forecast_by_key: dict = {}
        if forecast_article_ids:
            for forecast in Forecast.objects.filter(
                share_article_id__in=forecast_article_ids,
                year__in=forecast_years,
                delivery_week__in=forecast_weeks,
            ).order_by("pk"):
                forecast_by_key.setdefault(
                    (
                        forecast.year,
                        forecast.delivery_week,
                        forecast.share_article_id,
                        forecast.size,
                    ),
                    forecast,
                )

        def build_source(order_content, short_term, long_term):
            share_article = order_content.resolve_share_article()
            if not share_article:
                return None

            existing_forecast = forecast_by_key.get(
                (
                    order_content.order.year,
                    order_content.order.delivery_week,
                    share_article.id,
                    order_content.size,
                )
            )

            delivery_day = order_content.order.day_number
            harvesting_day = (
                order_content.order.harvesting_day
                if order_content.order.harvesting_day is not None
                else delivery_day
            )
            washing_day = (
                order_content.order.washing_day
                if order_content.order.washing_day is not None
                else harvesting_day
            )
            cleaning_day = (
                order_content.order.cleaning_day
                if order_content.order.cleaning_day is not None
                else washing_day
            )

            storage = Storage.select_harvest(
                short_term=short_term,
                long_term=long_term,
                comes_from_long_term=order_content.comes_from_long_term_storage,
            )

            return TheoreticalSourceData(
                year=order_content.order.year,
                delivery_week=order_content.order.delivery_week,
                delivery_day=delivery_day,
                harvesting_day=harvesting_day,
                washing_day=washing_day,
                cleaning_day=cleaning_day,
                share_article=share_article,
                amount=order_content.amount,
                unit=order_content.unit,
                size=order_content.size,
                note=order_content.note,
                washing=order_content.washing,
                cleaning=order_content.cleaning,
                forecast=existing_forecast,
                is_purchased=share_article.is_purchased,
                order_content=order_content,
                storage=storage,
                comes_from_long_term_storage=order_content.comes_from_long_term_storage,
            )

        return build_theoretical_objects_from_rows(
            order_contents, build_source, collect_movements=collect_movements
        )

    @staticmethod
    @transaction.atomic
    def create_movements(
        order_contents: list[OrderContent],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
    ) -> list[MovementShareArticle]:
        """Create MovementShareArticle objects for order contents with storage allocation.

        ``collect_movements`` defers the snapshot cascade to the caller —
        see ``movements.create_movements``.
        """
        from .movements import MovementSourceData, create_movements

        sources: list[MovementSourceData] = []

        for order_content in order_contents:
            share_article = order_content.resolve_share_article()
            if not share_article:
                continue
            if order_content.amount is None or order_content.amount == 0:
                continue

            packing_day = (
                order_content.order.packing_day
                if order_content.order.packing_day is not None
                else order_content.order.day_number
            )

            sources.append(
                MovementSourceData(
                    year=order_content.order.year,
                    delivery_week=order_content.order.delivery_week,
                    delivery_day=order_content.order.day_number,
                    packing_day=packing_day,
                    share_article=share_article,
                    unit=order_content.unit,
                    size=order_content.size,
                    amount=abs(Decimal(str(order_content.amount))),
                    movement_type="ORDERCONTENT",
                    order_content=order_content,
                )
            )

        return create_movements(sources, collect_movements=collect_movements)
