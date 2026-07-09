from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from django.db import transaction
from django.db.models import Q
from isoweek import Week

from ..errors import OfferGroupNotFound, ShareTypeVariationNotFound
from ..models import (
    DefaultShareArticleInShare,
    DefaultShareContent,
    DeliveryStationDay,
    Forecast,
    ForecastOfferGroup,
    ForecastShareTypeVariation,
    OfferGroup,
    Share,
    ShareContent,
    SharesDeliveryDay,
    ShareTypeVariation,
    TheoreticalHarvest,
)
from ..utils import sort_share_articles
from ..utils.iso_week_utils import saturday_of_iso_week
from .recompute import recompute_shares

logger = logging.getLogger(__name__)

_FORECAST_FIELDS = frozenset(
    {
        "amount",
        "bed_number",
        "delivery_week",
        "for_all_harvest_shares",
        "for_all_harvest_shares_fruit",
        "for_all_markets",
        "for_all_resellers",
        "note",
        "plot",
        "share_article",
        "harvesting_crate",
        "size",
        "unit",
        "year",
        "amount_per_pu",
        "sort_order",
    }
)

# Forecast fields whose change does NOT affect the materialised
# ShareContent rows (or anything downstream that ``recompute_shares``
# rebuilds). Editing one of these alone takes the light path —
# ``Forecast.save(update_fields=...)`` and nothing else. Editing
# anything else takes the full path (delete-theoreticals → rewrite
# variations / offer groups → re-create ShareContents → recompute).
#
# Why these are safe:
#   * ``note`` — pure documentation, never read by the planning math.
#   * ``sort_order`` — display-only on the office UI.
#   * ``bed_number`` — display-only on the harvesting list header.
#   * ``plot`` — display-only on the harvesting list header.
#   * ``harvesting_crate`` — consumed at harvest entry time, not at
#     planning time.
#
#
# A field NOT in this set (``amount``, ``share_article``, ``unit``,
# ``size``, ``year``, ``delivery_week``, ``for_all_*``, ``amount_per_pu``)
# takes the full path because it changes either the ShareContent
# rows themselves or which variations the forecast covers.
#
# Variation flag fields (``variation_<id>``) and offer-group flag
# fields (``offer_group_<id>``) come in via the same validated_data
# dict but live OUTSIDE ``_FORECAST_FIELDS``. They always trigger
# the full path because the ForecastShareTypeVariation /
# ForecastOfferGroup rewrites and the downstream ShareContent
# recompute depend on them.
_LIGHT_UPDATE_FIELDS = frozenset(
    {
        "note",
        "sort_order",
        "bed_number",
        "plot",
        "harvesting_crate",
    }
)


