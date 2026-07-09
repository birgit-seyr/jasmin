from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from isoweek import Week

from ..models import (
    DeliveryStation,
    ShareArticle,
    ShareContent,
    ShareTypeVariation,
)
from ..utils import sort_share_articles
from ..utils.basic_utils import size_order_annotation
from ..utils.delivery_utils import tour_station_ids
from ..utils.iso_week_utils import saturday_of_iso_week
from ..utils.packing_divergence import record_amount
from ..utils.share_type_variation_amounts import (
    batch_get_physical_variation_totals_for_week,
)
from ..utils.weight import quantize_weight

_UNSET = object()  # sentinel: "not hoisted" vs a legitimately None delivery_day


class PackingListService:
    @staticmethod
    def _active_share_type_variations(
        year: int,
        delivery_week: int,
        share_type: str,
        is_packed_bulk: bool | None = None,
    ) -> list[ShareTypeVariation]:
        """Active variations of ``share_type`` for the delivery week, in
        display order. Loop-invariant across delivery stations, so the bulk
        path resolves it once and hands it to ``get_packing_list``."""
        active_at_date = saturday_of_iso_week(year, delivery_week)
        qs = (
            ShareTypeVariation.current.active_at_date(active_at_date)
            .filter(share_type=share_type)
            .annotate(size_order=size_order_annotation())
            .order_by("sort_order", "size_order")
        )
        if is_packed_bulk is not None:
            qs = qs.filter(is_packed_bulk=is_packed_bulk)
        return list(qs)

    @staticmethod
    def get_packing_list(
        year: int,
        delivery_week: int,
        day_number: int,
        share_type: str,
        is_past: bool,
        delivery_station: str | None = None,
        tour: str | None = None,
        packing_station: int | None = None,
        is_packed_bulk: bool | None = None,
        *,
        # Loop-invariant values the bulk path computes once and hands down so
        # each station stops re-running the variation query + the
        # exists()/first() delivery_day probe. _UNSET keeps a legitimately
        # None delivery_day distinguishable from "caller didn't hoist it".
        _hoisted_variations: list[ShareTypeVariation] | None = None,
        _hoisted_delivery_day: Any = _UNSET,
    ) -> list[dict[str, Any]]:
        iso_week = Week(year, delivery_week)
        active_at_date = iso_week.saturday()

        if _hoisted_variations is not None:
            share_type_variations = _hoisted_variations
        else:
            share_type_variations = PackingListService._active_share_type_variations(
                year, delivery_week, share_type, is_packed_bulk
            )

        manager = ShareContent.active.for_period(is_past=is_past)

        share_contents = manager.filter(
            share__year=year,
            share__delivery_week=delivery_week,
            share__delivery_day__day_number=day_number,
            share__share_type_variation__share_type=share_type,
        )
        if is_packed_bulk is not None:
            share_contents = share_contents.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )

        if _hoisted_delivery_day is not _UNSET:
            delivery_day = _hoisted_delivery_day
        else:
            first = share_contents.first()
            delivery_day = first.share.delivery_day if first is not None else None

        if delivery_station is not None:
            share_contents = share_contents.filter(delivery_station=delivery_station)

        if tour is not None:
            station_ids = tour_station_ids(
                active_at_date, delivery_day=delivery_day, tour=tour
            )
            share_contents = share_contents.filter(delivery_station_id__in=station_ids)

        if packing_station is not None:
            share_contents = share_contents.filter(packing_station=packing_station)

        share_contents = share_contents.values(
            "share_article__id",
            "share_article__name",
            "unit",
            "size",
            "amount",
            "share__share_type_variation__id",
            "share__delivery_day_id",
            "note",
            "backup_share_article__id",
            "backup_share_article__name",
            "backup_unit",
            "backup_size",
            "backup_amount",
            "packing_station",
        ).order_by("share_article__name", "unit", "size")

        # Build variation key list once
        variation_keys = [f"variation_{v.id}" for v in share_type_variations]
        # Parallel ``backup_variation_<id>`` keys carry each row's per-variation
        # BACKUP quantity (ShareContent.backup_amount) so the packing list can
        # show the backup article's own amounts beside the mains, not a guess.
        backup_variation_keys = [
            f"backup_variation_{v.id}" for v in share_type_variations
        ]

        # Organize data by share article
        articles_dict: dict[str, dict[str, Any]] = {}
        # Safety net for the all-stations view (no delivery_station scope): the
        # same (article, unit, size, variation) cell can receive rows from
        # several stations WITHIN ONE DELIVERY DAY. Collapsing them keeps an
        # arbitrary one, which is only correct when their amounts AGREE — the
        # office's per-delivery-day granularity guard (days_ok) keeps the
        # all-stations view to exactly those consistent cases. If they diverge,
        # refuse loudly rather than silently drop a station's amount. The cell is
        # keyed by delivery day too: days_ok is computed PER delivery day, so two
        # delivery days that share a packing day may legitimately differ and must
        # NOT trip this. (Skipped when a concrete station scopes the request:
        # there's one row per cell then, so no collapse.)
        seen_amounts: dict[tuple[str, str, str], Any] = {}
        for content in share_contents:
            composite_key = (
                f"{content['share_article__id']}_{content['unit']}_{content['size']}"
            )

            if composite_key not in articles_dict:
                article_entry: dict[str, Any] = {
                    "id": composite_key,
                    "share_article": content["share_article__id"],
                    "share_article_name": content["share_article__name"],
                    "unit": content["unit"],
                    "size": content["size"],
                    "note": content["note"] or "",
                    "backup_share_article": content["backup_share_article__id"],
                    "backup_share_article_name": content["backup_share_article__name"],
                    "backup_share_article_unit": content["backup_unit"],
                    "backup_share_article_size": content["backup_size"],
                    "packing_station": content["packing_station"],
                }
                for variation_key in variation_keys:
                    article_entry[variation_key] = 0
                for backup_variation_key in backup_variation_keys:
                    article_entry[backup_variation_key] = 0
                articles_dict[composite_key] = article_entry

            variation_key = f'variation_{content["share__share_type_variation__id"]}'
            amount = content["amount"] or 0
            if delivery_station is None:
                cell = (
                    composite_key,
                    variation_key,
                    content["share__delivery_day_id"],
                )
                record_amount(
                    seen_amounts,
                    cell,
                    amount,
                    article_id=content["share_article__id"],
                    unit=content["unit"],
                    size=content["size"],
                    variation_id=content["share__share_type_variation__id"],
                )
            articles_dict[composite_key][variation_key] = amount
            backup_variation_key = (
                f'backup_variation_{content["share__share_type_variation__id"]}'
            )
            articles_dict[composite_key][backup_variation_key] = (
                content["backup_amount"] or 0
            )

        # Filter out entries where all variation amounts are 0
        filtered_results = [
            item
            for item in articles_dict.values()
            if any(item.get(variation_key, 0) > 0 for variation_key in variation_keys)
        ]

        if packing_station is None:
            # Group by packing station, then sort each group
            grouped_by_station: defaultdict[int | None, list[dict[str, Any]]] = (
                defaultdict(list)
            )
            for item in filtered_results:
                grouped_by_station[item.get("packing_station")].append(item)

            result: list[dict[str, Any]] = []
            for station_key in sorted(
                grouped_by_station.keys(), key=lambda x: x if x is not None else 0
            ):
                result.extend(sort_share_articles(grouped_by_station[station_key]))
        else:
            result = sort_share_articles(filtered_results)

        return result

    @staticmethod
    def _bulk_rows_for_share_type(
        year: int,
        delivery_week: int,
        day_number: int,
        share_type: str,
        is_past: bool,
        delivery_station: str | None = None,
        is_packed_bulk: bool | None = None,
    ) -> list[dict[str, Any]]:
        """
        Bulk packing rows for a SINGLE ``share_type`` — the per-share_type
        building block ``get_packing_list_bulk`` sums over.

        For each ``(delivery_station, share_article)`` combination, returns
        the total physical amount needed by summing
        ``amount_per_share × physical_share_type_variation_count`` across
        every variation. Virtual share_type_variations are resolved into
        their physical components by ``batch_get_physical_variation_totals_
        for_week`` — ``ShareContent`` rows reference only physical variations,
        so the multiplier must come from the resolved physical variation count.

        ``total_amount`` is returned as a **Decimal** (not float): the caller
        merges rows across share_types by summing, and staying in Decimal
        avoids binary-fp drift before the single float-cast at the boundary.
        """
        manager = ShareContent.active.for_period(is_past=is_past)
        share_contents = manager.filter(
            share__year=year,
            share__delivery_week=delivery_week,
            share__delivery_day__day_number=day_number,
            share__share_type_variation__share_type=share_type,
        ).select_related("share")
        if is_packed_bulk is not None:
            share_contents = share_contents.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )

        first = share_contents.first()
        if first is None:
            return []

        delivery_day = first.share.delivery_day

        if delivery_station is not None:
            share_contents = share_contents.filter(delivery_station=delivery_station)

        station_ids = list(
            share_contents.values_list("delivery_station_id", flat=True)
            .distinct()
            .order_by("delivery_station_id")
        )
        stations_by_id: dict[str, DeliveryStation] = {
            s.id: s for s in DeliveryStation.objects.filter(id__in=station_ids)
        }

        # Buffer percentages per article — bulk totals get multiplied by
        # ``(pct / 100 + 1)``. NULL / 0 keeps the multiplier at 1.0.
        bulk_pct_by_article: dict[str, int] = dict(
            ShareArticle.objects.values_list(
                "id", "percentage_added_to_bulk_packing_list"
            )
        )

        # Resolve every (variation × station) physical total for this delivery
        # day in ONE batched aggregation up front, then look it up per station
        # — instead of re-running the resolver inside the station loop (which
        # fired a demand query per variation per station).
        physical_variations = ShareTypeVariation.objects.filter(
            variation_type="physical", share_type=share_type
        )
        station_variation_totals = batch_get_physical_variation_totals_for_week(
            physical_variations, year, delivery_week
        )["station"]
        delivery_day_id = delivery_day.id
        totals_by_station: defaultdict[str, dict[str, int]] = defaultdict(dict)
        for (day_id, pv_id, station_key), total in station_variation_totals.items():
            if day_id == delivery_day_id:
                totals_by_station[station_key][pv_id] = total

        # Resolve the station-invariant active variations once; together with
        # the delivery_day already computed above, the per-station calls below
        # reuse them instead of re-querying the variation list + delivery_day
        # probe per station.
        hoisted_variations = PackingListService._active_share_type_variations(
            year, delivery_week, share_type, is_packed_bulk
        )

        rows: list[dict[str, Any]] = []
        for station_id in station_ids:
            station = stations_by_id.get(station_id)
            if station is None:
                continue

            station_packing_list = PackingListService.get_packing_list(
                year=year,
                delivery_week=delivery_week,
                day_number=day_number,
                share_type=share_type,
                is_past=is_past,
                delivery_station=station_id,
                is_packed_bulk=is_packed_bulk,
                _hoisted_variations=hoisted_variations,
                _hoisted_delivery_day=delivery_day,
            )
            if not station_packing_list:
                continue

            variation_keys = [
                k for k in station_packing_list[0] if k.startswith("variation_")
            ]

            variation_count_map: dict[str, int] = totals_by_station.get(station_id, {})

            for item in station_packing_list:
                # Keep the running total in Decimal end-to-end — ``float(amount)``
                # introduces binary-fp drift (e.g. 10.78 → 10.780000000000001)
                # that surfaces straight in the packing list. Amount is a
                # DecimalField (3dp); counts are ints.
                total_amount = Decimal("0")
                for variation_key in variation_keys:
                    variation_id = variation_key.replace("variation_", "")
                    amount_per_share = item.get(variation_key, 0) or 0
                    variation_count = variation_count_map.get(variation_id, 0)
                    total_amount += Decimal(str(amount_per_share)) * variation_count

                if total_amount <= 0:
                    continue

                pct = bulk_pct_by_article.get(item["share_article"]) or 0
                total_amount = quantize_weight(
                    total_amount * (Decimal(pct) / Decimal(100) + 1)
                )

                rows.append(
                    {
                        "id": f"{station.id}_{item['id']}",
                        "delivery_station": station.id,
                        "delivery_station_name": str(station),
                        "share_article": item["share_article"],
                        "share_article_name": item["share_article_name"],
                        "unit": item["unit"],
                        "size": item["size"],
                        # Decimal (3dp) — merged across share_types by the
                        # caller, which casts to float once at the boundary.
                        "total_amount": total_amount,
                        "note": item.get("note", ""),
                    }
                )

        return rows

    @staticmethod
    def get_packing_list_bulk(
        year: int,
        delivery_week: int,
        day_number: int,
        is_past: bool,
        share_type: str | None = None,
        delivery_station: str | None = None,
        is_packed_bulk: bool | None = None,
    ) -> list[dict[str, Any]]:
        """
        Per-delivery-station bulk packing list, summed across share_types.

        The bulk list answers "how much of each article does this station
        need on this delivery day" — a warehouse question that does not care
        which share_type an article belongs to. So ``share_type`` is optional:
        omit it to sum every share_type delivered that day, or pass one to
        scope the list to a single share_type.

        Rows for the same ``(delivery_station, share_article, unit, size)``
        coming from different share_types are merged by summing their
        ``total_amount``. Per-share_type totals are computed by
        ``_bulk_rows_for_share_type`` (see there for the physical-variation
        resolution and per-station amount handling).
        """
        if share_type is not None:
            share_type_ids: list[str] = [share_type]
        else:
            base_contents = ShareContent.active.for_period(is_past=is_past).filter(
                share__year=year,
                share__delivery_week=delivery_week,
                share__delivery_day__day_number=day_number,
            )
            if delivery_station is not None:
                base_contents = base_contents.filter(delivery_station=delivery_station)
            if is_packed_bulk is not None:
                base_contents = base_contents.filter(
                    share__share_type_variation__is_packed_bulk=is_packed_bulk
                )
            share_type_ids = list(
                base_contents.values_list(
                    "share__share_type_variation__share_type_id", flat=True
                )
                .distinct()
                .order_by("share__share_type_variation__share_type_id")
            )

        # Merge rows of equal (station, article, unit, size) — same ``id`` —
        # across share_types by summing the Decimal total_amount. The first
        # non-empty note wins (a per-article warehouse note is share_type-
        # independent; if two share_types disagree, one is kept).
        merged: dict[str, dict[str, Any]] = {}
        for share_type_id in share_type_ids:
            for row in PackingListService._bulk_rows_for_share_type(
                year=year,
                delivery_week=delivery_week,
                day_number=day_number,
                share_type=share_type_id,
                is_past=is_past,
                delivery_station=delivery_station,
                is_packed_bulk=is_packed_bulk,
            ):
                existing = merged.get(row["id"])
                if existing is None:
                    merged[row["id"]] = row
                else:
                    existing["total_amount"] += row["total_amount"]
                    if not existing["note"] and row["note"]:
                        existing["note"] = row["note"]

        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in merged.values():
            # Float at the boundary (the existing contract), computed from the
            # quantized Decimal sum — so the value is clean (no fp drift).
            row["total_amount"] = float(row["total_amount"])
            grouped[row["delivery_station_name"]].append(row)

        sorted_rows: list[dict[str, Any]] = []
        for station_name in sorted(grouped):
            sorted_rows.extend(sort_share_articles(grouped[station_name]))

        return sorted_rows

    @staticmethod
    def get_member_amounts_matrix(
        year: int,
        delivery_week: int,
        day_number: int,
        is_past: bool,
        delivery_station: str | None = None,
        tour: str | None = None,
        is_packed_bulk: bool | None = None,
    ) -> dict[str, Any]:
        """ "Was ihr nehmen könnt" — the per-SHARE amount matrix a member reads
        at a self-serve distribution.

        One column per active ``share_type_variation`` (grouped by share type,
        base types before additional "Zusatz" ones), one row per
        ``(share_article, unit, size)``, and each cell the amount a member of
        that variation may take (``ShareContent.amount`` — NOT multiplied by
        demand). The response mirrors the packing-boxes matrix
        (``{"columns", "rows"}`` with ``variation_<id>`` cell keys and empty
        ``add_ons``), so it reuses the same grouped-column matrix PDF.

        Reads ``ShareContent`` only — never ``ShareDelivery`` — so it works for
        subscription AND external-CSV (import) tenants.
        """
        active_at_date = saturday_of_iso_week(year, delivery_week)

        share_contents = ShareContent.active.for_period(is_past=is_past).filter(
            share__year=year,
            share__delivery_week=delivery_week,
            share__delivery_day__day_number=day_number,
        )
        if is_packed_bulk is not None:
            share_contents = share_contents.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )
        if delivery_station is not None:
            share_contents = share_contents.filter(delivery_station=delivery_station)

        if tour is not None:
            first = share_contents.first()
            delivery_day = first.share.delivery_day if first is not None else None
            station_ids = tour_station_ids(
                active_at_date, delivery_day=delivery_day, tour=tour
            )
            share_contents = share_contents.filter(delivery_station_id__in=station_ids)

        content_rows = share_contents.values(
            "share_article__id",
            "share_article__name",
            "unit",
            "size",
            "amount",
            "note",
            "share__delivery_day_id",
            "share__share_type_variation__id",
        ).order_by("share_article__name", "unit", "size")

        articles_dict: dict[str, dict[str, Any]] = {}
        present_variation_ids: set[str] = set()
        # All-stations safety net (no station scope): the same cell must not
        # carry two divergent per-share amounts within one delivery day —
        # mirrors ``get_packing_list``. The page always scopes to a station, so
        # this only trips on an explicit all-stations call with real divergence.
        seen_amounts: dict[tuple[str, str, int | None], Any] = {}
        for content in content_rows:
            variation_id = content["share__share_type_variation__id"]
            present_variation_ids.add(variation_id)
            composite_key = (
                f"{content['share_article__id']}_{content['unit']}_{content['size']}"
            )
            if composite_key not in articles_dict:
                articles_dict[composite_key] = {
                    "id": composite_key,
                    "share_article_id": content["share_article__id"],
                    "share_article_name": content["share_article__name"],
                    "unit": content["unit"] or "",
                    "size": content["size"] or "",
                    "note": content["note"] or "",
                }
            variation_key = f"variation_{variation_id}"
            amount = content["amount"] or 0
            if delivery_station is None:
                cell = (
                    composite_key,
                    variation_key,
                    content["share__delivery_day_id"],
                )
                record_amount(
                    seen_amounts,
                    cell,
                    amount,
                    article_id=content["share_article__id"],
                    unit=content["unit"],
                    size=content["size"],
                    variation_id=variation_id,
                )
            articles_dict[composite_key][variation_key] = amount

        # Drop rows where every variation cell is 0 (mirrors get_packing_list).
        filtered_rows = [
            row
            for row in articles_dict.values()
            if any(
                row.get(f"variation_{variation_id}", 0)
                for variation_id in present_variation_ids
            )
        ]

        columns = PackingListService._member_amount_columns(
            present_variation_ids, active_at_date
        )
        return {"columns": columns, "rows": sort_share_articles(filtered_rows)}

    @staticmethod
    def _member_amount_columns(
        variation_ids: set[str], active_at_date: Any
    ) -> list[dict[str, Any]]:
        """One column per variation (empty ``add_ons``), grouped by share type.
        Share types rank base-first (non-additional), then by their lightest
        variation's ``sort_order`` and name — so columns read
        "Gemüseanteil … | Zusatz …" like the packing-boxes matrix. Column dicts
        match ``PackingBoxesMatrixColumnSerializer``; ``count`` is always 0 (a
        member sheet has no box count)."""
        if not variation_ids:
            return []

        variations = list(
            ShareTypeVariation.current.active_at_date(active_at_date)
            .filter(id__in=variation_ids)
            .select_related("share_type")
            .annotate(size_order=size_order_annotation())
            .order_by("sort_order", "size_order")
        )

        # Rank share types: base (non-additional) groups first, then additional,
        # each by its lightest variation, name, id — a stable group order.
        share_type_rank_key: dict[str, tuple[Any, ...]] = {}
        for variation in variations:
            share_type = variation.share_type
            candidate = (
                share_type.is_additional_share_type,
                variation.sort_order,
                variation.size_order,
                share_type.name or "",
                str(share_type.id),
            )
            existing = share_type_rank_key.get(share_type.id)
            if existing is None or candidate < existing:
                share_type_rank_key[share_type.id] = candidate
        ranked_share_type_ids = sorted(
            share_type_rank_key, key=lambda st_id: share_type_rank_key[st_id]
        )
        share_type_rank = {
            st_id: index for index, st_id in enumerate(ranked_share_type_ids)
        }

        indexed_columns: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for variation in variations:
            share_type = variation.share_type
            column = {
                "key": f"variation_{variation.id}",
                "base_variation_id": variation.id,
                "base_size": variation.size or "",
                "base_sort_order": variation.sort_order,
                "base_share_type_id": share_type.id,
                "base_share_type_name": share_type.name or "",
                "base_share_type_short_name": (
                    share_type.short_name or share_type.name or ""
                ),
                "base_share_type_sort_index": share_type_rank[share_type.id],
                "add_ons": [],
                "count": 0,
            }
            sort_key = (
                share_type_rank[share_type.id],
                variation.sort_order,
                variation.size_order,
                column["key"],
            )
            indexed_columns.append((sort_key, column))

        indexed_columns.sort(key=lambda item: item[0])
        return [column for _sort_key, column in indexed_columns]
