from __future__ import annotations

import logging
import smtplib
from collections import defaultdict
from decimal import Decimal

from django.db import models, transaction
from django.db.models import OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from isoweek import Week

from ..models import (
    Forecast,
    ForecastOfferGroup,
    Offer,
    OfferGroup,
    OfferSending,
    OrderContent,
    Reseller,
    Share,
    ShareArticle,
    ShareContent,
)
from .bulk_email_job import create_send_record_idempotent, emit_progress
from .share_demand_service import ShareDemandService

logger = logging.getLogger(__name__)

# Maps unit type to the PU conversion attribute on ShareArticle
_PU_CONVERSION_ATTRS: dict[str, str] = {
    "KG": "default_kg_per_pu_reseller",
    "PCS": "default_pieces_per_pu_reseller",
    "BUNCH": "default_bunches_per_pu_reseller",
}

# Maps unit type to the pricing attribute prefix
_PRICING_UNIT_NAMES: dict[str, str] = {
    "KG": "kg",
    "PCS": "pieces",
    "BUNCH": "bunch",
}


class OfferService:
    @staticmethod
    def annotate_offers_with_ordered_amounts(
        queryset: QuerySet[Offer] | None = None,
        year: int | None = None,
        delivery_week: int | None = None,
        delivery_day: int | None = None,
        reseller=None,
    ) -> QuerySet[Offer]:
        """Annotate offers with the total amount already ordered."""
        if queryset is None:
            queryset = Offer.objects.all()

        order_content_filters = Q(offer=OuterRef("pk"))

        if year is not None:
            order_content_filters &= Q(order__year=year)
        if delivery_week is not None:
            order_content_filters &= Q(order__delivery_week=delivery_week)
        if delivery_day is not None:
            order_content_filters &= Q(order__day_number=delivery_day)
        if reseller is not None:
            order_content_filters &= Q(order__reseller=reseller)

        ordered_amount_subquery = Subquery(
            OrderContent.objects.filter(order_content_filters)
            .values("offer")
            .annotate(total=Sum("amount"))
            .values("total")[:1],
            output_field=models.DecimalField(max_digits=10, decimal_places=3),
        )

        return queryset.annotate(
            amount_ordered=Coalesce(
                ordered_amount_subquery,
                Value(
                    0, output_field=models.DecimalField(max_digits=10, decimal_places=3)
                ),
            )
        )

    @staticmethod
    def _copy_offers(offer_ids, *, key_fn, exists_filter, mutate_fn) -> dict:
        """Clone the given offers, skipping any whose target slot already exists
        (persisted) OR was already queued in this batch.

        ``key_fn(offer)`` -> the per-batch dedup key (the exists() check only
        dedups against PERSISTED rows, so two source offers collapsing to the
        same target key would both pass it — dedup the in-memory batch too).
        ``exists_filter(offer)`` -> the ``Offer.objects.filter(**…)`` kwargs
        identifying an already-persisted target. ``mutate_fn(offer)`` reassigns
        the clone's target fields (week / group / …). Each clone is detached
        (pk/id -> None) and un-finalized before the bulk insert."""
        offers_to_copy = Offer.objects.filter(id__in=offer_ids)
        new_offers: list[Offer] = []
        skipped_count = 0
        queued_keys: set[tuple] = set()

        for offer in offers_to_copy:
            key = key_fn(offer)
            if key in queued_keys:
                skipped_count += 1
                continue

            if Offer.objects.filter(**exists_filter(offer)).exists():
                skipped_count += 1
                continue

            queued_keys.add(key)
            offer.pk = None
            offer.id = None
            offer.is_finalized = False
            mutate_fn(offer)
            new_offers.append(offer)

        created_offers = Offer.objects.bulk_create(new_offers)

        return {
            "created_ids": [str(o.id) for o in created_offers],
            "created_count": len(created_offers),
            "skipped_count": skipped_count,
        }

    @staticmethod
    @transaction.atomic
    def copy_offers_to_next_week(offer_ids: list[str]) -> dict:
        """Copy offers to the next week."""

        def _next_week(offer):
            return Week(offer.year, offer.delivery_week) + 1

        def key_fn(offer):
            nw = _next_week(offer)
            return (nw.year, nw.week, offer.share_article_id, offer.unit, offer.size)

        def exists_filter(offer):
            nw = _next_week(offer)
            return {
                "year": nw.year,
                "delivery_week": nw.week,
                "share_article_id": offer.share_article_id,
                "unit": offer.unit,
                "size": offer.size,
            }

        def mutate_fn(offer):
            nw = _next_week(offer)
            offer.year = nw.year
            offer.delivery_week = nw.week

        return OfferService._copy_offers(
            offer_ids,
            key_fn=key_fn,
            exists_filter=exists_filter,
            mutate_fn=mutate_fn,
        )

    @staticmethod
    @transaction.atomic
    def copy_offers_to_offer_group(
        offer_ids: list[str],
        year: int,
        delivery_week: int,
        offer_group: str,
    ) -> dict:
        """Copy selected offers to a different offer group in the same week."""

        def key_fn(offer):
            return (offer.share_article_id, offer.unit, offer.size, offer_group)

        def exists_filter(offer):
            return {
                "year": year,
                "delivery_week": delivery_week,
                "share_article_id": offer.share_article_id,
                "unit": offer.unit,
                "size": offer.size,
                "offer_group": offer_group,
            }

        def mutate_fn(offer):
            offer.offer_group_id = offer_group

        return OfferService._copy_offers(
            offer_ids,
            key_fn=key_fn,
            exists_filter=exists_filter,
            mutate_fn=mutate_fn,
        )

    @staticmethod
    @transaction.atomic
    def create_offers(year: int, delivery_week: int) -> dict:
        """
        Create offers for resellers based on:
        1. Forecasts (assigned to offer groups or marked for all)
        2. Theoretical stock (from StockService)
        3. Share content needs
        """
        current_date = Week(year, delivery_week).monday()
        offer_groups = list(OfferGroup.objects.all())

        if not offer_groups:
            # Keep the shape consistent with the normal return below — the
            # view reads ``result["skipped_count"]`` and ``result["skipped_offers"]``
            # unconditionally, so the short-circuit dict must carry them too.
            return {
                "created_count": 0,
                "skipped_count": 0,
                "skipped_offers": [],
                "message": "No offer groups found",
            }

        # Phase 1 — resolve the shared inputs the whole run keys off:
        # reseller stock, share-content needs, forecasts per group, and the
        # existing-offer idempotency snapshot.
        stock_amounts = OfferService._resolve_reseller_stock_amounts(
            year, delivery_week
        )
        share_content_amounts = OfferService._calculate_share_content_amounts(
            year, delivery_week
        )
        # Preload forecasts per group (2 queries) instead of 2 per group, and
        # the existing offers for the week in one query instead of a per-item
        # ``.exists()``. The set is updated as we create so an intra-run
        # duplicate is still skipped (matching the old per-item check under the
        # surrounding ``@transaction.atomic``).
        forecasts_by_group = OfferService._collect_forecast_amounts_by_group(
            year, delivery_week, offer_groups
        )
        existing_offers: set[tuple] = set(
            Offer.objects.filter(year=year, delivery_week=delivery_week).values_list(
                "share_article_id", "unit", "size", "offer_group_id"
            )
        )
        # Batch-resolve active pricing for every share article we might offer, so
        # ``_persist_offer`` doesn't run one ``get_pricing_on_date`` query per
        # created offer (uncached reverse relation → O(offers) queries).
        pricing_by_article = OfferService._bulk_active_pricing(
            {
                item_data["share_article"].id
                for group_items in forecasts_by_group.values()
                for item_data in group_items.values()
            },
            current_date,
        )

        # Phase 2 — walk each group's items, building offers where an amount is
        # available and not already offered. The counters, the ``skipped_offers``
        # ledger and the mutable ``existing_offers`` set are threaded through the
        # orchestrator so the ordering + intra-run dedup stay visible here.
        created_count = 0
        skipped_count = 0
        skipped_offers = []
        for offer_group in offer_groups:
            group_items = forecasts_by_group.get(str(offer_group.id), {})

            if not group_items:
                skipped_offers.append(
                    {
                        "offer_group": offer_group.name,
                        "reason": "No forecasts assigned to this group (check for_all_resellers or ForecastOfferGroup)",
                    }
                )

            for _key, item_data in group_items.items():
                share_article = item_data["share_article"]
                forecast_size = item_data["size"]

                # Compute the offer's unit + PU amount, or a skip reason.
                offer_unit, amount_pu, skip_reason = OfferService._evaluate_offer_item(
                    item_data,
                    stock_amounts,
                    share_content_amounts,
                    offer_group,
                )
                if skip_reason is not None:
                    skipped_count += 1
                    skipped_offers.append(skip_reason)
                    continue

                # Skip if already exists (indexed from the preloaded set; the
                # set is updated after each create below so intra-run duplicates
                # are skipped too).
                offer_key = (
                    share_article.id,
                    offer_unit,
                    forecast_size,
                    offer_group.id,
                )
                if offer_key in existing_offers:
                    skipped_count += 1
                    skipped_offers.append(
                        {
                            "share_article": share_article.name,
                            "unit": offer_unit,
                            "size": forecast_size,
                            "offer_group": offer_group.name,
                            "reason": "Offer already exists",
                        }
                    )
                    continue

                created = OfferService._persist_offer(
                    year=year,
                    delivery_week=delivery_week,
                    share_article=share_article,
                    offer_unit=offer_unit,
                    forecast_size=forecast_size,
                    amount_pu=amount_pu,
                    offer_group=offer_group,
                    current_date=current_date,
                    pricing=pricing_by_article.get(share_article.id),
                )
                if not created:
                    skipped_count += 1
                    skipped_offers.append(
                        {
                            "share_article": share_article.name,
                            "unit": offer_unit,
                            "size": forecast_size,
                            "offer_group": offer_group.name,
                            "reason": "Offer already exists (concurrent run)",
                        }
                    )
                    existing_offers.add(offer_key)
                    continue
                created_count += 1
                # Keep the idempotency set in sync so a later item in this same
                # run targeting the identical slot is skipped, as the old
                # per-item ``.exists()`` would have caught it.
                existing_offers.add(offer_key)

        return {
            "created_count": created_count,
            "skipped_count": skipped_count,
            "skipped_offers": skipped_offers,
        }

    @staticmethod
    def _resolve_reseller_stock_amounts(
        year: int, delivery_week: int
    ) -> dict[tuple, Decimal]:
        """Theoretical reseller stock for the week, keyed by
        ``(share_article_id, unit, size)``.

        Picks the first delivery ``day_number`` for the calculation and keeps
        only the entries flagged ``for_resellers``, summing across storages.
        """
        from .stock_service import StockService

        stock_map = StockService.get_theoretical_current_stock(
            year, delivery_week, day_number=0, storage=None
        )

        stock_amounts: dict[tuple, Decimal] = {}
        for (sa_id, unit, size, _storage_id), stock_data in stock_map.items():
            if not stock_data.get("for_resellers", False):
                continue
            key = (sa_id, unit, size)
            amount = stock_data.get("theoretical_current_stock") or Decimal("0")
            stock_amounts[key] = stock_amounts.get(key, Decimal("0")) + amount
        return stock_amounts

    @staticmethod
    def _evaluate_offer_item(
        item_data: dict,
        stock_amounts: dict[tuple, Decimal],
        share_content_amounts: dict[tuple, Decimal],
        offer_group: OfferGroup,
    ) -> tuple[str | None, Decimal | None, dict | None]:
        """Decide the offer unit + PU amount for one forecast item, or produce a
        skip reason.

        Returns ``(offer_unit, amount_pu, None)`` when an offer should be built,
        or ``(None, None, skip_reason)`` when the item is skipped (no available
        amount / missing PU conversion / amount below one PU). This covers the
        unit resolution, stock+share netting and PU conversion — everything
        BEFORE the existing-offer dedup check and the create, which stay in the
        orchestrator (they mutate the run-wide idempotency set and hit the DB).
        """
        share_article = item_data["share_article"]
        forecast_unit = item_data["unit"]
        forecast_size = item_data["size"]
        forecast_amount = item_data["forecast_amount"]

        commissioning_unit = share_article.default_commissioning_unit or forecast_unit

        # Convert the forecast to the article's commissioning unit. If the
        # per-size conversion factor is missing, fall back to the ORIGINAL
        # forecast unit/amount rather than skipping the offer — the offer
        # is still useful in its source unit. Everything below (stock/share
        # netting, PU, pricing, amount_per_pu) then keys off ``offer_unit``.
        if forecast_unit != commissioning_unit:
            converted = OfferService._convert_amount(
                forecast_amount,
                forecast_unit,
                commissioning_unit,
                forecast_size,
                share_article,
            )
            if converted:
                offer_amount = converted
                offer_unit = commissioning_unit
            else:
                offer_amount = forecast_amount
                offer_unit = forecast_unit
        else:
            offer_amount = forecast_amount
            offer_unit = forecast_unit

        # Convert stock and share needs to the CHOSEN offer unit (= the
        # commissioning unit normally, or the original forecast unit when
        # the conversion factor was missing) so offer_amount + stock −
        # needed below all share one unit.
        stock_amount = sum(
            OfferService._convert_amount(
                val,
                stock_key[1],
                offer_unit,
                forecast_size,
                share_article,
            )
            or Decimal("0")
            for stock_key, val in stock_amounts.items()
            if stock_key[0] == share_article.id and stock_key[2] == forecast_size
        )

        share_needed = sum(
            OfferService._convert_amount(
                val,
                stock_key[1],
                offer_unit,
                forecast_size,
                share_article,
            )
            or Decimal("0")
            for stock_key, val in share_content_amounts.items()
            if stock_key[0] == share_article.id and stock_key[2] == forecast_size
        )

        total_available = offer_amount + stock_amount - share_needed
        if total_available <= 0:
            return (
                None,
                None,
                {
                    "share_article": share_article.name,
                    "unit": offer_unit,
                    "size": forecast_size,
                    "offer_group": offer_group.name,
                    "reason": f"No available amount (forecast: {offer_amount}, stock: {stock_amount}, needed: {share_needed})",
                },
            )

        # Convert to PU
        pu_attr = _PU_CONVERSION_ATTRS.get(offer_unit)
        pu_conversion = getattr(share_article, pu_attr, None) if pu_attr else None
        if not pu_conversion or pu_conversion <= 0:
            return (
                None,
                None,
                {
                    "share_article": share_article.name,
                    "unit": offer_unit,
                    "size": forecast_size,
                    "offer_group": offer_group.name,
                    "reason": f"No PU conversion defined for {offer_unit} (attr: {pu_attr})",
                },
            )

        amount_pu = total_available / Decimal(str(pu_conversion))
        if amount_pu < 1:
            return (
                None,
                None,
                {
                    "share_article": share_article.name,
                    "unit": offer_unit,
                    "size": forecast_size,
                    "offer_group": offer_group.name,
                    "reason": f"Amount too small ({float(amount_pu):.2f} PU < 1 PU)",
                    "total_available": float(total_available),
                },
            )

        return offer_unit, amount_pu, None

    @staticmethod
    def _bulk_active_pricing(share_article_ids, on_date) -> dict:
        """Resolve the active ``ShareArticleNetPrice`` for many share articles in
        ONE query, keyed by ``share_article_id`` — the batch equivalent of
        ``ShareArticle.get_pricing_on_date`` (which caches nothing, so calling it
        per offer is O(offers) queries). Same newest-effective-wins tie-break
        (order by ``-valid_from``, first row per article)."""
        from ..models import ShareArticleNetPrice
        from ..models.managers import active_on_date_q

        by_article: dict = {}
        for row in (
            ShareArticleNetPrice.objects.filter(
                share_article_id__in=list(share_article_ids)
            )
            .filter(active_on_date_q(on_date))
            .order_by("-valid_from")
        ):
            by_article.setdefault(row.share_article_id, row)
        return by_article

    @staticmethod
    def _persist_offer(
        *,
        year: int,
        delivery_week: int,
        share_article: ShareArticle,
        offer_unit: str,
        forecast_size: str,
        amount_pu: Decimal,
        offer_group: OfferGroup,
        current_date,
        pricing=None,
    ) -> bool:
        """Create one general offer, resolving its pricing on ``current_date``.

        ``pricing`` is the active ``ShareArticleNetPrice`` pre-resolved in bulk by
        ``create_offers``; a direct caller that omits it falls back to a per-row
        lookup so the method stays usable standalone.

        Returns ``True`` when the row was created, ``False`` when a concurrent
        ``create_offers`` run inserted the same general-offer slot between the
        one-shot ``existing_offers`` snapshot and this INSERT. The partial
        unique constraint catches that race; the savepoint keeps the
        ``IntegrityError`` from poisoning the surrounding transaction, and we
        treat it as already-created (idempotent) rather than crashing the batch.
        """
        if pricing is None:
            pricing = share_article.get_pricing_on_date(current_date)
        price_1, price_2, price_3 = OfferService._get_prices_for_unit(
            pricing, offer_unit
        )

        from django.db import IntegrityError

        try:
            with transaction.atomic():
                Offer.objects.create(
                    year=year,
                    delivery_week=delivery_week,
                    share_article=share_article,
                    unit=offer_unit,
                    size=forecast_size,
                    amount=amount_pu,
                    price_1=price_1,
                    price_2=price_2,
                    price_3=price_3,
                    offer_group=offer_group,
                    is_finalized=False,
                    amount_per_pu=share_article.get_amount_per_pu_for_reseller(
                        offer_unit
                    ),
                    used_crate=share_article.default_crate_reseller,
                    description=share_article.description,
                )
        except IntegrityError:
            return False
        return True

    # ------------------------------------------------------------------
    # Private helpers for create_offers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_forecast_amounts_for_group(
        year: int, delivery_week: int, offer_group: OfferGroup
    ) -> dict[tuple, dict]:
        """
        Collect forecast amounts for a specific offer group.
        Includes forecasts that are:
        1. Marked for_all_resellers=True, OR
        2. Linked to this specific offer_group via ForecastOfferGroup
        """
        # Get forecast IDs linked to this offer group
        group_forecast_ids = set(
            ForecastOfferGroup.objects.filter(offer_group=offer_group).values_list(
                "forecast_id", flat=True
            )
        )

        # Get all forecasts that are either for_all_resellers or linked to this group
        forecasts = (
            Forecast.objects.filter(
                year=year,
                delivery_week=delivery_week,
            )
            .filter(Q(for_all_resellers=True) | Q(id__in=group_forecast_ids))
            .select_related("share_article")
        )

        group_items: dict[tuple, dict] = {}

        for forecast in forecasts:
            key = (forecast.share_article_id, forecast.unit, forecast.size)
            if key not in group_items:
                group_items[key] = {
                    "share_article": forecast.share_article,
                    "unit": forecast.unit,
                    "size": forecast.size,
                    "forecast_amount": Decimal("0"),
                }
            group_items[key]["forecast_amount"] += Decimal(forecast.amount or 0)

        return group_items

    @staticmethod
    def _collect_forecast_amounts_by_group(
        year: int,
        delivery_week: int,
        offer_groups: list[OfferGroup],
    ) -> dict[str, dict[tuple, dict]]:
        """Batched form of ``_collect_forecast_amounts_for_group`` for the whole
        offer-group set: two queries total instead of two per group (the
        ``for_all_resellers`` forecasts were otherwise re-scanned once per
        group, and the ForecastOfferGroup link query ran per group).

        Returns ``{offer_group_id_str: {(share_article_id, unit, size): {...}}}``
        and reproduces the single-group helper exactly — a forecast is included
        in a group iff it is ``for_all_resellers`` OR linked to that group, and
        counted once even when both hold (the original ``Q | Q`` filter dedups).
        """
        forecasts = list(
            Forecast.objects.filter(year=year, delivery_week=delivery_week)
            # Cache ``share_article.default_crate_reseller`` too — ``_persist_offer``
            # reads it per offer, so without this it's an extra FK query per
            # distinct article.
            .select_related("share_article", "share_article__default_crate_reseller")
        )

        group_ids_by_forecast: dict[str, set] = {}
        for forecast_id, group_id in ForecastOfferGroup.objects.filter(
            forecast__year=year, forecast__delivery_week=delivery_week
        ).values_list("forecast_id", "offer_group_id"):
            group_ids_by_forecast.setdefault(forecast_id, set()).add(group_id)

        result: dict[str, dict[tuple, dict]] = {}
        for offer_group in offer_groups:
            group_items: dict[tuple, dict] = {}
            for forecast in forecasts:
                if not (
                    forecast.for_all_resellers
                    or offer_group.id in group_ids_by_forecast.get(forecast.id, set())
                ):
                    continue
                key = (forecast.share_article_id, forecast.unit, forecast.size)
                if key not in group_items:
                    group_items[key] = {
                        "share_article": forecast.share_article,
                        "unit": forecast.unit,
                        "size": forecast.size,
                        "forecast_amount": Decimal("0"),
                    }
                group_items[key]["forecast_amount"] += Decimal(forecast.amount or 0)
            result[str(offer_group.id)] = group_items
        return result

    @staticmethod
    def _convert_amount(
        amount: Decimal,
        from_unit: str,
        to_unit: str,
        size: str,
        share_article: ShareArticle,
    ) -> Decimal | None:
        """
        Convert amount from one unit to another using ShareArticle conversion factors.

        Conversion paths:
        - KG <-> PCS: using kg_per_piece_{size} or pieces_per_kg_{size}
        - KG <-> BUNCH: using kg_per_bunch_{size}
        - PCS <-> BUNCH: using pieces_per_bunch_{size}

        Returns None if conversion not possible.
        """
        if from_unit == to_unit:
            return amount

        # KG -> PCS
        if from_unit == "KG" and to_unit == "PCS":
            pieces_per_kg = getattr(share_article, f"pieces_per_kg_{size}", None)
            if pieces_per_kg and pieces_per_kg > 0:
                return amount * Decimal(str(pieces_per_kg))

        # PCS -> KG
        if from_unit == "PCS" and to_unit == "KG":
            kg_per_piece = getattr(share_article, f"kg_per_piece_{size}", None)
            if kg_per_piece and kg_per_piece > 0:
                return amount * Decimal(str(kg_per_piece))

        # KG -> BUNCH
        if from_unit == "KG" and to_unit == "BUNCH":
            kg_per_bunch = getattr(share_article, f"kg_per_bunch_{size}", None)
            if kg_per_bunch and kg_per_bunch > 0:
                return amount / Decimal(str(kg_per_bunch))

        # BUNCH -> KG
        if from_unit == "BUNCH" and to_unit == "KG":
            kg_per_bunch = getattr(share_article, f"kg_per_bunch_{size}", None)
            if kg_per_bunch and kg_per_bunch > 0:
                return amount * Decimal(str(kg_per_bunch))

        # PCS -> BUNCH
        if from_unit == "PCS" and to_unit == "BUNCH":
            pieces_per_bunch = getattr(share_article, f"pieces_per_bunch_{size}", None)
            if pieces_per_bunch and pieces_per_bunch > 0:
                return amount / Decimal(str(pieces_per_bunch))

        # BUNCH -> PCS
        if from_unit == "BUNCH" and to_unit == "PCS":
            pieces_per_bunch = getattr(share_article, f"pieces_per_bunch_{size}", None)
            if pieces_per_bunch and pieces_per_bunch > 0:
                return amount * Decimal(str(pieces_per_bunch))

        # Indirect conversions (e.g., PCS -> KG -> BUNCH)
        if from_unit not in ["KG"] and to_unit not in ["KG"]:
            # Try converting through KG as intermediate
            amount_in_kg = OfferService._convert_amount(
                amount, from_unit, "KG", size, share_article
            )
            if amount_in_kg:
                return OfferService._convert_amount(
                    amount_in_kg, "KG", to_unit, size, share_article
                )

        return None

    @staticmethod
    def _calculate_share_content_amounts(
        year: int, delivery_week: int
    ) -> dict[tuple, Decimal]:
        """Calculate how much of each article is needed for shares."""
        shares = Share.objects.filter(year=year, delivery_week=delivery_week)

        # One aggregated query through the demand service. Switches
        # automatically between subscription-derived counts and the
        # CSV-imported ExternalShareDemand depending on tenant settings.
        rows = ShareDemandService.aggregated_rows(
            year=year,
            delivery_week=delivery_week,
        )

        # Build {(day_id, variation_id): {station_id_or_None: qty}}
        bucket: dict[tuple, dict[str | None, Decimal]] = defaultdict(
            lambda: defaultdict(lambda: Decimal("0"))
        )
        for r in rows:
            key = (r["day_id"], r["variation_id"])
            bucket[key][r["station_id"]] += Decimal(str(r["count"]))

        # Map back to per-share station quantities. Share is uniquely
        # identified within a (year, week) by (delivery_day, variation).
        share_station_quantities: dict[str, dict[str | None, Decimal]] = {}
        for share in shares:
            station_quantities = bucket.get(
                (share.delivery_day_id, share.share_type_variation_id), {}
            )
            share_station_quantities[share.id] = dict(station_quantities)

        # Calculate share content amounts
        share_contents = ShareContent.objects.filter(
            share__year=year,
            share__delivery_week=delivery_week,
        ).select_related(
            "share",
            "share_article",
            "share__share_type_variation",
            "delivery_station",
        )

        share_content_amounts: dict[tuple, Decimal] = {}

        for content in share_contents:
            key = (content.share_article_id, content.unit, content.size)

            if key not in share_content_amounts:
                share_content_amounts[key] = Decimal("0")

            station_id = (
                content.delivery_station.id if content.delivery_station else None
            )
            station_quantities = share_station_quantities.get(content.share.id, {})
            total_quantity = station_quantities.get(station_id, Decimal("0"))
            amount_needed = Decimal(content.amount or 0) * total_quantity

            share_content_amounts[key] += amount_needed

        return share_content_amounts

    @staticmethod
    def _get_prices_for_unit(pricing, unit: str) -> tuple:
        """Extract price_1, price_2, price_3 from pricing based on unit type."""
        if not pricing:
            return None, None, None

        unit_name = _PRICING_UNIT_NAMES.get(unit)
        if not unit_name:
            return None, None, None

        return (
            getattr(pricing, f"net_price_for_orders_{unit_name}_1", None),
            getattr(pricing, f"net_price_for_orders_{unit_name}_2", None),
            getattr(pricing, f"net_price_for_orders_{unit_name}_3", None),
        )

    @staticmethod
    def bulk_send_offers_via_email(
        *,
        reseller_ids: list[str],
        year: int,
        delivery_week: int,
        offer_group: OfferGroup,
        email_ctx: dict | None = None,
        progress_cb=None,
    ) -> dict:
        """
        Send offer emails to selected resellers and create OfferSending records.

        Returns a dict with total_processed, successful, failed, and results.

        ``progress_cb``: optional callable that receives a snapshot
        dict ``{processed, successful, failed, total}`` after every
        per-reseller iteration. Used by the Huey wrapper
        (``apps/commissioning/tasks.py::run_bulk_offer_send``) to drive
        the polling drawer's progress bar. Synchronous callers (tests,
        legacy paths) just pass ``None`` and the service stays
        identical to its pre-queue shape.
        """
        from apps.shared.tenants.email_service import (
            EmailService,
            capture_tenant_email_context,
        )

        email_service = EmailService()
        # Tenant name / language / frontend URL — passed from the enqueueing
        # view (real Tenant); fall back to the live tenant for synchronous
        # callers. The worker's FakeTenant can't supply these.
        ctx = email_ctx or capture_tenant_email_context()

        # Distinct requested ids — the progress denominator. The UI sends a
        # distinct selection, but dedup defensively so the bar can't overcount.
        requested_ids = list(dict.fromkeys(str(rid) for rid in reseller_ids))

        def _emit_progress(results_so_far: list[dict]) -> None:
            successful_count = sum(1 for r in results_so_far if r.get("success"))
            emit_progress(
                progress_cb,
                processed=len(results_so_far),
                successful=successful_count,
                failed=len(results_so_far) - successful_count,
                total=len(requested_ids),
            )

        resellers = Reseller.objects.filter(
            id__in=requested_ids, offer_group=offer_group
        ).select_related("contact")

        results: list[dict] = []

        # Any requested id missing from the queryset above (stale selection,
        # wrong offer group, deleted reseller) is silently dropped by the
        # filter. Record each as a failed result so the progress bar reaches
        # 100% (processed reconciles with total) and the office sees why an
        # id was skipped instead of facing a job that looks stuck.
        found_ids = {str(reseller.id) for reseller in resellers}
        for missing_id in requested_ids:
            if missing_id not in found_ids:
                results.append(
                    {
                        "reseller_id": missing_id,
                        "reseller_name": "Unknown",
                        "success": False,
                        "error": "Reseller not in this offer group",
                    }
                )
        # Surface the skipped ids immediately so the bar reflects them even
        # when there is no valid reseller left to iterate below.
        if results:
            _emit_progress(results)

        # Fetch offers once outside the loop (same for all resellers)
        offers = Offer.objects.filter(
            year=year,
            delivery_week=delivery_week,
            offer_group=offer_group,
        ).select_related("share_article")

        if not offers.exists():
            for reseller in resellers:
                reseller_name = reseller.contact.name if reseller.contact else "Unknown"
                results.append(
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": reseller_name,
                        "success": False,
                        "error": "No offers found for this week",
                    }
                )
            return {
                "total_processed": len(results),
                "successful": 0,
                "failed": len(results),
                "results": results,
            }

        # P1-2 idempotency pre-check, batched (2a). The previous
        # shape ran one ``.exists()`` query per reseller (N+1) — for
        # a 100-reseller bulk that's 100 extra round-trips before
        # the SMTP work even starts. One ``.values_list`` over the
        # whole composite-key bucket gives an in-memory set lookup
        # per iteration instead. The unique constraint still catches
        # the race window between this snapshot and the ``.create()``
        # below — defense-in-depth unchanged.
        already_sent_reseller_ids: set[str] = set(
            OfferSending.objects.filter(
                offer_group=offer_group,
                year=year,
                delivery_week=delivery_week,
            ).values_list("reseller_id", flat=True)
        )

        for reseller in resellers:
            reseller_name = reseller.contact.name if reseller.contact else "Unknown"

            if not reseller.contact or not reseller.contact.email:
                results.append(
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": reseller_name,
                        "success": False,
                        "error": "No email address found for reseller",
                    }
                )
                _emit_progress(results)
                continue

            if reseller.id in already_sent_reseller_ids:
                results.append(
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": reseller_name,
                        "success": True,
                        "already_sent": True,
                    }
                )
                _emit_progress(results)
                continue

            # ``reseller.contact`` is guaranteed non-None here (the
            # no-contact/no-email case already `continue`d above).
            offer_url = (
                f"{ctx['frontend_base_url']}"
                f"/commissioning/customer-orders/{reseller.id}"
            )
            try:
                success = email_service.send_email(
                    slug="commissioning.offer",
                    to_emails=[reseller.contact.email],
                    # Only the registry-declared scalar variables — never hand a
                    # live Offer queryset or OfferGroup instance to the
                    # tenant-editable renderer (info-leakage / accidental
                    # serialization). ``year``/``delivery_week`` stay as locals
                    # for the period string + log id, not as context keys.
                    context={
                        "tenant_name": ctx["tenant_name"],
                        "reseller": {"name": reseller.contact.name},
                        # No single ``deadline``: the order cutoff is per
                        # delivery day (OrdersDeliveryDay.default_last_possible_
                        # ordering_day/time). The order sheet (offer_url) shows
                        # and enforces each day's cutoff.
                        "offer": {"period": f"Week {delivery_week}, {year}"},
                        "offer_url": offer_url,
                    },
                    language=ctx["tenant_language"] or None,
                    related_object_type="offer_group",
                    related_object_id=str(getattr(offer_group, "id", "") or ""),
                )
            except (
                smtplib.SMTPException,
                ConnectionError,
                OSError,
                ValueError,
                TypeError,
                AttributeError,
            ):
                # Email send failures must not abort the batch — one bad
                # reseller email shouldn't stop the rest of the offer
                # blast. Real bugs still propagate.
                logger.exception(
                    "Failed to send offer email to reseller %s", reseller.id
                )
                success = False

            if success:
                # Record the send. The ``transaction.atomic`` block
                # is mostly intent-marking around a single
                # ``.create()`` — it gives us a clean ``IntegrityError``
                # handle for the race case where a concurrent bulk-
                # send raced through the ``.exists()`` check above
                # and inserted the composite key first. The recipient
                # got the email either way, so we log + treat as
                # success.
                def _create_offer_sending(reseller=reseller):
                    OfferSending.objects.create(
                        offer_group=offer_group,
                        year=year,
                        delivery_week=delivery_week,
                        reseller=reseller,
                    )

                def _on_offer_sending_race(reseller=reseller):
                    logger.warning(
                        "OfferSending composite key (%s, %s, %s, %s) already "
                        "existed at create — concurrent send race. Email DID "
                        "go out; treating as success.",
                        offer_group.id,
                        year,
                        delivery_week,
                        reseller.id,
                    )

                create_send_record_idempotent(
                    _create_offer_sending, on_race=_on_offer_sending_race
                )

                results.append(
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": reseller_name,
                        "success": True,
                    }
                )
            else:
                results.append(
                    {
                        "reseller_id": str(reseller.id),
                        "reseller_name": reseller_name,
                        "success": False,
                        "error": "Failed to send email",
                    }
                )
            _emit_progress(results)

        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful

        return {
            "total_processed": len(requested_ids),
            "successful": successful,
            "failed": failed,
            "results": results,
        }