class ForecastService:
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_forecasts_with_relations(
        self, year: int, delivery_week: int, is_past: bool = False
    ) -> list[dict[str, Any]]:
        """Return forecasts for *year*/*delivery_week* with flattened variation/offer-group flags."""
        manager = Forecast.active.for_period(is_past=is_past)

        forecasts = (
            manager.filter(year=year, delivery_week=delivery_week)
            .select_related("share_article", "plot")
            .prefetch_related(
                "forecastsharetypevariation_set__share_type_variation",
                "forecastoffergroup_set__offer_group",
            )
        )

        result: list[dict[str, Any]] = []
        for forecast in forecasts:
            forecast_data: dict[str, Any] = {
                "id": forecast.id,
                "amount": forecast.amount,
                "bed_number": forecast.bed_number,
                "delivery_week": forecast.delivery_week,
                "for_all_harvest_shares": forecast.for_all_harvest_shares,
                "for_all_harvest_shares_fruit": forecast.for_all_harvest_shares_fruit,
                "for_all_markets": forecast.for_all_markets,
                "for_all_resellers": forecast.for_all_resellers,
                "note": forecast.note,
                "plot": forecast.plot_id,
                "plot_name": forecast.plot.name if forecast.plot else "",
                "share_article": forecast.share_article_id,
                "share_article_name": forecast.share_article.name,
                "size": forecast.size,
                "unit": forecast.unit,
                "year": forecast.year,
                "is_finalized": forecast.is_finalized,
            }

            for variation_rel in forecast.forecastsharetypevariation_set.all():
                forecast_data[f"variation_{variation_rel.share_type_variation_id}"] = (
                    True
                )

            for offer_group_rel in forecast.forecastoffergroup_set.all():
                forecast_data[f"offer_group_{offer_group_rel.offer_group_id}"] = True

            result.append(forecast_data)

        return sort_share_articles(result)

    @transaction.atomic
    def create_forecast_with_related_objects(
        self, validated_data: dict[str, Any]
    ) -> Forecast:
        forecast = self._create_forecast(validated_data)

        forecast_variations = self._create_share_type_variations(
            forecast, validated_data
        )
        self._create_offer_groups(forecast, validated_data)
        created, updated = self._create_or_update_share_contents(
            forecast, validated_data, forecast_variations
        )

        # Recompute the genuinely-new rows AND the pre-existing ShareContents
        # this new forecast just adopted (``updated``). A re-pointed row that
        # was previously forecastless has NO harvest theoretical on disk (they
        # are gated on ``share_content.forecast is not None``), so it needs its
        # TheoreticalHarvest + HARVEST movement CREATED — a bare forecast-FK
        # relink can only fix rows that already have theoreticals, never create
        # missing ones. ``recompute_shares`` is idempotent, so folding in rows
        # whose numbers are unchanged is safe.
        self._recompute_affected_shares(
            {str(share_content.share_id) for share_content in created}
            | {str(share_content.share_id) for share_content in updated}
        )

        return forecast

    @transaction.atomic
    def update_forecast_with_related_objects(
        self, instance: Forecast, validated_data: dict[str, Any]
    ) -> Forecast:
        # Light-path short-circuit: if the office only edited
        # display-only / documentation fields and didn't touch any
        # variation / offer-group flag, do a single
        # ``Forecast.save(update_fields=...)`` and skip the
        # delete-theoreticals → rewrite-relations → recompute chain.
        # Note-only edits on a heavy forecast measured ~600 ms before
        # this short-circuit and drop to <50 ms with it (the
        # recompute_shares + bulk re-create were ~95% of the cost).
        # See ``tests_services/test_forecast_service_perf.py`` for
        # the regression-guarding budgets.
        if self._is_light_update(instance, validated_data):
            forecast_fields = self._extract_forecast_fields(validated_data)
            for attr, value in forecast_fields.items():
                setattr(instance, attr, value)
            # ``update_fields=`` skips Django's auto_now machinery for
            # untouched columns and skips the model's signal payload
            # for irrelevant fields. The CheckConstraints on
            # ``Forecast`` cover the touched columns; ``full_clean``
            # is unnecessary for these fields (none have
            # cross-field validators), matching the rest of the
            # service's bulk paths.
            instance.save(update_fields=list(forecast_fields.keys()))
            return instance

        # Capture the shares affected by this update BEFORE mutating the
        # forecast, so the recompute below covers the survivors (re-pointed,
        # not recreated, by ``_create_or_update_share_contents``), the
        # genuinely-new rows, and the orphan-deleted ones (a no-op recompute
        # for a fully-emptied share).
        #
        # We deliberately do NOT delete the harvest theoreticals here. The
        # recompute (``recompute_for_shares``) owns that: it captures each
        # share's existing ``MovementShareArticle`` rows as ``old_movements``,
        # deletes ALL theoreticals + movements, rebuilds from the new forecast
        # state, then cascades those old movements through the stock snapshots.
        # Pre-deleting the harvest theoreticals (and their cascade-deleted
        # movements) here would strand the snapshots — the recompute would find
        # no movements to capture, leaving ``theoretical_current_stock``
        # permanently too high by the removed harvest amount.
        affected_share_ids = {
            str(share_id)
            for share_id in ShareContent.objects.filter(forecast=instance).values_list(
                "share_id", flat=True
            )
        }

        forecast_fields = self._extract_forecast_fields(validated_data)
        for attr, value in forecast_fields.items():
            setattr(instance, attr, value)
        instance.save()

        validated_data["share_article"] = instance.share_article

        forecast_variations = self._update_share_type_variations(
            instance, validated_data
        )

        # Delete orphaned share_contents when variations are removed
        self._delete_orphaned_share_contents(instance, forecast_variations)

        self._update_offer_groups(instance, validated_data)
        created, updated = self._create_or_update_share_contents(
            instance, validated_data, forecast_variations
        )

        # Recompute every affected share exactly once: the survivors already
        # on this forecast (captured above), any genuinely-new rows, AND the
        # pre-existing ShareContents this forecast just adopted (``updated`` —
        # rows re-pointed from ``forecast=None`` or a different forecast). An
        # adopted forecastless row has no harvest theoretical yet, so it must be
        # recomputed to CREATE its TheoreticalHarvest + HARVEST movement. A
        # single deduped set keeps the demand aggregation batched (one recompute
        # call, not N+1 per share); the overlap with ``affected_share_ids`` is
        # deduped away.
        self._recompute_affected_shares(
            affected_share_ids
            | {str(share_content.share_id) for share_content in created}
            | {str(share_content.share_id) for share_content in updated}
        )

        return instance

    @staticmethod
    def _is_light_update(instance: Forecast, validated_data: dict[str, Any]) -> bool:
        """True when this update touches only light fields AND doesn't
        change the variation / offer-group selection.

        "Touches only light fields": every key in ``validated_data``
        that targets a Forecast column is in ``_LIGHT_UPDATE_FIELDS``.
        ``variation_<id>`` / ``offer_group_<id>`` keys disqualify
        because they go through the relation-rewrite path; we also
        compare them against the current state so a payload that
        re-asserts the same flags (no diff) still takes the light
        path. Keys that don't target Forecast fields and aren't
        relation flags are ignored (forward-compat against new
        serializer fields).
        """
        # Lazily load the currently-set relation ids ONCE (one query each)
        # instead of a .exists() per variation_/offer_group_ key — the payload
        # can carry one flag per variation, so the old per-key probe was an N+1.
        existing_variation_ids: set[str] | None = None
        existing_offer_group_ids: set[str] | None = None
        for key, value in validated_data.items():
            if key in _LIGHT_UPDATE_FIELDS:
                continue
            if key in _FORECAST_FIELDS:
                # Heavy field present → full path.
                return False
            if key.startswith("variation_"):
                if existing_variation_ids is None:
                    existing_variation_ids = set(
                        ForecastShareTypeVariation.objects.filter(
                            forecast=instance
                        ).values_list("share_type_variation_id", flat=True)
                    )
                share_type_variation_id = key.removeprefix("variation_")
                is_set_now = share_type_variation_id in existing_variation_ids
                if bool(value) != is_set_now:
                    return False
                continue
            if key.startswith("offer_group_"):
                if existing_offer_group_ids is None:
                    existing_offer_group_ids = set(
                        ForecastOfferGroup.objects.filter(
                            forecast=instance
                        ).values_list("offer_group_id", flat=True)
                    )
                offer_group_id = key.removeprefix("offer_group_")
                is_set_now = offer_group_id in existing_offer_group_ids
                if bool(value) != is_set_now:
                    return False
                continue
        return True

    @transaction.atomic
    def bulk_copy_forecast_to_next_week(
        self, instance: Forecast, validated_data: dict[str, Any] | None = None
    ) -> Forecast | None:
        """Copy *instance* to the next ISO week, creating all related objects."""
        next_week_obj = Week(instance.year, instance.delivery_week) + 1
        next_week = next_week_obj.week
        next_year = next_week_obj.year

        already_exists = Forecast.objects.filter(
            year=next_year,
            delivery_week=next_week,
            share_article=instance.share_article,
            unit=instance.unit,
            size=instance.size,
        ).exists()

        if already_exists:
            return None

        forecast_data: dict[str, Any] = {
            "amount": instance.amount,
            "bed_number": instance.bed_number,
            "for_all_harvest_shares": instance.for_all_harvest_shares,
            "for_all_harvest_shares_fruit": instance.for_all_harvest_shares_fruit,
            "for_all_markets": instance.for_all_markets,
            "for_all_resellers": instance.for_all_resellers,
            "note": instance.note,
            "size": instance.size,
            "unit": instance.unit,
            "year": next_year,
            "delivery_week": next_week,
            "share_article": instance.share_article,
            "plot": instance.plot,
        }

        # Carry over variation & offer-group flags
        for v in instance.forecastsharetypevariation_set.all():
            forecast_data[f"variation_{v.share_type_variation_id}"] = True
        for offer_group in instance.forecastoffergroup_set.all():
            forecast_data[f"offer_group_{offer_group.offer_group_id}"] = True

        return self.create_forecast_with_related_objects(forecast_data)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_forecast_fields(validated_data: dict[str, Any]) -> dict[str, Any]:
        """Extract only fields that belong to the Forecast model."""
        return {
            key: value
            for key, value in validated_data.items()
            if key in _FORECAST_FIELDS
        }

    @transaction.atomic
    def _create_forecast(self, validated_data: dict[str, Any]) -> Forecast:
        return Forecast.objects.create(**self._extract_forecast_fields(validated_data))

    @transaction.atomic
    def _create_share_type_variations(
        self,
        forecast: Forecast,
        validated_data: dict[str, Any],
    ) -> list[ForecastShareTypeVariation]:
        """Create ``ForecastShareTypeVariation`` rows.

        If ``for_all_harvest_shares`` (or fruit variant) is set, all matching
        active variations are linked.  Otherwise, only explicitly flagged
        ``variation_<id>=True`` keys are used.
        """
        year: int = validated_data["year"]
        delivery_week: int = validated_data["delivery_week"]
        active_at_date = saturday_of_iso_week(year, delivery_week)

        collected: dict[str, ShareTypeVariation] = {}

        # "for all" flags → bulk-add all matching active variations
        if validated_data.get("for_all_harvest_shares"):
            for share_type_variation in ShareTypeVariation.current.active_at_date(
                active_at_date
            ).filter(share_type__share_option="HARVEST_SHARE"):
                collected[str(share_type_variation.id)] = share_type_variation

        if validated_data.get("for_all_harvest_shares_fruit"):
            for share_type_variation in ShareTypeVariation.current.active_at_date(
                active_at_date
            ).filter(share_type__share_option="HARVEST_SHARE_FRUIT"):
                collected[str(share_type_variation.id)] = share_type_variation

        # Explicit variation_<id> keys (handles individual checkboxes)
        explicit_ids = [
            key[10:]  # strip "variation_"
            for key in validated_data
            if key.startswith("variation_") and validated_data[key]
        ]
        # Only fetch IDs not already covered by the "for all" queries
        missing_ids = [
            variation_id
            for variation_id in explicit_ids
            if variation_id not in collected
        ]
        if missing_ids:
            for share_type_variation in ShareTypeVariation.objects.filter(
                id__in=missing_ids
            ):
                collected[str(share_type_variation.id)] = share_type_variation
            # Verify all requested IDs were found
            for variation_id in missing_ids:
                if variation_id not in collected:
                    # A JasminError (404), not ValueError: a bare ValueError
                    # would fall through the exception handler as a generic
                    # 500 mid-transaction.
                    raise ShareTypeVariationNotFound(
                        f"ShareTypeVariation with id {variation_id} does not exist",
                        field=f"variation_{variation_id}",
                        details={"variation_id": variation_id},
                    )

        if not collected:
            return []

        objs = [
            ForecastShareTypeVariation(
                forecast=forecast, share_type_variation=share_type_variation
            )
            for share_type_variation in collected.values()
        ]
        return list(ForecastShareTypeVariation.objects.bulk_create(objs))

    @transaction.atomic
    def _create_offer_groups(
        self,
        forecast: Forecast,
        validated_data: dict[str, Any],
    ) -> list[ForecastOfferGroup]:
        """Create ``ForecastOfferGroup`` rows for ``offer_group_<id>=True`` keys."""
        offer_group_ids = [
            key.replace("offer_group_", "")
            for key in validated_data
            if key.startswith("offer_group_") and validated_data[key]
        ]
        if not offer_group_ids:
            return []

        groups_by_id = {
            str(offer_group.id): offer_group
            for offer_group in OfferGroup.objects.filter(id__in=offer_group_ids)
        }
        objs = []
        for offer_group_id in offer_group_ids:
            offer_group = groups_by_id.get(offer_group_id)
            if offer_group is None:
                # A JasminError (404), not ValueError: a bare ValueError
                # would fall through the exception handler as a generic
                # 500 mid-transaction.
                raise OfferGroupNotFound(
                    f"OfferGroup with id {offer_group_id} does not exist"
                )
            objs.append(ForecastOfferGroup(forecast=forecast, offer_group=offer_group))

        return list(ForecastOfferGroup.objects.bulk_create(objs))

    @staticmethod
    def _prefetch_share_content_context(
        share_article: Any,
        size: Any,
        year: int,
        unit: Any,
        delivery_week: int,
        variation_ids: list[Any],
    ) -> tuple[
        list[SharesDeliveryDay],
        dict[tuple[Any, Any], Any],
        dict[tuple[Any, Any], DefaultShareContent],
        dict[Any, list[DeliveryStationDay]],
        dict[tuple[int, int, Any, Any], Share],
        dict[tuple[Any, Any], list[ShareContent]],
    ]:
        """Prefetch every lookup structure the build loop needs in a fixed
        number of queries.

        Returns ``(days, default_in_shares, default_share_contents,
        station_days_by_day, existing_shares, existing_contents_by_key)``.
        """
        active_at_date = saturday_of_iso_week(year, delivery_week)

        days = list(SharesDeliveryDay.current.active_at_date(active_at_date))

        # Pre-fetch defaults
        default_in_shares = {
            (
                article_in_share.share_article_id,
                article_in_share.share_type_variation_id,
            ): article_in_share
            for article_in_share in DefaultShareArticleInShare.objects.filter(
                share_article=share_article, share_type_variation_id__in=variation_ids
            )
        }
        default_share_contents = {
            (
                default_share_content.share_type_variation_id,
                default_share_content.share_article_id,
            ): default_share_content
            for default_share_content in DefaultShareContent.objects.filter(
                share_type_variation_id__in=variation_ids,
                share_article=share_article,
                year=year,
                delivery_week=delivery_week,
            )
        }

        # Pre-fetch all station-days for all delivery days in one query
        all_station_days = list(
            DeliveryStationDay.current.active_at_date(active_at_date)
            .filter(
                delivery_day__in=days,
                delivery_station__is_active=True,
            )
            .select_related("delivery_station")
        )
        station_days_by_day: dict[Any, list[DeliveryStationDay]] = {}
        for share_delivery in all_station_days:
            station_days_by_day.setdefault(share_delivery.delivery_day_id, []).append(
                share_delivery
            )

        # Pre-fetch existing shares
        existing_shares: dict[tuple[int, int, Any, Any], Share] = {}
        for s in Share.objects.filter(
            year=year,
            delivery_week=delivery_week,
            delivery_day__in=days,
            share_type_variation_id__in=variation_ids,
        ):
            existing_shares[
                (s.year, s.delivery_week, s.delivery_day_id, s.share_type_variation_id)
            ] = s

        # Batch the "does a ShareContent already exist for this (share,
        # station)?" lookup ONCE, instead of a ``.filter().exists()`` per
        # (share, station) inside the nested loop below. share_article / size /
        # unit are constant for this method (matching the
        # ``sharecontent_unique_share_article_station_unit_size`` constraint),
        # so the only varying keys are (share_id, delivery_station_id). Shares
        # created later in the loop have no ShareContent yet, so they correctly
        # miss this map and fall through to the create branch.
        existing_contents_by_key: dict[tuple[Any, Any], list[ShareContent]] = (
            defaultdict(list)
        )
        for share_content in ShareContent.objects.filter(
            share__in=list(existing_shares.values()),
            share_article=share_article,
            size=size,
            unit=unit,
        ):
            existing_contents_by_key[
                (share_content.share_id, share_content.delivery_station_id)
            ].append(share_content)

        return (
            days,
            default_in_shares,
            default_share_contents,
            station_days_by_day,
            existing_shares,
            existing_contents_by_key,
        )

    @staticmethod
    def _build_share_content_changes(
        forecast: Forecast,
        forecast_share_type_variations: list[ForecastShareTypeVariation],
        share_article: Any,
        size: Any,
        year: int,
        unit: Any,
        delivery_week: int,
        days: list[SharesDeliveryDay],
        default_in_shares: dict[tuple[Any, Any], Any],
        default_share_contents: dict[tuple[Any, Any], DefaultShareContent],
        station_days_by_day: dict[Any, list[DeliveryStationDay]],
        existing_shares: dict[tuple[int, int, Any, Any], Share],
        existing_contents_by_key: dict[tuple[Any, Any], list[ShareContent]],
    ) -> tuple[list[ShareContent], list[ShareContent]]:
        """Walk every variation × delivery-day × station and split the resulting
        ShareContent rows into the create / re-point buckets.

        Mutates ``existing_shares`` in place with any share created on demand via
        ``Share.get_or_create_for_delivery`` so a later iteration reuses it.
        Returns ``(share_contents_to_create, share_contents_to_update)``.
        """
        share_contents_to_create: list[ShareContent] = []
        share_contents_to_update: list[ShareContent] = []
        # Tracks (share_id, delivery_station_id) tuples we've already emitted
        # in this run so we never queue two ShareContents for the same
        # business-unique key (matches the DB constraint
        # ``sharecontent_unique_share_article_station_unit_size`` since
        # share_article/unit/size are constant for this method).
        seen_share_station_keys: set[tuple[Any, Any]] = set()

        for variation in forecast_share_type_variations:
            share_type_variation = variation.share_type_variation
            share_type_variation_id = variation.share_type_variation_id

            # Resolve default amount
            article_in_share = default_in_shares.get(
                (share_article.id, share_type_variation_id)
            )
            default_share_content = default_share_contents.get(
                (share_type_variation_id, share_article.id)
            )
            if article_in_share is not None and article_in_share.quantity is not None:
                amount = article_in_share.quantity
            elif (
                default_share_content is not None
                and default_share_content.amount is not None
            ):
                amount = default_share_content.amount
            else:
                amount = 0

            for day in days:
                share_delivery_list = station_days_by_day.get(day.id, [])

                # Get or create share
                share_key = (year, delivery_week, day.id, share_type_variation_id)
                share = existing_shares.get(share_key)
                if share is None:
                    share, _ = Share.get_or_create_for_delivery(
                        year=year,
                        delivery_week=delivery_week,
                        delivery_day=day,
                        share_type_variation=share_type_variation,
                    )
                    existing_shares[share_key] = share

                for station_day in share_delivery_list:
                    station_obj = station_day.delivery_station

                    # A station may have multiple DeliveryStationDay rows for
                    # the same (station, delivery_day) — different tours, or
                    # historical/overlapping rows. We still want exactly one
                    # ShareContent per (share, share_article, station, unit, size).
                    share_station_key = (share.id, station_obj.id)
                    if share_station_key in seen_share_station_keys:
                        continue
                    seen_share_station_keys.add(share_station_key)

                    existing = existing_contents_by_key.get((share.id, station_obj.id))

                    if existing:
                        for share_content in existing:
                            share_content.forecast = forecast
                            share_contents_to_update.append(share_content)
                    else:
                        share_contents_to_create.append(
                            ShareContent(
                                share=share,
                                share_article=share_article,
                                delivery_station=station_obj,
                                forecast=forecast,
                                amount=amount,
                                unit=unit,
                                size=size,
                            )
                        )

        return share_contents_to_create, share_contents_to_update

    @transaction.atomic
    def _create_or_update_share_contents(
        self,
        forecast: Forecast,
        validated_data: dict[str, Any],
        forecast_share_type_variations: list[ForecastShareTypeVariation],
    ) -> tuple[list[ShareContent], list[ShareContent]]:
        """Create or link ``ShareContent`` rows.

        Returns ``(created, updated)`` — the genuinely-new rows and the
        re-pointed existing rows — so each caller can build its own
        affected-share set and schedule recompute (see the two public
        ``*_forecast_with_related_objects`` methods).
        """
        if not forecast_share_type_variations:
            return [], []

        share_article = validated_data["share_article"]
        size = validated_data["size"]
        year: int = validated_data["year"]
        unit = validated_data["unit"]
        delivery_week: int = validated_data["delivery_week"]

        variation_ids = [
            v.share_type_variation_id for v in forecast_share_type_variations
        ]

        (
            days,
            default_in_shares,
            default_share_contents,
            station_days_by_day,
            existing_shares,
            existing_contents_by_key,
        ) = self._prefetch_share_content_context(
            share_article,
            size,
            year,
            unit,
            delivery_week,
            variation_ids,
        )

        (
            share_contents_to_create,
            share_contents_to_update,
        ) = self._build_share_content_changes(
            forecast,
            forecast_share_type_variations,
            share_article,
            size,
            year,
            unit,
            delivery_week,
            days,
            default_in_shares,
            default_share_contents,
            station_days_by_day,
            existing_shares,
            existing_contents_by_key,
        )

        created = (
            list(ShareContent.objects.bulk_create(share_contents_to_create))
            if share_contents_to_create
            else []
        )
        if share_contents_to_update:
            ShareContent.objects.bulk_update(share_contents_to_update, ["forecast"])

            # ``share_contents_to_update`` are EXISTING ShareContents whose
            # ``forecast`` FK was just re-pointed at this Forecast. Re-link any
            # harvest theoreticals they ALREADY have so the FK is consistent
            # immediately (before the deferred recompute fires). This does NOT
            # cover a row that was previously forecastless: it has no
            # TheoreticalHarvest to re-link, and its harvest theoretical must be
            # CREATED — which only ``recompute_shares`` can do. That is why both
            # callers additionally schedule a recompute for the ``updated`` rows;
            # this relink is just best-effort immediate consistency.
            #
            # Only ``TheoreticalHarvest`` carries the ``forecast`` FK —
            # ``TheoreticalPurchase`` / ``TheoreticalWashAmount`` /
            # ``TheoreticalCleanAmount`` link via ``share_content`` only,
            # so the bulk_update on ShareContent above already brings
            # them in line implicitly.
            TheoreticalHarvest.objects.filter(
                share_content_id__in=[
                    share_content.id for share_content in share_contents_to_update
                ]
            ).update(forecast=forecast)

        # Recompute is NOT scheduled here — the two callers own that decision
        # and build their own affected-share set. Both must recompute the
        # ``updated`` (re-pointed) rows so an adopted forecastless ShareContent
        # gets its harvest theoreticals created; ``update_*`` additionally folds
        # in the shares already on this forecast (captured before the mutation)
        # so their old movements are cascaded. Return both groups.
        return created, share_contents_to_update

    @staticmethod
    def _recompute_affected_shares(share_ids: set[str]) -> None:
        """Rebuild theoreticals + SHARECONTENT movements for *share_ids*
        synchronously, as part of the current forecast save.

        Runs inside the caller's ``@transaction.atomic`` block, so the
        recompute is atomic with the save: if it fails, the whole save
        rolls back (no half-written forecast with stale theoreticals), and
        downstream pages see fresh data the instant the request returns.

        Empty input is a no-op. ``recompute_shares`` is idempotent and
        early-returns for shares with no ShareContent, so passing a
        superset (e.g. a fully-emptied share) is safe. Pass ONE deduped
        set so the demand aggregation batches in a single call rather
        than N+1 per share.
        """
        if not share_ids:
            return

        recompute_shares(list(share_ids))

    @transaction.atomic
    def _update_share_type_variations(
        self, forecast: Forecast, validated_data: dict[str, Any]
    ) -> list[ForecastShareTypeVariation]:
        ForecastShareTypeVariation.objects.filter(forecast=forecast).delete()
        return self._create_share_type_variations(forecast, validated_data)

    def _delete_orphaned_share_contents(
        self,
        forecast: Forecast,
        new_forecast_variations: list[ForecastShareTypeVariation],
    ) -> None:
        """
        Delete ShareContent objects linked to this forecast but not in new variations.
        Only deletes if amount is null/None/0 - preserves manually edited amounts.
        """
        if not new_forecast_variations:
            # All variations removed, delete share_contents with null/None/0 amounts
            ShareContent.objects.filter(forecast=forecast).filter(
                Q(amount__isnull=True) | Q(amount=0)
            ).delete()
            return

        # Get the new variation IDs
        new_variation_ids = [v.share_type_variation_id for v in new_forecast_variations]

        # Delete share_contents that are:
        # 1. Linked to this forecast, AND
        # 2. Share's variation is not in new list, AND
        # 3. Amount is null/None or 0 (not manually edited)
        ShareContent.objects.filter(forecast=forecast).exclude(
            share__share_type_variation_id__in=new_variation_ids
        ).filter(Q(amount__isnull=True) | Q(amount=0)).delete()

    @transaction.atomic
    def _update_offer_groups(
        self, forecast: Forecast, validated_data: dict[str, Any]
    ) -> list[ForecastOfferGroup]:
        ForecastOfferGroup.objects.filter(forecast=forecast).delete()
        return self._create_offer_groups(forecast, validated_data)
