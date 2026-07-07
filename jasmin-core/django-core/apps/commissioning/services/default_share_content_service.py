from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from isoweek import Week

from ..errors import (
    CommissioningError,
    RequiredFieldMissing,
    ResellerNotFound,
    ShareArticleNotFound,
)
from ..models import (
    DefaultShareContent,
    DeliveryStationDay,
    MovementShareArticle,
    Reseller,
    Share,
    ShareArticle,
    ShareContent,
    SharesDeliveryDay,
    ShareTypeVariation,
    Subscription,
    VirtualVariationComponent,
)
from ..utils.basic_utils import extract_amounts_from_keys
from ..utils.dynamic_keys import SCAFFOLD_VALUES, parse_amount_cell

# Share lookup key: (year, delivery_week, delivery_day_id, share_type_variation_id)
_ShareKey = tuple[int, int, int, str]


class DefaultShareContentService:
    # ──────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _filter_weeks(
        week_range: range,
        *,
        only_odd: bool = False,
        only_even: bool = False,
        only_every_three: bool = False,
    ) -> list[int]:
        """Apply odd/even/every-three-week filters to a range of weeks."""
        filtered: list[int] = []
        for i, week in enumerate(week_range):
            if only_odd and week % 2 == 0:
                continue
            if only_even and week % 2 != 0:
                continue
            if only_every_three and i % 3 != 0:
                continue
            filtered.append(week)
        return filtered

    @staticmethod
    def _get_future_weeks(
        year: int,
        weeks: list[int],
        current_date: datetime.date,
    ) -> list[tuple[int, datetime.date]]:
        """Return (week_number, monday_date) pairs for weeks on or after current_date."""
        result: list[tuple[int, datetime.date]] = []
        for week in weeks:
            monday = Week(year, week).monday()
            if monday >= current_date:
                result.append((week, monday))
        return result

    @staticmethod
    def _prefetch_delivery_data(
        future_weeks: list[tuple[int, datetime.date]],
    ) -> tuple[
        dict[datetime.date, list],
        dict[Any, list],
    ]:
        """Prefetch delivery days and station relationships for future weeks.

        Returns:
            (delivery_days_by_date, delivery_station_days)
        """
        delivery_days_by_date: dict[datetime.date, list] = {}
        for _week, date in future_weeks:
            active_days = SharesDeliveryDay.current.active_at_date(date)
            if active_days.exists():
                delivery_days_by_date[date] = list(active_days)

        delivery_station_days: dict[Any, list] = defaultdict(list)
        if delivery_days_by_date:
            all_delivery_days = [
                delivery_day
                for delivery_day_list in delivery_days_by_date.values()
                for delivery_day in delivery_day_list
            ]
            # ``current`` (not ``objects``) so only ACTIVE station-days are
            # used — matches how the harvest planner resolves stations
            # (``DeliveryStationDay.current.active_at_date``). With ``objects``
            # this pulled in closed/historical station-days and materialised
            # ShareContent for stations that no longer deliver.
            station_relations = DeliveryStationDay.current.filter(
                delivery_day__in=all_delivery_days
            ).select_related("delivery_station", "delivery_day")

            for rel in station_relations:
                delivery_station_days[rel.delivery_day].append(rel.delivery_station)

        return delivery_days_by_date, dict(delivery_station_days)

    @staticmethod
    def _prefetch_existing_shares(
        year: int,
        week_range: range,
        variations: list[ShareTypeVariation],
        delivery_days: list,
    ) -> dict[_ShareKey, Share]:
        """Build a lookup dict of existing Share objects."""
        if not variations or not delivery_days:
            return {}

        existing: dict[_ShareKey, Share] = {}
        for share in Share.objects.filter(
            year=year,
            delivery_week__in=week_range,
            share_type_variation__in=variations,
            delivery_day__in=delivery_days,
        ).select_related("delivery_day"):
            key = (
                share.year,
                share.delivery_week,
                share.delivery_day_id,
                share.share_type_variation_id,
            )
            existing[key] = share

        # Self-heal reused shares that an earlier bulk_create left with NULL
        # day fields — otherwise the ShareContent we attach to them inherits
        # the NULL packing_day and silently drops out of the packing lists.
        Share.heal_day_fields(existing.values())
        return existing

    @staticmethod
    def _detect_week_pattern(
        weeks: list[int],
        range_1: int,
        range_2: int,
    ) -> tuple[bool, bool, bool]:
        """Detect whether weeks follow odd / even / every-three-weeks patterns.

        Returns:
            (only_odd_weeks, only_even_weeks, only_every_three_weeks)
        """
        weeks_set = set(weeks)

        only_odd = weeks_set == {w for w in range(range_1, range_2 + 1) if w % 2 != 0}
        only_even = weeks_set == {w for w in range(range_1, range_2 + 1) if w % 2 == 0}

        only_every_three = False
        if len(weeks) >= 2:
            expected = {range_1 + i for i in range(range_2 - range_1 + 1) if i % 3 == 0}
            only_every_three = weeks_set == expected

        return only_odd, only_even, only_every_three

    @staticmethod
    def _count_subscriptions_for_variation(
        variation: ShareTypeVariation,
        target_date: datetime.date,
    ) -> Decimal:
        """Active subscriptions (direct + virtual) for a physical variation at a
        date — or, when none are active then, the next future cohort. Thin
        wrapper over the batched ``_subscriber_counts_by_variation``."""
        return DefaultShareContentService._subscriber_counts_by_variation(
            {str(variation.id)}, target_date
        ).get(str(variation.id), Decimal(0))

    @staticmethod
    def _subscriber_counts_by_variation(
        variation_ids: set[str],
        snapshot_date: datetime.date,
    ) -> dict[str, Decimal]:
        """Active-subscriber count (direct + virtual) per physical variation.

        Counts subscriptions active at ``snapshot_date``. For a variation with
        NO subscriptions active then, falls back to its next future cohort — the
        subscribers starting on the earliest ``valid_from`` after
        ``snapshot_date`` — so planning a season before it starts doesn't read 0
        (``active_at_date`` otherwise excludes future-dated subscriptions).

        Virtual variations are covered too: those can be subscribed to directly,
        and a physical variation's count adds its virtual components' counts.
        """
        active_subs = Subscription.current.active_at_date(snapshot_date)

        # ``order_by()`` clears the model's default ``-valid_from`` ordering:
        # without it Django folds valid_from into the GROUP BY, splitting a
        # variation into one row per valid_from and undercounting the sum.
        direct_by_variation: dict[str, Decimal] = {}
        for row in (
            active_subs.values("share_type_variation_id")
            .annotate(total=Coalesce(Sum("quantity"), 0))
            .order_by()
        ):
            var_id = row["share_type_variation_id"]
            if var_id is not None:
                direct_by_variation[str(var_id)] = Decimal(row["total"])

        components_by_physical: dict[str, list[tuple[str, Decimal]]] = {}
        virtual_ids: set[str] = set()
        for phys_id, virt_id, quantity in VirtualVariationComponent.objects.filter(
            physical_variation_id__in=variation_ids
        ).values_list("physical_variation_id", "virtual_variation_id", "quantity"):
            components_by_physical.setdefault(str(phys_id), []).append(
                (str(virt_id), quantity)
            )
            virtual_ids.add(str(virt_id))

        # Forward fallback: for relevant variations with no subscribers active at
        # snapshot_date, use the next future cohort's count — the subscriptions
        # starting on the earliest valid_from after snapshot_date.
        relevant = set(variation_ids) | virtual_ids
        zero_vars = {v for v in relevant if direct_by_variation.get(v, Decimal(0)) == 0}
        if zero_vars:
            future_by_var: dict[str, list[tuple[datetime.date, int]]] = defaultdict(
                list
            )
            for var_id, valid_from, quantity in Subscription.current.filter(
                share_type_variation_id__in=zero_vars,
                valid_from__gt=snapshot_date,
            ).values_list(
                "share_type_variation_id",
                "valid_from",
                "quantity",
            ):
                if var_id is not None:
                    future_by_var[str(var_id)].append((valid_from, quantity or 0))
            for var_id, rows in future_by_var.items():
                earliest = min(valid_from for valid_from, _ in rows)
                direct_by_variation[var_id] = Decimal(
                    sum(q for valid_from, q in rows if valid_from == earliest)
                )

        counts: dict[str, Decimal] = {}
        for var_id in variation_ids:
            total = direct_by_variation.get(var_id, Decimal(0))
            for virt_id, quantity in components_by_physical.get(var_id, []):
                total += direct_by_variation.get(virt_id, Decimal(0)) * quantity
            counts[var_id] = total
        return counts

    @staticmethod
    def _calculate_needed_amount(
        year: int,
        range_1: int,
        range_2: int,
        only_odd: bool,
        only_even: bool,
        only_every_three: bool,
        amounts_dict: dict[str, str],
        subscriber_counts: dict[str, Decimal] | None = None,
    ) -> str:
        """Rough estimate of total amount needed for a share article over the
        planned timespan.

        Treats the current subscriber count of each share_type_variation as
        constant for the whole period (real ShareDeliveries are intentionally
        not summed up — they reflect past dispatch decisions that don't
        belong in a forward-looking planning total).

        Formula::

            Σ_variation ( current_subscribers(variation)
                          × amount_per_variation
                          × num_filtered_weeks )

        where ``num_filtered_weeks`` is the count of weeks in
        ``[range_1, range_2]`` after applying the only_odd / only_even /
        only_every_three pattern.
        """
        week_range = range(range_1, range_2 + 1)
        filtered_weeks = DefaultShareContentService._filter_weeks(
            week_range,
            only_odd=only_odd,
            only_even=only_even,
            only_every_three=only_every_three,
        )
        num_weeks = len(filtered_weeks)
        if num_weeks == 0:
            return "0"

        variation_amounts: dict[str, Decimal] = {}
        for variation_id, value in extract_amounts_from_keys(amounts_dict).items():
            variation_amounts[variation_id] = parse_amount_cell(
                value, field=f"amount_{variation_id}"
            )

        if not variation_amounts:
            return "0"

        # Single snapshot — the spec says "assume subscribers don't change over
        # the weeks", so one reference count is used for every week.
        total = Decimal(0)
        if subscriber_counts is not None:
            # Fast path: counts precomputed once for the whole request (see
            # ``get_default_share_content_list``) — no per-variation query. A
            # var_id absent from the map contributes 0, matching the legacy
            # path's skip of an unknown variation.
            for var_id, amount in variation_amounts.items():
                current_subscribers = subscriber_counts.get(var_id, Decimal(0))
                total += amount * current_subscribers * num_weeks
        else:
            # Legacy path (singular ``get_default_share_content``): resolve and
            # count each variation individually.
            snapshot_date = timezone.localdate()
            variations = {
                str(v.id): v
                for v in ShareTypeVariation.objects.filter(
                    id__in=list(variation_amounts.keys())
                )
            }
            for var_id, amount in variation_amounts.items():
                variation = variations.get(var_id)
                if variation is None:
                    continue
                current_subscribers = (
                    DefaultShareContentService._count_subscriptions_for_variation(
                        variation, snapshot_date
                    )
                )
                total += amount * current_subscribers * num_weeks

        return str(total.quantize(Decimal("0.01")))

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    @staticmethod
    def _validate_create_input(
        validated_data: dict[str, Any],
    ) -> dict[str, str]:
        """Validate the create payload and return the parsed amounts map.

        Raises ``CommissioningError`` when no amounts are provided and
        ``RequiredFieldMissing`` for any missing required field.
        """
        amounts = extract_amounts_from_keys(validated_data, "amount_")
        if not amounts:
            raise CommissioningError(
                "No share type variation amounts provided",
                code="default_share_content.no_amounts",
            )

        required_fields = [
            "year",
            "share_article",
            "share_option",
            "range_1",
            "range_2",
            "unit",
            "size",
        ]
        for field in required_fields:
            if not validated_data.get(field):
                raise RequiredFieldMissing(
                    f"Missing required field: {field}",
                    field=field,
                )

        return amounts

    @staticmethod
    def _resolve_create_variations(
        validated_data: dict[str, Any],
        amounts: dict[str, str],
    ) -> tuple[ShareArticle, dict[str, ShareTypeVariation], Reseller | None]:
        """Resolve the ShareArticle, all requested ShareTypeVariations and the
        optional Reseller referenced by the payload.

        Raises ``ShareArticleNotFound`` / ``ResellerNotFound`` for unknown FKs
        and ``CommissioningError`` when any requested variation id is missing.
        """
        try:
            share_article = ShareArticle.objects.get(id=validated_data["share_article"])
        except ShareArticle.DoesNotExist as exc:
            raise ShareArticleNotFound(
                f"ShareArticle with id {validated_data['share_article']} does not exist",
                details={"share_article_id": validated_data["share_article"]},
            ) from exc

        # Bulk-fetch all share type variations
        variation_ids = list(amounts.keys())
        share_type_variations: dict[str, ShareTypeVariation] = {
            str(var.id): var
            for var in ShareTypeVariation.objects.filter(id__in=variation_ids)
        }
        missing = set(variation_ids) - set(share_type_variations.keys())
        if missing:
            raise CommissioningError(
                f"ShareTypeVariations with ids {missing} do not exist",
                code="share_type_variation.missing_bulk",
                details={"missing_ids": sorted(missing)},
            )

        seller = None
        seller_id = validated_data.get("seller")
        if seller_id:
            try:
                seller = Reseller.objects.get(id=seller_id)
            except Reseller.DoesNotExist as exc:
                raise ResellerNotFound(
                    f"Reseller with id {seller_id} does not exist",
                    details={"seller_id": seller_id},
                ) from exc

        return share_article, share_type_variations, seller

    @staticmethod
    def _build_create_objects(
        validated_data: dict[str, Any],
        amounts: dict[str, str],
        share_article: ShareArticle,
        share_type_variations: dict[str, ShareTypeVariation],
        seller: Reseller | None,
    ) -> tuple[
        list[DefaultShareContent],
        list[Share],
        list[tuple[ShareContent, Share, Any, Any]],
        dict[_ShareKey, Share],
    ]:
        """Resolve the week/delivery layout and build the in-memory objects.

        Returns ``(all_default_contents, shares_to_create, all_share_contents,
        existing_shares)`` for the persist phase. ``existing_shares`` seeds the
        Share lookup with the prefetched + newly-built (unsaved) shares.
        """
        year: int = validated_data["year"]
        unit: str = validated_data["unit"]
        size: str = validated_data["size"]

        # Week filtering
        week_range = range(
            int(validated_data["range_1"]), int(validated_data["range_2"]) + 1
        )
        filtered_weeks = DefaultShareContentService._filter_weeks(
            week_range,
            only_odd=validated_data.get("only_odd_weeks", False),
            only_even=validated_data.get("only_even_weeks", False),
            only_every_three=validated_data.get("only_every_three_weeks", False),
        )

        current_date = timezone.localdate()
        future_weeks = DefaultShareContentService._get_future_weeks(
            year, filtered_weeks, current_date
        )

        # Pre-compute a set of future week numbers for fast lookups
        future_week_dates: dict[int, datetime.date] = {
            wk: dt for wk, dt in future_weeks
        }

        # Prefetch delivery/station data
        (
            delivery_days_by_date,
            delivery_station_days,
        ) = DefaultShareContentService._prefetch_delivery_data(future_weeks)

        all_delivery_days_flat = [
            delivery_day
            for delivery_day_list in delivery_days_by_date.values()
            for delivery_day in delivery_day_list
        ]
        existing_shares = DefaultShareContentService._prefetch_existing_shares(
            year,
            week_range,
            list(share_type_variations.values()),
            all_delivery_days_flat,
        )

        # Build objects in memory
        all_default_contents: list[DefaultShareContent] = []
        shares_to_create: list[Share] = []
        all_share_contents: list[tuple[ShareContent, Share, Any, Any]] = []

        note = validated_data.get("note")

        for variation_id, amount in amounts.items():
            if amount in SCAFFOLD_VALUES:
                continue

            variation = share_type_variations[variation_id]
            decimal_amount = parse_amount_cell(amount, field=f"amount_{variation_id}")
            # A zero amount is scaffold, not a real plan — same as
            # HarvestSharePlanning: don't persist a zero-quantity default row.
            if decimal_amount == 0:
                continue

            for week in filtered_weeks:
                all_default_contents.append(
                    DefaultShareContent(
                        year=year,
                        delivery_week=week,
                        share_type_variation=variation,
                        share_article=share_article,
                        amount=decimal_amount,
                        unit=unit,
                        size=size,
                        note=note,
                        seller=seller,
                    )
                )

                # Only create Share/ShareContent for future weeks
                monday = future_week_dates.get(week)
                if monday is None:
                    continue

                delivery_days = delivery_days_by_date.get(monday, [])

                for delivery_day in delivery_days:
                    share_key: _ShareKey = (
                        year,
                        week,
                        delivery_day.id,
                        variation.id,
                    )

                    if share_key in existing_shares:
                        share = existing_shares[share_key]
                    else:
                        # ``bulk_create`` below bypasses ``Share.save()``,
                        # which is where ALL day fields (harvesting / packing /
                        # washing / cleaning / get_current_stock) are defaulted
                        # from the delivery day. Apply them in memory via the
                        # model's own helper (driven by ``DAY_FIELD_DEFAULTS``,
                        # the single source of truth) so none are missed — a
                        # NULL day field silently excludes the share from that
                        # day-filtered list.
                        share = Share(
                            year=year,
                            delivery_week=week,
                            delivery_day=delivery_day,
                            share_type_variation=variation,
                        )
                        share._apply_default_day_fields()
                        shares_to_create.append(share)
                        existing_shares[share_key] = share

                    for station in delivery_station_days.get(delivery_day, []):
                        share_content = ShareContent(
                            share=share,
                            share_article=share_article,
                            size=size,
                            unit=unit,
                            delivery_station=station,
                            amount=decimal_amount,
                            seller=seller,
                        )
                        all_share_contents.append(
                            (share_content, share, delivery_day, station)
                        )

        return (
            all_default_contents,
            shares_to_create,
            all_share_contents,
            existing_shares,
        )

    @staticmethod
    def _persist_create_objects(
        year: int,
        all_default_contents: list[DefaultShareContent],
        shares_to_create: list[Share],
        all_share_contents: list[tuple[ShareContent, Share, Any, Any]],
        existing_shares: dict[_ShareKey, Share],
    ) -> None:
        """Bulk-persist the built objects, resolve Share references on the
        ShareContent rows, and trigger the recompute for the created shares."""
        # Bulk create
        if all_default_contents:
            DefaultShareContent.objects.bulk_create(
                all_default_contents, ignore_conflicts=True
            )

        if shares_to_create:
            Share.objects.bulk_create(shares_to_create, ignore_conflicts=True)

            # Re-fetch to get IDs assigned by the database
            for share in Share.objects.filter(
                year=year,
                delivery_week__in=[s.delivery_week for s in shares_to_create],
                share_type_variation__in=[
                    s.share_type_variation for s in shares_to_create
                ],
            ):
                key: _ShareKey = (
                    share.year,
                    share.delivery_week,
                    share.delivery_day_id,
                    share.share_type_variation_id,
                )
                existing_shares[key] = share

        # Resolve Share references and bulk-create ShareContent
        final_share_contents: list[ShareContent] = []
        for share_content, original_share, delivery_day, _station in all_share_contents:
            key = (
                original_share.year,
                original_share.delivery_week,
                delivery_day.id,
                original_share.share_type_variation_id,
            )
            resolved = existing_shares.get(key)
            if resolved:
                share_content.share = resolved
                final_share_contents.append(share_content)

        if final_share_contents:
            ShareContent.objects.bulk_create(
                final_share_contents, ignore_conflicts=True
            )

            from .recompute import recompute_shares

            recompute_shares(
                share_content.share_id for share_content in final_share_contents
            )

    @staticmethod
    @transaction.atomic
    def create_default_share_content(
        validated_data: dict[str, Any],
    ) -> list[DefaultShareContent]:
        """Create multiple DefaultShareContent objects from validated data."""
        amounts = DefaultShareContentService._validate_create_input(validated_data)

        (
            share_article,
            share_type_variations,
            seller,
        ) = DefaultShareContentService._resolve_create_variations(
            validated_data, amounts
        )

        (
            all_default_contents,
            shares_to_create,
            all_share_contents,
            existing_shares,
        ) = DefaultShareContentService._build_create_objects(
            validated_data,
            amounts,
            share_article,
            share_type_variations,
            seller,
        )

        DefaultShareContentService._persist_create_objects(
            validated_data["year"],
            all_default_contents,
            shares_to_create,
            all_share_contents,
            existing_shares,
        )

        return all_default_contents

    @staticmethod
    @transaction.atomic
    def materialize_for_new_station_day(station_day: DeliveryStationDay) -> int:
        """Fan the existing long-term ``DefaultShareContent`` plan out to a
        newly added ``DeliveryStationDay``.

        When a station starts delivering mid-season, the office expects the
        already-planned shares (honey, etc.) to be "theoretically delivered"
        at the new station too — without re-running long-term planning by
        hand. This materializes the missing ``ShareContent`` for just that
        station, for **future weeks only** (past deliveries already happened).

        Idempotent: ``bulk_create(ignore_conflicts=True)`` skips rows that
        already exist (ShareContent is unique per
        ``share / article / station / unit / size``), so re-firing is safe.

        Returns the number of ShareContent rows created.
        """
        delivery_day = station_day.delivery_day
        station = station_day.delivery_station
        current_date = timezone.localdate()

        defaults = list(
            DefaultShareContent.objects.select_related("share_type_variation")
        )
        if not defaults:
            return 0

        def _active_at(obj: Any, on_date: datetime.date) -> bool:
            if obj.valid_from and obj.valid_from > on_date:
                return False
            return obj.valid_until is None or obj.valid_until >= on_date

        # Future weeks where BOTH the delivery day and the new station-day are
        # active. Resolved once per (year, week).
        active_weeks: set[tuple[int, int]] = set()
        checked: set[tuple[int, int]] = set()
        for default in defaults:
            key = (default.year, default.delivery_week)
            if key in checked:
                continue
            checked.add(key)
            monday = Week(default.year, default.delivery_week).monday()
            if (
                monday >= current_date
                and _active_at(delivery_day, monday)
                and _active_at(station_day, monday)
            ):
                active_weeks.add(key)

        if not active_weeks:
            return 0

        # Resolve every Share for the active defaults in a bounded number of
        # queries rather than one get_or_create per default (the same
        # (year, week, variation) recurs across a variation's share_articles).
        share_keys = {
            (default.year, default.delivery_week, default.share_type_variation_id)
            for default in defaults
            if (default.year, default.delivery_week) in active_weeks
        }
        years = {key[0] for key in share_keys}
        weeks = {key[1] for key in share_keys}
        variation_ids = {key[2] for key in share_keys}

        def _fetch_shares() -> dict[tuple[int, int, str], Share]:
            return {
                (share.year, share.delivery_week, share.share_type_variation_id): share
                for share in Share.objects.filter(
                    delivery_day=delivery_day,
                    year__in=years,
                    delivery_week__in=weeks,
                    share_type_variation_id__in=variation_ids,
                )
            }

        shares_by_key = _fetch_shares()
        missing = [
            Share.build_for_delivery(
                year=year,
                delivery_week=week,
                delivery_day=delivery_day,
                share_type_variation_id=variation_id,
            )
            for (year, week, variation_id) in share_keys
            if (year, week, variation_id) not in shares_by_key
        ]
        if missing:
            Share.objects.bulk_create(missing, ignore_conflicts=True)
            # Re-fetch so the map holds PK-bearing rows for everything just
            # created (and anything a concurrent writer inserted meanwhile).
            shares_by_key = _fetch_shares()

        # Heal any reused row whose day fields are NULL — a no-op (no write)
        # for the common case where they're already populated.
        for share in shares_by_key.values():
            share.ensure_day_fields()

        contents: list[ShareContent] = []
        for default in defaults:
            if (default.year, default.delivery_week) not in active_weeks:
                continue
            share = shares_by_key[
                (
                    default.year,
                    default.delivery_week,
                    default.share_type_variation_id,
                )
            ]
            contents.append(
                ShareContent(
                    share=share,
                    share_article_id=default.share_article_id,
                    delivery_station=station,
                    unit=default.unit,
                    size=default.size,
                    amount=default.amount,
                    seller_id=default.seller_id,
                )
            )

        if not contents:
            return 0

        ShareContent.objects.bulk_create(contents, ignore_conflicts=True)

        from .recompute import recompute_shares

        recompute_shares({share_content.share_id for share_content in contents})
        return len(contents)

    @staticmethod
    def get_default_share_content(
        year: int,
        share_article_id: str,
        unit: str,
        size: str,
    ) -> dict[str, Any] | None:
        """Get DefaultShareContent data for a specific year/share_article/unit/size."""
        if not ShareArticle.objects.filter(id=share_article_id).exists():
            raise ShareArticleNotFound(
                f"ShareArticle with id {share_article_id} does not exist",
                details={"share_article_id": share_article_id},
            )

        contents: QuerySet[DefaultShareContent] = (
            DefaultShareContent.objects.filter(
                year=year, share_article_id=share_article_id, unit=unit, size=size
            )
            .select_related(
                "share_type_variation", "share_type_variation__share_type", "seller"
            )
            .order_by("delivery_week")
        )

        first = contents.first()
        if first is None:
            return None

        weeks = list(contents.values_list("delivery_week", flat=True))
        range_1 = min(weeks)
        range_2 = max(weeks)

        (
            only_odd,
            only_even,
            only_every_three,
        ) = DefaultShareContentService._detect_week_pattern(weeks, range_1, range_2)

        # Group amounts by share_type_variation
        amounts_dict: dict[str, str] = {}
        share_option: str | None = None

        for content in contents:
            variation_id = str(content.share_type_variation_id)
            amount_key = f"amount_{variation_id}"

            if amount_key not in amounts_dict:
                amounts_dict[amount_key] = str(content.amount)

            if share_option is None:
                share_option = content.share_type_variation.share_type.share_option

        needed_amount = DefaultShareContentService._calculate_needed_amount(
            year, range_1, range_2, only_odd, only_even, only_every_three, amounts_dict
        )

        result: dict[str, Any] = {
            "id": f"{year}_{share_article_id}_{unit}_{size}",
            "year": year,
            "share_article": share_article_id,
            "share_option": share_option,
            "range_1": range_1,
            "range_2": range_2,
            "unit": unit,
            "size": size,
            "note": first.note,
            "only_odd_weeks": only_odd,
            "only_even_weeks": only_even,
            "only_every_three_weeks": only_every_three,
            "needed_amount": needed_amount,
            "seller": str(first.seller_id) if first.seller_id else None,
            "seller_name": str(first.seller) if first.seller_id else None,
        }
        result.update(amounts_dict)
        return result

    @staticmethod
    def get_default_share_content_list(
        year: int,
        share_article_id: str | None = None,
        unit: str | None = None,
        size: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get a list of DefaultShareContent grouped by year/share_article/unit/size."""
        if share_article_id and unit and size:
            result = DefaultShareContentService.get_default_share_content(
                year, share_article_id, unit, size
            )
            return [result] if result else []

        # Batch-fetch all contents for the year in one query.
        # ``share_article`` covers the per-row name/unit lookups the
        # serializer touches; without it the response fans out to one
        # query per group on a 100s-row page.
        all_contents = (
            DefaultShareContent.objects.filter(year=year)
            .select_related(
                "share_type_variation",
                "share_type_variation__share_type",
                "share_article",
                "seller",
            )
            .order_by("share_article_id", "unit", "size", "delivery_week")
        )

        # Group by (share_article_id, unit, size)
        grouped: dict[tuple, list[DefaultShareContent]] = {}
        variation_ids: set[str] = set()
        for content in all_contents:
            key = (content.share_article_id, content.unit, content.size)
            grouped.setdefault(key, []).append(content)
            if content.share_type_variation_id is not None:
                variation_ids.add(str(content.share_type_variation_id))

        # Precompute active-subscriber counts ONCE for every variation on the
        # page. ``_calculate_needed_amount`` would otherwise re-query per group
        # per variation even though the snapshot date is identical per request.
        snapshot_date = timezone.localdate()
        subscriber_counts = DefaultShareContentService._subscriber_counts_by_variation(
            variation_ids, snapshot_date
        )

        results: list[dict[str, Any]] = []
        for (sa_id, unit_val, size_val), contents_list in grouped.items():
            first = contents_list[0]
            weeks = [c.delivery_week for c in contents_list]
            range_1 = min(weeks)
            range_2 = max(weeks)

            (
                only_odd,
                only_even,
                only_every_three,
            ) = DefaultShareContentService._detect_week_pattern(weeks, range_1, range_2)

            amounts_dict: dict[str, str] = {}
            share_option: str | None = None

            for content in contents_list:
                variation_id = str(content.share_type_variation_id)
                amount_key = f"amount_{variation_id}"
                if amount_key not in amounts_dict:
                    amounts_dict[amount_key] = str(content.amount)
                if share_option is None:
                    share_option = content.share_type_variation.share_type.share_option

            needed_amount = DefaultShareContentService._calculate_needed_amount(
                year,
                range_1,
                range_2,
                only_odd,
                only_even,
                only_every_three,
                amounts_dict,
                subscriber_counts=subscriber_counts,
            )

            result: dict[str, Any] = {
                "id": f"{year}_{sa_id}_{unit_val}_{size_val}",
                "year": year,
                "share_article": sa_id,
                "share_option": share_option,
                "range_1": range_1,
                "range_2": range_2,
                "unit": unit_val,
                "size": size_val,
                "note": first.note,
                "only_odd_weeks": only_odd,
                "only_even_weeks": only_even,
                "only_every_three_weeks": only_every_three,
                "needed_amount": needed_amount,
                "seller": str(first.seller_id) if first.seller_id else None,
                "seller_name": str(first.seller) if first.seller_id else None,
            }
            result.update(amounts_dict)
            results.append(result)

        return results

    @staticmethod
    @transaction.atomic
    def update_default_share_content(
        year: int,
        share_article_id: str,
        validated_data: dict[str, Any],
    ) -> list[DefaultShareContent]:
        """Update DefaultShareContent: deletes existing and creates new from validated_data."""
        try:
            share_article = ShareArticle.objects.get(id=share_article_id)
        except ShareArticle.DoesNotExist as exc:
            raise ShareArticleNotFound(
                f"ShareArticle with id {share_article_id} does not exist",
                details={"share_article_id": share_article_id},
            ) from exc

        unit = validated_data.get("unit")
        size = validated_data.get("size")

        week_range = range(
            int(validated_data["range_1"]), int(validated_data["range_2"]) + 1
        )
        current_date = timezone.localdate()
        future_weeks = [
            week for week in week_range if Week(year, week).monday() >= current_date
        ]

        DefaultShareContent.objects.filter(
            year=year, share_article=share_article, unit=unit, size=size
        ).delete()

        # Capture what the ShareContent deletion will cascade away BEFORE it
        # runs: its MovementShareArticle rows (FK on_delete=CASCADE) and the
        # parent Share ids. The slot's planned amounts can be non-zero, so
        # dropping them silently leaves StockSnapshots / INVENTORY balances
        # stale unless we cascade afterwards — mirror delete_share_planning.
        affected_movements: list[MovementShareArticle] = []
        emptied_share_ids: set[Any] = set()
        if future_weeks:
            share_contents_to_delete = ShareContent.objects.filter(
                share__year=year,
                share__delivery_week__in=future_weeks,
                share_article=share_article,
                unit=unit,
                size=size,
            )
            emptied_share_ids = set(
                share_contents_to_delete.values_list("share_id", flat=True)
            )
            # Capture BOTH movement halves before the delete: the SHARECONTENT
            # rows AND the theoretical_* halves (which carry share_content=NULL
            # and cascade away with the ShareContent) — else their stock
            # contribution is silently left out of the recompute and the
            # snapshot stays too high. Mirrors share_content_service's slot paths.
            affected_movements = list(
                MovementShareArticle.objects.for_share_contents(
                    share_contents_to_delete
                )
            )
            share_contents_to_delete.delete()

        result = DefaultShareContentService.create_default_share_content(validated_data)

        # ``create_default_share_content`` recomputes only the rows it recreates.
        # A slot week the new range / week-pattern / station set no longer
        # covers is left emptied with no replacement, and ``recompute_for_shares``
        # early-returns for a share with no remaining ShareContent — so rebuild
        # the affected shares explicitly (idempotent; a no-op for fully-emptied
        # shares), then cascade snapshots for the entities whose movements were
        # removed so downstream stock balances stay correct. The recompute's
        # cascade is folded into ONE union cascade with the removed movements —
        # a single sorted ``current_balance:*`` advisory-lock pass for the
        # transaction (two separate passes could AB/BA-deadlock against a
        # concurrent overlapping acquirer).
        deferred_movements: list[MovementShareArticle] = []
        if emptied_share_ids:
            from .recompute import recompute_shares

            recompute_shares(emptied_share_ids, collect_movements=deferred_movements)
        if affected_movements:
            from .theoretical_objects import recalculate_actual_corrections

            deferred_movements.extend(affected_movements)
            recalculate_actual_corrections(
                affected_movements, collect_movements=deferred_movements
            )
        if deferred_movements:
            from .snapshot_service import SnapshotService

            SnapshotService.cascade_for_movements(deferred_movements)

        return result

    @staticmethod
    @transaction.atomic
    def delete_default_share_content_bulk(
        year: int,
        share_article: ShareArticle | None = None,
        unit: str | None = None,
        size: str | None = None,
    ) -> int:
        """Delete multiple DefaultShareContent objects by criteria, and cascade
        the deletion to the future ShareContent they materialised.

        ShareContent from **current ISO week + 2** onward is removed; the next
        two weeks are already in the packing pipeline, so those slots (and all
        past weeks) are left intact. Mirrors ``update_default_share_content``'s
        cascade: capture the affected Shares + MovementShareArticle rows BEFORE
        deleting, then recompute the emptied Shares and cascade stock snapshots
        so downstream balances stay correct.
        """
        queryset = DefaultShareContent.objects.filter(year=year)

        if share_article:
            queryset = queryset.filter(share_article=share_article)
        if unit:
            queryset = queryset.filter(unit=unit)
        if size:
            queryset = queryset.filter(size=size)

        count = queryset.count()

        # Cascade to the future ShareContent these defaults materialised, scoped
        # to the SAME article/unit/size so another article's slots are never
        # touched. Only meaningful when an article is given (the URL always
        # supplies one); a whole-year wipe without an article is left as a plain
        # DefaultShareContent delete.
        emptied_share_ids: set[Any] = set()
        affected_movements: list[MovementShareArticle] = []

        # Roll the cutoff via ``isoweek.Week`` so "current ISO week + 2"
        # crosses 52/53-week year boundaries correctly: near year end the
        # pipeline weeks live in the NEXT ISO year (e.g. week 52 + 2 → weeks
        # 1-2 of the following year), which a bare ``current_week + 2``
        # comparison would wrongly treat as deletable.
        iso = timezone.localdate().isocalendar()
        cutoff = Week(iso[0], iso[1]) + 2
        cutoff_year, cutoff_week = cutoff.year, cutoff.week

        if share_article is not None and year >= cutoff_year:
            share_contents_to_delete = ShareContent.objects.filter(
                share__year=year, share_article=share_article
            )
            if unit:
                share_contents_to_delete = share_contents_to_delete.filter(unit=unit)
            if size:
                share_contents_to_delete = share_contents_to_delete.filter(size=size)
            # A year past the cutoff year is entirely ahead of the cutoff;
            # only the cutoff year itself needs the week threshold.
            if year == cutoff_year:
                share_contents_to_delete = share_contents_to_delete.filter(
                    share__delivery_week__gte=cutoff_week
                )

            emptied_share_ids = set(
                share_contents_to_delete.values_list("share_id", flat=True)
            )
            # Wide capture (both movement halves) before the delete — see the
            # matching note in update_default_share_content; the theoretical_*
            # halves must be re-cascaded too or the snapshot stays too high.
            affected_movements = list(
                MovementShareArticle.objects.for_share_contents(
                    share_contents_to_delete
                )
            )
            share_contents_to_delete.delete()

        queryset.delete()

        # ``recompute_shares`` is idempotent and a no-op for fully-emptied
        # Shares; cascade snapshots for the entities whose movements were
        # removed so downstream stock balances stay correct. Folded into ONE
        # union cascade (single sorted advisory-lock pass) — see the matching
        # note in update_default_share_content.
        deferred_movements: list[MovementShareArticle] = []
        if emptied_share_ids:
            from .recompute import recompute_shares

            recompute_shares(emptied_share_ids, collect_movements=deferred_movements)
        if affected_movements:
            from .theoretical_objects import recalculate_actual_corrections

            deferred_movements.extend(affected_movements)
            recalculate_actual_corrections(
                affected_movements, collect_movements=deferred_movements
            )
        if deferred_movements:
            from .snapshot_service import SnapshotService

            SnapshotService.cascade_for_movements(deferred_movements)

        return count
