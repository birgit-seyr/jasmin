"""Packing boxes MATRIX — one column per box COMBINATION.

Where :class:`PackingListService.get_packing_list` pivots ShareContent by
individual share_type_variation (one column per variation, scoped to a single
share_type), this service pivots by the distinct box *combination* that
actually occurs across all share types: a base (non-additional) box plus the
additional shares ("Zusatz") physically packed into it.

The "combination" is not a stored concept — it is derived by grouping the
week's shippable ``ShareDelivery`` rows per ``(member, delivery_station_day)``:
within one such group the non-additional delivery is the base box and the
additional ones are packed into it. Only combinations that occur produce a
column (no cartesian blow-up).

Output shape (consumed by ``PackingListBoxes.tsx``)::

    {
      "columns": [ { key, base_variation_id, base_size, base_sort_order,
                     base_share_type_id, base_share_type_name,
                     base_share_type_sort_index, add_ons: [...], count } ],
      "rows":    [ { id, share_article_id, share_article_name, unit, size,
                     note, "<combo_key>": <per-box quantity>, ... } ],
    }

Each cell is the per-BOX quantity of that article in that combination (base
contents + add-on contents); the per-combination ``count`` is rendered by the
frontend as the pinned first row.

Known v1 limitation (``get_boxes_matrix`` ONLY): base / add-on variations are
assumed PHYSICAL for the per-article amounts. A virtual variation
(``variation_type="virtual"``) has no ShareContent rows of its own, so its
ARTICLE cells read as empty — resolving virtual variations into their physical
components (as the bulk path does) is a follow-up. This does NOT affect
``get_station_member_matrix``: that path never reads ShareContent, it only
counts boxes per member, so a virtual variation still yields correct per-member
box counts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from isoweek import Week

from ..errors import PackingAmountsDivergeAcrossStations
from ..models import DeliveryStationDay, ShareContent, ShareDelivery
from ..models.choices_text import SizeOptions

# (article_id, unit, size, variation_id) -> per-box amount
_AmountByCell = dict[tuple[str, str, str, str], Decimal]
# (article_id, unit, size) -> stable row metadata
_ArticleMeta = dict[tuple[str, str, str], dict[str, Any]]
# (base_variation_id | None, sorted add-on variation ids)
_Signature = tuple["str | None", tuple[str, ...]]

# Rank each SizeOptions code by its declared order (XS < S < M < L < …) so a
# size tie-break sorts naturally. ``size`` is a plain CharField — there is NO
# ``size_order`` column on ShareTypeVariation — so the ordering is derived here.
_SIZE_ORDER: dict[str, int] = {
    choice: index for index, choice in enumerate(SizeOptions.values)
}


def _size_rank(size: str | None) -> int:
    return _SIZE_ORDER.get(size or "", 999)


# One box in a member-group: the delivered variation + how many identical
# boxes the subscription is (quantity), plus the flags we split/order on.
class _BoxLine:
    __slots__ = ("variation", "share_type", "is_additional", "quantity")

    def __init__(self, variation, share_type, quantity: int) -> None:
        self.variation = variation
        self.share_type = share_type
        self.is_additional = share_type.is_additional_share_type
        self.quantity = quantity


class PackingListBoxesMatrixService:
    @classmethod
    def get_boxes_matrix(
        cls,
        year: int,
        delivery_week: int,
        day_number: int,
        is_past: bool = False,
        delivery_station: str | None = None,
        tour: str | None = None,
        is_packed_bulk: bool | None = None,
    ) -> dict[str, Any]:
        active_at_date = Week(year, delivery_week).saturday()

        tour_station_ids: list[str] | None = None
        if tour is not None:
            tour_station_ids = list(
                DeliveryStationDay.current.active_at_date(active_at_date)
                .filter(delivery_day__day_number=day_number, tour_number=tour)
                .values_list("delivery_station_id", flat=True)
            )

        combinations, variation_by_id = cls._derive_combinations(
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            delivery_station=delivery_station,
            tour_station_ids=tour_station_ids,
            is_packed_bulk=is_packed_bulk,
        )

        amount_by_cell, article_meta = cls._collect_amounts(
            year=year,
            delivery_week=delivery_week,
            day_number=day_number,
            is_past=is_past,
            delivery_station=delivery_station,
            tour_station_ids=tour_station_ids,
            is_packed_bulk=is_packed_bulk,
            variation_ids=list(variation_by_id.keys()),
        )

        columns = cls._build_columns(combinations, variation_by_id)
        rows = cls._build_rows(columns, amount_by_cell, article_meta)
        return {"columns": columns, "rows": rows}

    @classmethod
    def get_station_member_matrix(
        cls,
        year: int,
        delivery_week: int,
        day_number: int,
        delivery_station: str,
        is_packed_bulk: bool | None = None,
    ) -> dict[str, Any]:
        """Member × combination matrix for ONE station: one row per member, one
        column per box combination, each cell the number of that member's boxes
        of that combination. Reuses the packing-matrix combination derivation
        (``_boxes_for_group`` + ``_build_columns``), so DeliveryStationDetails
        renders the exact same combination columns as the packing list.
        """
        deliveries = (
            ShareDelivery.objects.shippable()
            .filter(
                share__year=year,
                share__delivery_week=delivery_week,
                share__delivery_day__day_number=day_number,
                subscription__isnull=False,
                delivery_station_day__isnull=False,
                delivery_station_day__delivery_station_id=delivery_station,
            )
            .select_related(
                "subscription__member",
                "share__share_type_variation__share_type",
            )
        )
        if is_packed_bulk is not None:
            deliveries = deliveries.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )

        variation_by_id: dict[str, Any] = {}
        member_lines: defaultdict[str, list[_BoxLine]] = defaultdict(list)
        member_names: dict[str, str] = {}
        for delivery in deliveries:
            variation = delivery.share.share_type_variation
            variation_by_id[variation.id] = variation
            member = delivery.subscription.member
            member_names[member.id] = member.display_name or str(member)
            member_lines[member.id].append(
                _BoxLine(
                    variation,
                    variation.share_type,
                    delivery.subscription.quantity or 1,
                )
            )

        combinations: Counter = Counter()
        member_signature_counts: dict[str, Counter] = {}
        for member_id, lines in member_lines.items():
            signature_counts: Counter = Counter()
            for signature, boxes in cls._boxes_for_group(lines):
                signature_counts[signature] += boxes
                combinations[signature] += boxes
            member_signature_counts[member_id] = signature_counts

        columns = cls._build_columns(combinations, variation_by_id)
        rows: list[dict[str, Any]] = []
        for member_id in sorted(
            member_names, key=lambda mid: member_names[mid].lower()
        ):
            row: dict[str, Any] = {"id": member_id, "name": member_names[member_id]}
            for signature, count in member_signature_counts[member_id].items():
                row[cls._column_key(signature[0], signature[1])] = count
            rows.append(row)

        return {"columns": columns, "rows": rows}

    @classmethod
    def get_station_combination_counts(
        cls,
        year: int,
        delivery_week: int,
        day_number: int,
        is_packed_bulk: bool | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
        """Per-STATION box-combination counts for a whole delivery day (every
        station / tour). Returns ``(columns, {delivery_station_id: {column_key:
        box_count}})`` — the DeliveryStations overview renders one row per
        station with the SAME combination columns as the packing list, each cell
        the number of boxes of that combination shipping to that station.

        Reuses the packing-matrix combination derivation (group by
        ``(member, station)`` → ``_boxes_for_group`` → ``_build_columns``), so
        the overview, the packing list and DeliveryStationDetails all share one
        column definition.
        """
        deliveries = (
            ShareDelivery.objects.shippable()
            .filter(
                share__year=year,
                share__delivery_week=delivery_week,
                share__delivery_day__day_number=day_number,
                subscription__isnull=False,
                delivery_station_day__isnull=False,
            )
            .select_related(
                "subscription",
                "share__share_type_variation__share_type",
                "delivery_station_day",
            )
        )
        if is_packed_bulk is not None:
            deliveries = deliveries.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )

        variation_by_id: dict[str, Any] = {}
        groups: defaultdict[tuple[str, str], list[_BoxLine]] = defaultdict(list)
        for delivery in deliveries:
            variation = delivery.share.share_type_variation
            variation_by_id[variation.id] = variation
            station_id = delivery.delivery_station_day.delivery_station_id
            groups[(delivery.subscription.member_id, station_id)].append(
                _BoxLine(
                    variation, variation.share_type, delivery.subscription.quantity or 1
                )
            )

        combinations: Counter = Counter()
        station_signature_counts: defaultdict[str, Counter] = defaultdict(Counter)
        for (_member_id, station_id), lines in groups.items():
            for signature, boxes in cls._boxes_for_group(lines):
                station_signature_counts[station_id][signature] += boxes
                combinations[signature] += boxes

        columns = cls._build_columns(combinations, variation_by_id)
        counts_by_station: dict[str, dict[str, int]] = {
            station_id: {
                cls._column_key(signature[0], signature[1]): count
                for signature, count in signature_counts.items()
            }
            for station_id, signature_counts in station_signature_counts.items()
        }
        return columns, counts_by_station

    # ── Step A/B: derive the box combinations + their counts ──────────────
    @classmethod
    def _derive_combinations(
        cls,
        *,
        year: int,
        delivery_week: int,
        day_number: int,
        delivery_station: str | None,
        tour_station_ids: list[str] | None,
        is_packed_bulk: bool | None,
    ) -> tuple[Counter, dict[str, Any]]:
        """Group shippable deliveries into physical boxes and count each
        distinct ``(base_variation, frozenset(addon_variations))`` signature.

        Returns ``(Counter[signature] -> box count, {variation_id: variation})``.
        """
        deliveries = (
            ShareDelivery.objects.shippable()
            .filter(
                share__year=year,
                share__delivery_week=delivery_week,
                share__delivery_day__day_number=day_number,
                subscription__isnull=False,
                # A NULL station-day can't identify a physical box; without this
                # every such row collapses into one bogus group.
                delivery_station_day__isnull=False,
            )
            .select_related(
                "subscription",
                "share__share_type_variation__share_type",
                "delivery_station_day",
            )
        )
        if delivery_station is not None:
            deliveries = deliveries.filter(
                delivery_station_day__delivery_station_id=delivery_station
            )
        elif tour_station_ids is not None:
            deliveries = deliveries.filter(
                delivery_station_day__delivery_station_id__in=tour_station_ids
            )
        if is_packed_bulk is not None:
            deliveries = deliveries.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )

        variation_by_id: dict[str, Any] = {}
        # A physical box = one member's pickup at one delivery STATION on the
        # queried day (year/week/day are already fixed by the filter above). We
        # group by (member, delivery_station) rather than by the specific
        # DeliveryStationDay row so a member's base + add-ons combine as long as
        # they ship to the same station that day — robust to DSD succession.
        # (A single active DSD per (station, day) makes the two equivalent today.)
        groups: defaultdict[tuple[str, str], list[_BoxLine]] = defaultdict(list)
        for delivery in deliveries:
            variation = delivery.share.share_type_variation
            share_type = variation.share_type
            variation_by_id[variation.id] = variation
            station_id = delivery.delivery_station_day.delivery_station_id
            groups[(delivery.subscription.member_id, station_id)].append(
                _BoxLine(variation, share_type, delivery.subscription.quantity or 1)
            )

        counter: Counter = Counter()
        for lines in groups.values():
            for signature, boxes in cls._boxes_for_group(lines):
                counter[signature] += boxes
        return counter, variation_by_id

    @classmethod
    def _boxes_for_group(cls, lines: list[_BoxLine]) -> list[tuple[_Signature, int]]:
        """Turn one member's (member, station-day) deliveries into counted box
        signatures.

        Rules:
        - Add-ons ride the base whose variation has the greatest
          ``average_weight`` (tie-break: lower ``sort_order``, then id). Every
          other base becomes its own base-only box.
        - ``quantity`` expands to that many identical boxes; add-ons are nested
          into the fullest boxes first (a base×2 + add-on×1 = one combined box
          + one base-only box, not two combined boxes). N units of ONE add-on
          variation spread one-per-box regardless of how many subscription
          lines carry them.
        - Add-on units with no base to ride — no base at all, or more add-on
          units than the base has boxes — become visible "no base" boxes rather
          than being silently dropped.
        """
        bases = [line for line in lines if not line.is_additional]
        addons = [line for line in lines if line.is_additional]

        # Aggregate per add-on VARIATION: two lines of the same add-on are N
        # units of one add-on (spread across boxes), not two add-ons stacked.
        addon_totals: Counter = Counter()
        for addon in addons:
            addon_totals[addon.variation.id] += addon.quantity

        if not bases:
            if not addon_totals:
                return []
            # Orphan add-ons: synthetic "no base" boxes, nested fullest-first.
            return cls._nest_boxes(None, addon_totals, max(addon_totals.values()))

        primary = sorted(bases, key=cls._primary_base_key)[0]
        result: list[tuple[_Signature, int]] = []

        # Other bases are plain base-only boxes.
        for base in bases:
            if base is primary:
                continue
            result.append(((base.variation.id, ()), base.quantity))

        base_boxes = primary.quantity
        # Add-ons ride the primary base's boxes, fullest-first, capped at the
        # base's box count.
        on_base = Counter(
            {vid: min(qty, base_boxes) for vid, qty in addon_totals.items()}
        )
        result.extend(cls._nest_boxes(primary.variation.id, on_base, base_boxes))

        # Add-on units beyond the base's box count have no base box to ride;
        # surface them as visible no-base boxes rather than dropping them.
        overflow = Counter(
            {
                vid: qty - base_boxes
                for vid, qty in addon_totals.items()
                if qty > base_boxes
            }
        )
        if overflow:
            result.extend(cls._nest_boxes(None, overflow, max(overflow.values())))
        return result

    @staticmethod
    def _nest_boxes(
        base_variation_id: str | None, addon_totals: Counter, box_count: int
    ) -> list[tuple[_Signature, int]]:
        """Distribute add-ons across ``box_count`` boxes fullest-first: box
        ``j`` carries every add-on whose count exceeds ``j``. Boxes with no
        add-on left are plain ``(base, ())`` boxes. Returns
        ``[(signature, count), ...]``."""
        signature_counts: Counter = Counter()
        for box_index in range(box_count):
            present = tuple(
                sorted(
                    variation_id
                    for variation_id, count in addon_totals.items()
                    if box_index < count
                )
            )
            signature_counts[(base_variation_id, present)] += 1
        return list(signature_counts.items())

    @staticmethod
    def _primary_base_key(line: _BoxLine) -> tuple[Decimal, int, str]:
        variation = line.variation
        weight = (
            variation.average_weight
            if variation.average_weight is not None
            else Decimal("-1")
        )
        # Ascending sort → the heaviest base (most negative -weight) sorts first;
        # tie-break on lower sort_order, then stable id.
        return (-weight, variation.sort_order, str(variation.id))

    # ── Step C: per-combination article amounts from ShareContent ─────────
    @classmethod
    def _collect_amounts(
        cls,
        *,
        year: int,
        delivery_week: int,
        day_number: int,
        is_past: bool,
        delivery_station: str | None,
        tour_station_ids: list[str] | None,
        is_packed_bulk: bool | None,
        variation_ids: list[str],
    ) -> tuple[_AmountByCell, _ArticleMeta]:
        """Per-(article, unit, size, variation) amount map + per-article-row
        metadata. One query, no N+1.
        """
        amount_by_cell: _AmountByCell = {}
        article_meta: _ArticleMeta = {}
        if not variation_ids:
            return amount_by_cell, article_meta

        contents = ShareContent.active.for_period(is_past=is_past).filter(
            share__year=year,
            share__delivery_week=delivery_week,
            share__delivery_day__day_number=day_number,
            share__share_type_variation_id__in=variation_ids,
        )
        if is_packed_bulk is not None:
            contents = contents.filter(
                share__share_type_variation__is_packed_bulk=is_packed_bulk
            )
        if delivery_station is not None:
            contents = contents.filter(delivery_station=delivery_station)
        elif tour_station_ids is not None:
            contents = contents.filter(delivery_station_id__in=tour_station_ids)

        rows = contents.values(
            "share_article__id",
            "share_article__name",
            "unit",
            "size",
            "note",
            "share__share_type_variation_id",
            "share__share_type_variation__share_type__is_additional_share_type",
            "share__delivery_day_id",
            "amount",
        )

        # Guard the all-stations view: the same (article, unit, size, variation)
        # can receive rows from several stations. Collapsing keeps one, which is
        # only correct when the amounts AGREE — else refuse loudly. Keyed by
        # delivery_day too (mirrors PackingListService): two delivery days
        # sharing a packing day may legitimately differ.
        seen: dict[tuple[str, str, str, str, str], Decimal] = {}
        for row in rows:
            article_key = (row["share_article__id"], row["unit"], row["size"])
            if article_key not in article_meta:
                article_meta[article_key] = {
                    "share_article_id": row["share_article__id"],
                    "share_article_name": row["share_article__name"],
                    "unit": row["unit"],
                    "size": row["size"],
                    "note": row["note"] or "",
                    # Base article iff it appears in ANY non-additional (base)
                    # variation; else it's a Zusatz-only article. Drives row
                    # order (base articles first, then Zusatz articles).
                    "_has_base": False,
                }
            if not row[
                "share__share_type_variation__share_type__is_additional_share_type"
            ]:
                article_meta[article_key]["_has_base"] = True
            variation_id = row["share__share_type_variation_id"]
            amount = row["amount"] or Decimal("0")
            if delivery_station is None:
                guard_key = (*article_key, variation_id, row["share__delivery_day_id"])
                if guard_key in seen and seen[guard_key] != amount:
                    raise PackingAmountsDivergeAcrossStations(
                        share_article_id=row["share_article__id"],
                        unit=row["unit"],
                        size=row["size"],
                        variation_id=variation_id,
                        amounts=[seen[guard_key], amount],
                    )
                seen[guard_key] = amount
            amount_by_cell[(*article_key, variation_id)] = amount
        return amount_by_cell, article_meta

    # ── Step D/E: assemble columns + rows ─────────────────────────────────
    @classmethod
    def _build_columns(
        cls, combinations: Counter, variation_by_id: dict[str, Any]
    ) -> list[dict[str, Any]]:
        base_rank = cls._rank_base_share_types(combinations, variation_by_id)
        addon_rank = cls._rank_addon_share_types(combinations, variation_by_id)

        columns: list[dict[str, Any]] = []
        for (base_variation_id, addon_ids), count in combinations.items():
            add_ons = sorted(
                (
                    cls._addon_payload(variation_by_id[aid], addon_rank)
                    for aid in addon_ids
                ),
                key=lambda addon: (
                    addon["share_type_sort_index"],
                    addon["sort_order"],
                    _size_rank(addon["size"]),
                ),
            )
            if base_variation_id is None:
                columns.append(
                    {
                        "key": cls._column_key(None, addon_ids),
                        "base_variation_id": None,
                        "base_size": "",
                        "base_sort_order": 0,
                        "base_share_type_id": None,
                        "base_share_type_name": "",
                        "base_share_type_short_name": "",
                        # Orphan "no base" group sorts after every real base.
                        "base_share_type_sort_index": len(base_rank),
                        "add_ons": add_ons,
                        "count": count,
                    }
                )
                continue
            base_variation = variation_by_id[base_variation_id]
            base_share_type = base_variation.share_type
            columns.append(
                {
                    "key": cls._column_key(base_variation_id, addon_ids),
                    "base_variation_id": base_variation_id,
                    "base_size": base_variation.size or "",
                    "base_sort_order": base_variation.sort_order,
                    "base_share_type_id": base_share_type.id,
                    "base_share_type_name": base_share_type.name or "",
                    "base_share_type_short_name": (
                        base_share_type.short_name or base_share_type.name or ""
                    ),
                    "base_share_type_sort_index": base_rank[base_share_type.id],
                    "add_ons": add_ons,
                    "count": count,
                }
            )

        columns.sort(
            key=lambda column: (
                column["base_share_type_sort_index"],
                column["base_sort_order"],
                _size_rank(column["base_size"]),
                len(column["add_ons"]),
                column["key"],
            )
        )
        return columns

    @staticmethod
    def _rank_base_share_types(
        combinations: Counter, variation_by_id: dict[str, Any]
    ) -> dict[str, int]:
        # ShareType has no sort field; rank base share types by their lightest
        # base variation's sort_order, then name, for a stable group order.
        share_types: dict[str, Any] = {}
        min_sort: dict[str, int] = {}
        for base_variation_id, _addon_ids in combinations:
            if base_variation_id is None:
                continue
            variation = variation_by_id[base_variation_id]
            share_type = variation.share_type
            share_types[share_type.id] = share_type
            min_sort[share_type.id] = min(
                min_sort.get(share_type.id, variation.sort_order),
                variation.sort_order,
            )
        ranked = sorted(
            share_types.values(),
            key=lambda st: (min_sort[st.id], st.name or "", str(st.id)),
        )
        return {st.id: index for index, st in enumerate(ranked)}

    @staticmethod
    def _rank_addon_share_types(
        combinations: Counter, variation_by_id: dict[str, Any]
    ) -> dict[str, int]:
        share_types: dict[str, Any] = {}
        for _base_variation_id, addon_ids in combinations:
            for addon_id in addon_ids:
                share_type = variation_by_id[addon_id].share_type
                share_types[share_type.id] = share_type
        ranked = sorted(
            share_types.values(),
            key=lambda st: (st.name or "", str(st.id)),
        )
        return {st.id: index for index, st in enumerate(ranked)}

    @staticmethod
    def _addon_payload(variation, addon_rank: dict[str, int]) -> dict[str, Any]:
        share_type = variation.share_type
        return {
            "variation_id": variation.id,
            "size": variation.size or "",
            "sort_order": variation.sort_order,
            "share_type_id": share_type.id,
            "share_type_short_name": share_type.short_name or share_type.name or "",
            "share_type_sort_index": addon_rank[share_type.id],
        }

    @staticmethod
    def _column_key(base_variation_id: str | None, addon_ids: tuple[str, ...]) -> str:
        return f"combo_{base_variation_id or 'none'}|{'-'.join(addon_ids)}"

    @classmethod
    def _build_rows(
        cls,
        columns: list[dict[str, Any]],
        amount_by_cell: _AmountByCell,
        article_meta: _ArticleMeta,
    ) -> list[dict[str, Any]]:
        # Each column's variations = base + add-ons.
        column_variations: list[tuple[str, list[str]]] = []
        for column in columns:
            variation_ids = [addon["variation_id"] for addon in column["add_ons"]]
            if column["base_variation_id"] is not None:
                variation_ids.append(column["base_variation_id"])
            column_variations.append((column["key"], variation_ids))

        # Row order: base articles first (alphabetical by name), then the
        # Zusatz-only articles (alphabetical). ``_has_base`` is set in
        # ``_collect_amounts``; unit/size are stable tie-breakers.
        ordered_meta = sorted(
            article_meta.items(),
            key=lambda item: (
                not item[1]["_has_base"],
                (item[1]["share_article_name"] or "").lower(),
                item[1]["unit"] or "",
                item[1]["size"] or "",
            ),
        )

        rows: list[dict[str, Any]] = []
        for article_key, meta in ordered_meta:
            row: dict[str, Any] = {
                "id": f"{meta['share_article_id']}_{meta['unit']}_{meta['size']}",
                "share_article_id": meta["share_article_id"],
                "share_article_name": meta["share_article_name"],
                "unit": meta["unit"],
                "size": meta["size"],
                "note": meta["note"],
            }
            has_value = False
            for column_key, variation_ids in column_variations:
                total = Decimal("0")
                for variation_id in variation_ids:
                    total += amount_by_cell.get(
                        (*article_key, variation_id), Decimal("0")
                    )
                if total > 0:
                    has_value = True
                # Quantities (not money): a clean float at the boundary.
                row[column_key] = float(total)
            if has_value:
                rows.append(row)

        return rows
