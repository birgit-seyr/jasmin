"""Writes from the share-content planning page: the planned amounts in, the
share contents and their theoretical objects and movements rebuilt."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from ..errors import (
    CommissioningError,
    ShareArticleNotFound,
    ShareContentAlreadyPlanned,
    ShareContentError,
    ShareContentNotFound,
    SharesDeliveryDayNotFound,
    ShareTypeVariationNotFound,
)
from ..models import (
    DeliveryStation,
    DeliveryStationDay,
    Forecast,
    MovementShareArticle,
    Reseller,
    Share,
    ShareArticle,
    ShareContent,
    SharesDeliveryDay,
    ShareTypeVariation,
)
from ..models.choices import VegetableSizeOptions
from ..utils.dynamic_keys import DAY_VARIATION_RE, parse_amount_cell
from ..utils.iso_week_utils import saturday_of_iso_week
from .planning_slots import PlanningSlot
from .share_content_stock import ShareContentStock

# Row-level attributes a planning payload carries once for the whole slot. The
# rebuild stamps them onto every recreated ShareContent, so on a partial update
# a field the caller never sent has to be read back from the stored rows —
# otherwise it silently reverts to the column default (packing_station 1,
# washing / cleaning False, the rest NULL).
_SLOT_LEVEL_FIELDS = (
    "note",
    "seller",
    "kg_per_piece",
    "price_per_unit",
    "cleaning",
    "washing",
    "packing_station",
)

# ``ShareContent`` holds at most one of washing / cleaning
# (``sharecontent_washing_cleaning_mutually_exclusive``), so a payload that
# switches one on must not have the other carried over from storage — the
# rebuild would insert the pair the database refuses.
_EXCLUSIVE_SLOT_FLAGS = {"washing": "cleaning", "cleaning": "washing"}


def _create_unless_planned(contents: list[ShareContent]) -> list[ShareContent]:
    """Create ``contents``, refusing in words a row whose share, article,
    station, unit and size already have one: a page loaded before another tab
    or user planned the slot sends such rows, and the unique constraint would
    otherwise answer with a bare integrity error."""
    try:
        with transaction.atomic():
            return ShareContent.objects.bulk_create(contents)
    except IntegrityError as error:
        diag = getattr(error.__cause__, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if constraint != "sharecontent_unique_share_article_station_unit_size":
            raise
        raise ShareContentAlreadyPlanned(
            "This article is already planned in this unit and size for a share "
            "and station of the slot. Reload the page and change that entry."
        ) from error


def _merge_stored_slot_fields(
    data: dict[str, Any], stored_rows: QuerySet[ShareContent]
) -> dict[str, Any]:
    """Fill the slot-level fields *data* does not mention from the stored rows.

    Every row of a slot holds the same value for these — the rebuild writes one
    payload value to all of them — so the lowest-id row is representative.
    Switching washing or cleaning on clears the other instead of carrying it
    over, mirroring what the planning grid does when one is ticked.
    """
    stored = stored_rows.order_by("id").first()
    if stored is None:
        return data

    merged = dict(data)
    for field in _SLOT_LEVEL_FIELDS:
        if field in merged:
            continue
        opposite_flag = _EXCLUSIVE_SLOT_FLAGS.get(field)
        if opposite_flag is not None and merged.get(opposite_flag):
            merged[field] = False
            continue
        merged[field] = (
            stored.seller_id if field == "seller" else getattr(stored, field)
        )
    return merged


class ShareContentPlanning(ShareContentStock):
    """Create, replace, recompute, delete and back up planned share contents."""

    @transaction.atomic
    def process_share_planning_data(
        self,
        data: dict[str, Any],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
        replaced_movements: list[MovementShareArticle] | None = None,
    ) -> list[ShareContent]:
        """Process frontend data and create ShareContent + theoretical objects + movements.

        The theoretical and SHARECONTENT builders' snapshot cascades are
        collected and run as ONE union cascade at the end (a single sorted
        ``current_balance:*`` advisory-lock pass — two separate sorted passes
        could interleave with a concurrent writer and AB/BA-deadlock). When the
        caller passes ``collect_movements`` it takes over even that final
        cascade (``replace_share_planning`` folds the old movements in too).

        ``replaced_movements``: the movements of the contents this data
        replaces, whose actual corrections are re-derived once the new
        theoretical objects exist and before the SHARECONTENT movements are
        allocated, which read those corrections from the ledger.
        """
        year: int = data.get("year")
        delivery_week: int = data.get("delivery_week")
        share_article_id = data.get("share_article")
        unit: str | None = data.get("unit")
        size: str | None = data.get("size")
        note: str | None = data.get("note")
        seller_id = data.get("seller")
        cleaning: bool = data.get("cleaning", False)
        washing: bool = data.get("washing", False)
        kg_per_piece = data.get("kg_per_piece")
        price_per_unit = data.get("price_per_unit")
        packing_station: int = data.get("packing_station", 1)

        if not all([year, delivery_week, share_article_id]):
            raise CommissioningError(
                "Missing required fields: year, delivery_week, or share_article",
                code="share_content.missing_required",
            )

        active_at_date = saturday_of_iso_week(year, delivery_week)

        forecast = Forecast.objects.filter(
            year=year,
            delivery_week=delivery_week,
            share_article=share_article_id,
            unit=unit,
            size=size,
        ).first()

        day_variations = self._extract_day_variations(data)
        if not day_variations:
            # "All zero" is a valid update intent: the user cleared every
            # cell on this slot, which in this domain means "no human plan
            # any more" — the same state as a freshly forecast-scaffolded
            # row (amount IS NULL OR amount = 0; see
            # ``forecast_service._delete_orphaned_share_contents``). The
            # caller already wiped the slot's old rows before invoking
            # this path, so returning an empty list leaves the slot in
            # the unplanned state. Refusing to do this would force the
            # surrounding ``@transaction.atomic`` to roll the wipe back
            # and the user would silently see their cleared values
            # revert. The viewset's CREATE path enforces a non-empty
            # payload separately so a fresh ``POST`` with no amounts
            # still 400s.
            return []

        share_article = self._get_share_article(share_article_id)
        seller: Reseller | None = (
            Reseller.objects.get(id=seller_id) if seller_id is not None else None
        )

        # Pre-fetch ShareTypeVariation and SharesDeliveryDay to avoid N+1
        variation_ids = {v for _, v, _, _, _ in day_variations}
        day_ids = {d for d, _, _, _, _ in day_variations}

        variations_by_id = {
            str(v.id): v
            for v in ShareTypeVariation.objects.filter(id__in=variation_ids)
        }
        days_by_id = {
            str(d.id): d for d in SharesDeliveryDay.objects.filter(id__in=day_ids)
        }

        # Pre-fetch all station days for this week (avoids per-day query)
        all_station_days = list(
            DeliveryStationDay.current.active_at_date(active_at_date)
            .filter(delivery_station__is_active=True)
            .select_related("delivery_station")
        )
        station_days_by_day: dict[Any, list[DeliveryStationDay]] = {}
        for share_delivery in all_station_days:
            station_days_by_day.setdefault(share_delivery.delivery_day_id, []).append(
                share_delivery
            )

        # Map station IDs to DeliveryStation objects (avoids N+1 per station)
        station_by_id: dict[Any, DeliveryStation] = {
            share_delivery.delivery_station_id: share_delivery.delivery_station
            for share_delivery in all_station_days
        }

        share_contents_to_create: list[ShareContent] = []
        seen_share_station: set[tuple[Any, Any]] = set()

        for day_id, variation_id, amount, tour, station_id in day_variations:
            share_type_variation = variations_by_id.get(str(variation_id))
            if share_type_variation is None:
                raise ShareTypeVariationNotFound(
                    f"ShareTypeVariation with id {variation_id} does not exist",
                    details={"variation_id": variation_id},
                )
            share_delivery_day = days_by_id.get(str(day_id))
            if share_delivery_day is None:
                raise SharesDeliveryDayNotFound(
                    f"SharesDeliveryDay with id {day_id} does not exist",
                    details={"day_id": day_id},
                )

            share, _ = Share.get_or_create_for_delivery(
                share_type_variation=share_type_variation,
                year=year,
                delivery_week=delivery_week,
                delivery_day=share_delivery_day,
            )

            if station_id is not None:
                station = station_by_id.get(station_id)
                if station is None:
                    station = DeliveryStation.objects.get(id=station_id)
                resolved_stations = [station]
            elif tour is not None:
                resolved_stations = [
                    share_delivery.delivery_station
                    for share_delivery in station_days_by_day.get(
                        share_delivery_day.id, []
                    )
                    if share_delivery.tour_number == int(tour)
                ]
            else:
                resolved_stations = [
                    share_delivery.delivery_station
                    for share_delivery in station_days_by_day.get(
                        share_delivery_day.id, []
                    )
                ]

            for delivery_station in resolved_stations:
                key = (share.id, delivery_station.id)
                if key in seen_share_station:
                    raise ShareContentError(
                        f"Duplicate planning entry: share_article={share_article.id} "
                        f"unit={unit} size={size} resolves to the same delivery "
                        f"station ({delivery_station.id}) for share {share.id} more than "
                        f"once. Check for overlapping tour/station selections on "
                        f"day {day_id} / variation {variation_id}."
                    )
                seen_share_station.add(key)
                share_contents_to_create.append(
                    ShareContent(
                        share=share,
                        share_article=share_article,
                        amount=amount,
                        unit=unit,
                        size=size,
                        note=note,
                        seller=seller,
                        cleaning=cleaning,
                        washing=washing,
                        forecast=forecast,
                        delivery_station=delivery_station,
                        kg_per_piece=(
                            Decimal(str(kg_per_piece)) if kg_per_piece else None
                        ),
                        price_per_unit=(
                            Decimal(str(price_per_unit)) if price_per_unit else None
                        ),
                        packing_station=packing_station or 1,
                    )
                )

        share_contents = _create_unless_planned(share_contents_to_create)

        # Re-fetch with select_related to avoid N+1 in theoretical/movement creation
        share_contents = list(
            ShareContent.objects.filter(
                id__in=[share_content.id for share_content in share_contents]
            ).select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
            )
        )

        self._build_planned_movements(
            share_contents,
            collect_movements=collect_movements,
            replaced_movements=replaced_movements or [],
        )
        return share_contents

    def _build_planned_movements(
        self,
        share_contents: list[ShareContent],
        *,
        collect_movements: list[MovementShareArticle] | None,
        replaced_movements: list[MovementShareArticle],
    ) -> None:
        """The theoretical objects and SHARECONTENT movements of freshly saved
        ``share_contents``; see ``process_share_planning_data``."""
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        # Compute the demand totals once and share them — both builders
        # need the identical lookup.
        deferred_movements: list[MovementShareArticle] = (
            collect_movements if collect_movements is not None else []
        )
        variation_totals_by_week = self.variation_totals_by_week(share_contents)
        self.create_all_theoretical_objects(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )
        # A no-op without replaced movements.
        recalculate_actual_corrections(
            replaced_movements, collect_movements=deferred_movements
        )
        self.create_movements(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )
        if collect_movements is None and deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

    @transaction.atomic
    def recompute_for_shares(
        self,
        shares: Iterable[Share],
        *,
        collect_movements: list[MovementShareArticle] | None = None,
        replaced_movements: list[MovementShareArticle] | None = None,
    ) -> list[Any]:
        """Wipe + rebuild theoreticals and SHARECONTENT movements for ``shares``.

        Idempotent — safe to call any time the inputs change (ShareContent
        edited, ShareDelivery added/removed, Forecast updated, day-fields
        moved). Locks the affected ``Share`` rows for the duration of the
        transaction to prevent concurrent rebuilds from racing.

        Snapshot cascades are single-pass: every movement the rebuild touches
        (new theoreticals, new SHARECONTENT rows, re-derived corrections, and
        the captured OLD movements) is accumulated and cascaded ONCE at the
        end, so the per-entity ``current_balance:*`` advisory locks are
        acquired in one canonically-sorted pass. Cascading in three separate
        passes (theoretical → new → old) would not be globally sorted — two
        concurrent overlapping recomputes (or a recompute vs. a bulk stock write)
        could acquire the shared locks in opposite orders and AB/BA-deadlock.
        ``collect_movements`` hands even
        the final cascade to an enclosing caller that has more movements to
        fold into the same single pass.

        ``replaced_movements``: the movements of contents the caller deleted
        before recreating them on these shares; their actual corrections are
        re-derived with the shares' own old ones, under the Share locks and
        before the allocation. Shares without contents rebuild nothing and
        leave them to the caller.

        Returns the list of touched ``ShareContent`` ids (handy for tests
        and callers that want to invalidate caches).
        """
        # Local imports to keep the top-of-file lean and avoid cycles.
        from ..models import (
            TheoreticalCleanAmount,
            TheoreticalHarvest,
            TheoreticalPurchase,
            TheoreticalWashAmount,
        )

        share_ids = [s.id if hasattr(s, "id") else s for s in shares]
        if not share_ids:
            return []

        # Serialize concurrent recomputes for the same Share — without this,
        # two transactions touching the same Share could each delete + rebuild
        # at the same time and double-write movements. Lock in deterministic
        # (id) order so overlapping recomputes serialise without AB/BA-deadlocking
        # (Share declares no Meta.ordering, so the FOR UPDATE scan order is
        # otherwise plan-dependent).
        list(Share.objects.select_for_update().filter(id__in=share_ids).order_by("id"))

        share_contents = list(
            ShareContent.objects.filter(share_id__in=share_ids).select_related(
                "share__share_type_variation",
                "share__delivery_day",
                "share_article",
                "forecast",
                "seller",
                "delivery_station",
            )
        )
        if not share_contents:
            return []

        # Capture the OLD movements BEFORE the wipe so the rebuild can
        # re-cascade every storage a zeroed / relocated / date-shifted movement
        # strands. BOTH halves are captured: the SHARECONTENT rows AND the
        # theoretical HARVEST/PURCHASE/WASH/CLEAN movements — the latter carry
        # share_content=NULL (their source FK is ``theoretical_*``), so they are
        # reached via their Theoretical* parent's share_content link. The
        # rebuild's own cascades only cover the NEW storages, so an old
        # theoretical storage the rebuild relocates away from (e.g.
        # comes-from-long-term flips) would otherwise stay stranded.
        from .past_days import not_yet_past
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        old_movements = list(
            MovementShareArticle.objects.for_share_contents(share_contents)
        )

        # Theoreticals cascade-delete their is_theoretical=True
        # MovementShareArticle rows (FK on_delete=CASCADE). A harvest, washing
        # or cleaning amount of a day before today stays as it was.
        for model in (
            TheoreticalHarvest,
            TheoreticalWashAmount,
            TheoreticalCleanAmount,
        ):
            not_yet_past(
                model.objects.filter(share_content__in=share_contents)
            ).delete()
        TheoreticalPurchase.objects.filter(share_content__in=share_contents).delete()

        # SHARECONTENT-type movements point at ShareContent (which still
        # exists), so they don't cascade-delete — wipe them explicitly.
        MovementShareArticle.objects.filter(
            share_content__in=share_contents,
            movement_type="SHARECONTENT",
        ).delete()

        # Compute the demand totals once and share them — this is the
        # recompute hot path (a default-share-content save spans a whole
        # season of weeks) and the two builders need the identical lookup.
        deferred_movements: list[MovementShareArticle] = (
            collect_movements if collect_movements is not None else []
        )
        variation_totals_by_week = self.variation_totals_by_week(share_contents)
        self.create_all_theoretical_objects(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )

        old_movements.extend(replaced_movements or [])
        if old_movements:
            deferred_movements.extend(old_movements)
            # Re-derive actual harvest/purchase corrections for the OLD
            # theoretical dimensions too. create_theoretical_objects only recalcs
            # the dimensions of the NEW theoretical movements, so a dimension
            # whose theoreticals dropped to zero (demand gone) or relocated keeps
            # a stale correction (amount = counted − Σ_old) and its entity total
            # ≠ counted. Recomputing from the OLD dimensions re-derives them
            # against the CURRENT theoreticals (= 0 if gone) → entity total =
            # counted again. (SHARECONTENT keys in old_movements match no actual
            # correction, so they are harmless no-ops here.) It runs before the
            # SHARECONTENT movements are allocated, which read these corrections
            # from the ledger. The mutated corrections join the deferred union
            # instead of cascading here.
            recalculate_actual_corrections(
                old_movements, collect_movements=deferred_movements
            )

        self.create_movements(
            share_contents,
            variation_totals_by_week=variation_totals_by_week,
            collect_movements=deferred_movements,
        )

        # ONE cascade over everything the rebuild touched — old entities whose
        # movements were wiped/relocated, new theoretical + SHARECONTENT
        # entities, and re-derived corrections. cascade_for_movements sorts its
        # entity set, so this is the transaction's single, canonically-ordered
        # advisory-lock pass (unless an enclosing caller collects it).
        if collect_movements is None and deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

        return [share_content.id for share_content in share_contents]

    @transaction.atomic
    def replace_share_planning(
        self,
        *,
        slot: PlanningSlot,
        data: dict[str, Any],
        carry_over_unset_fields: bool = False,
    ) -> list[ShareContent]:
        """Replace the slot's existing ShareContent rows with freshly-created
        rows from `data`, then cascade snapshots for any movements affected by
        the deletion. Cells for another share option's variations are refused
        before anything is deleted.

        With ``carry_over_unset_fields`` (the PATCH path) a slot-level field the
        payload omits — washing, cleaning, packing_station, note, seller,
        kg_per_piece, price_per_unit — is taken from the stored rows instead of
        falling back to the column default. A full replace leaves it off.

        Empty payloads (``data`` carrying no usable day-variation cells —
        the user cleared every amount on the row) split into two cases:

        * Forecast-attached rows are KEPT, with ``amount`` reset to
          ``None``. The forecast is still asking for this row to exist;
          clearing the cells means "no human plan yet", not "remove the
          row". This preserves the row in the planning list so the user
          can fill it later.
        * Ad-hoc rows (no forecast link) are DELETED, since their only
          reason to exist was the human-typed amount that's now gone.

        Non-empty payloads keep the original wipe-and-rebuild semantics.
        """
        from .snapshot_service import SnapshotService
        from .theoretical_objects import recalculate_actual_corrections

        # The slot coordinates come from the caller (the composite pk), not the
        # body: a partial update needn't repeat them, and a body that disagreed
        # would rebuild into a different week than the one the wipe cleared.
        data = {
            **data,
            "year": slot.year,
            "delivery_week": slot.delivery_week,
            "share_article": slot.share_article_id,
            "unit": slot.unit,
            "size": slot.size,
        }

        old_share_contents = slot.share_contents()

        if carry_over_unset_fields:
            data = _merge_stored_slot_fields(data, old_share_contents)

        # Capture BOTH movement halves before the delete: the SHARECONTENT rows
        # AND the theoretical HARVEST/PURCHASE/WASH/CLEAN movements (these carry
        # share_content=NULL, reached via their Theoretical* parent's
        # share_content link). The wipe cascades the theoreticals away, so a
        # storage dimension this slot uniquely fed must still be re-cascaded and
        # its actual correction re-derived (mirrors delete_share_planning).
        old_movements = list(
            MovementShareArticle.objects.for_share_contents(old_share_contents)
        )

        day_variations = self._extract_day_variations(data)
        slot.refuse_cells_outside(day_variations)

        # Accumulate every movement the replace touches (the rebuild's new
        # movements, re-derived corrections, AND the captured old set) and
        # cascade ONCE — a single sorted ``current_balance:*`` advisory-lock
        # pass for the whole transaction instead of one pass per step.
        deferred_movements: list[MovementShareArticle] = []

        if not day_variations:
            # User cleared every cell. Spare forecast-attached rows so
            # the row stays visible (amount=None == "no human plan"); drop
            # the ad-hoc ones whose only purpose was the now-cleared
            # amount.
            affected_share_ids = set(
                old_share_contents.values_list("share_id", flat=True)
            )
            old_share_contents.filter(forecast__isnull=True).delete()
            old_share_contents.filter(forecast__isnull=False).update(amount=None)
            # The spared forecast rows now carry amount=None but still hold
            # theoreticals + SHARECONTENT movements built off the old
            # non-zero amount. Rebuild them so the cleared cells stop
            # contributing harvest/production demand, THEN cascade stock
            # snapshots — snapshots must be recomputed last, after the
            # movement set is corrected (mirrors the wipe-and-rebuild path).
            # The survivors first, which takes their Share rows before any
            # theoretical_sum lock, as every recompute does; they allocate
            # nothing of the cleared amounts.
            if affected_share_ids:
                from .recompute import recompute_shares

                recompute_shares(
                    affected_share_ids, collect_movements=deferred_movements
                )
            if old_movements:
                deferred_movements.extend(old_movements)
                # recompute_shares only re-derives the SURVIVING contents'
                # dimensions; a dropped ad-hoc row's uniquely-fed theoretical
                # storage (e.g. its own wash/clean storage) would keep a stale
                # actual correction. Re-derive over the captured 5-way set.
                recalculate_actual_corrections(
                    old_movements, collect_movements=deferred_movements
                )
            if deferred_movements:
                SnapshotService.cascade_for_movements(deferred_movements)
            # Re-fetch what survived so the response shows the cleared
            # forecast scaffold to the frontend.
            return list(slot.share_contents())

        # Preserve the backup plan across the wipe-and-rebuild. It lives on
        # ShareContent (backup_share_article/unit/size + backup_amount), but the
        # rebuild from ``data`` carries only the MAIN amounts — so without this,
        # editing any cell silently drops the row's whole backup plan. Key it by
        # the ShareContent's own identity within the slot, ``(share,
        # delivery_station)`` (its unique constraint), so a PER-STATION backup is
        # preserved exactly rather than collapsed onto a single value.
        preserved_backup: dict[tuple[str, str | None], tuple[Any, ...]] = {}
        for old in old_share_contents:
            if old.backup_share_article_id or old.backup_amount:
                preserved_backup[(old.share_id, old.delivery_station_id)] = (
                    old.backup_share_article_id,
                    old.backup_unit,
                    old.backup_size,
                    old.backup_amount,
                )

        old_share_contents.delete()
        share_contents = self.process_share_planning_data(
            data,
            collect_movements=deferred_movements,
            replaced_movements=old_movements,
        )

        # Re-stamp each rebuilt row from its matching (share, delivery_station).
        if preserved_backup:
            to_restamp = []
            for share_content in share_contents:
                backup = preserved_backup.get(
                    (share_content.share_id, share_content.delivery_station_id)
                )
                if backup is None:
                    continue
                (
                    share_content.backup_share_article_id,
                    share_content.backup_unit,
                    share_content.backup_size,
                    share_content.backup_amount,
                ) = backup
                to_restamp.append(share_content)
            if to_restamp:
                ShareContent.objects.bulk_update(
                    to_restamp,
                    [
                        "backup_share_article",
                        "backup_unit",
                        "backup_size",
                        "backup_amount",
                    ],
                )

        # The old movements' corrections were re-derived before the new
        # movements were allocated; their entities join the one cascade.
        deferred_movements.extend(old_movements)
        if deferred_movements:
            SnapshotService.cascade_for_movements(deferred_movements)

        return share_contents

    @transaction.atomic
    def delete_share_planning(self, *, slot: PlanningSlot) -> int:
        """Delete the slot's ShareContent rows and cascade snapshots.

        Returns the number of deleted rows. Raises `ShareContentNotFound` if no
        rows match.
        """
        from .snapshot_service import SnapshotService

        share_contents = slot.share_contents()

        if not share_contents.exists():
            raise ShareContentNotFound(
                "No share content found for the given parameters"
            )

        # Capture BOTH movement halves before the cascade-delete: the
        # SHARECONTENT rows AND the theoretical HARVEST/PURCHASE/WASH/CLEAN
        # movements (share_content=NULL, linked via their Theoretical* parent).
        # Deleting the content cascade-kills the theoretical rows from today on
        # + their movements, so a dimension whose theoreticals vanish would keep
        # a stale actual correction (entity total ≠ counted) — mirror
        # ``recompute_for_shares``.
        from .theoretical_objects import recalculate_actual_corrections

        affected_movements = list(
            MovementShareArticle.objects.for_share_contents(share_contents)
        )
        deleted_count = share_contents.count()
        share_contents.delete()

        if affected_movements:
            # Keep the global lock order theoretical_sum → current_balance: run
            # the theoretical-correction pass FIRST (it takes theoretical_sum
            # locks) but DEFER its current_balance cascade into ONE pass, instead
            # of cascading current_balance up front and re-locking it after
            # theoretical_sum — the AB/BA inversion every sibling path avoids.
            # Mirrors replace_share_planning / process_share_planning_data.
            deferred_movements = list(affected_movements)
            recalculate_actual_corrections(
                affected_movements, collect_movements=deferred_movements
            )
            SnapshotService.cascade_for_movements(deferred_movements)

        return deleted_count

    @transaction.atomic
    def update_backup_fields(
        self, *, slot: PlanningSlot, data: dict[str, Any]
    ) -> QuerySet[ShareContent]:
        """Update backup_* fields on the slot's ShareContent rows.

        `data` may contain `backup_share_article`, `backup_unit`, `backup_size`,
        and `day_{day_id}_variation_{var_id}` per-row backup amounts.
        Raises `ShareContentNotFound` if no rows match, or `ShareArticleNotFound`
        if the backup share article is invalid.
        """
        share_contents = slot.share_contents().select_related("share")

        if not share_contents.exists():
            raise ShareContentNotFound(
                "No share content found for the given parameters"
            )

        backup_share_article_id = data.get("backup_share_article")
        backup_share_article = None
        if backup_share_article_id:
            try:
                backup_share_article = ShareArticle.objects.get(
                    id=backup_share_article_id
                )
            except ShareArticle.DoesNotExist as exc:
                raise ShareArticleNotFound(
                    f"ShareArticle {backup_share_article_id} not found"
                ) from exc

        backup_unit = data.get("backup_unit") or None
        # The column can't be empty, so a cleared size takes its default.
        backup_size = data.get("backup_size") or VegetableSizeOptions.M

        backup_amounts: dict[tuple[str, str], Decimal] = {}
        for key, value in data.items():
            match = DAY_VARIATION_RE.match(key)
            if not match:
                continue
            day_id = match.group(1)
            var_id = match.group(2)
            if not value:
                # Falsy (0 / "" / None) means "no backup planned" — store 0.
                backup_amounts[(day_id, var_id)] = Decimal(0)
                continue
            backup_amounts[(day_id, var_id)] = parse_amount_cell(value, field=key)

        for share_content in share_contents:
            share_content.backup_share_article = backup_share_article
            share_content.backup_unit = backup_unit
            share_content.backup_size = backup_size

            day_id = str(share_content.share.delivery_day_id)
            var_id = str(share_content.share.share_type_variation_id)
            share_content.backup_amount = backup_amounts.get(
                (day_id, var_id), Decimal(0)
            )
            share_content.save(
                update_fields=[
                    "backup_share_article",
                    "backup_unit",
                    "backup_size",
                    "backup_amount",
                ]
            )

        return share_contents

    @staticmethod
    def _extract_day_variations(
        data: dict[str, Any],
    ) -> list[tuple[str, str, Decimal, str | None, str | None]]:
        """Extract day-variation combinations from frontend data.

        The frontend's planning row carries up to THREE parallel
        representations of the same data per ``(day, variation)``:

          * ``day_X_variation_Y``                 → bare row-level
                                                    amount (sum
                                                    across stations
                                                    /tours)
          * ``day_X_variation_Y_tour_N``          → per-tour amount
          * ``day_X_variation_Y_station_Z``       → per-station amount

        Depending on the active planning mode the form often
        propagates the user's single typed value into ALL three
        slots (so the row total displays consistently). If the
        backend trusts every slot, the bare entry collides with the
        specifics, AND a tour entry expands to all stations on that
        tour and collides with any explicit station entry — the
        downstream ``(share, station)`` dedupe in
        ``create_share_contents`` then raises "Duplicate planning
        entry …".

        Resolution: per ``(day, variation)`` group, pick the MOST
        SPECIFIC representation that was actually sent and drop the
        rest. Precedence:

            1. station-specific  (most precise — names a single
               delivery station explicitly)
            2. tour-specific     (mid — names a tour, fans to all
               stations on that tour)
            3. bare              (least — no tour or station,
               fans to every station on the day)

        Only the highest tier present in the group is emitted; the
        lower tiers are dropped as redundant.

        Zero-amount entries are also dropped at the source. ``0``
        semantically means "no plan for this tour/station", NOT
        "plan zero share content" — the frontend ships a zero-
        filled scaffold for every tour and station on every row
        regardless of what the user actually touched, and treating
        those zeros as real entries would (a) spawn phantom
        ``ShareContent`` rows and (b) cause the station collision this dedupe
        prevents.
        """
        # Walk once to collect every match. Track per-group whether
        # we saw any station-specific entry and whether we saw any
        # tour-specific entry, so the second pass knows which tier
        # to keep.
        all_entries: list[tuple[str, str, Decimal, str | None, str | None]] = []
        has_station_for_group: dict[tuple[str, str], bool] = {}
        has_tour_for_group: dict[tuple[str, str], bool] = {}

        for key, value in data.items():
            match = DAY_VARIATION_RE.match(key)
            if not match:
                continue

            if value is None or value == "" or value == "undefined":
                continue

            # Surface bad input as a 400 with the offending key — including the
            # well-formed-but-not-a-number strings "NaN"/"Infinity" — rather
            # than silently dropping it (the user sees "saved" but the row is
            # missing) or storing a garbage Decimal.
            amount = parse_amount_cell(value, field=key)

            # See docstring: zero is the scaffold default, never a
            # real plan.
            if amount == 0:
                continue

            day = match.group(1)
            variation = match.group(2)
            sub_type = match.group(3)
            sub_id = match.group(4)

            tour = sub_id if sub_type == "tour" else None
            station = sub_id if sub_type == "station" else None

            group_key = (day, variation)
            if station is not None:
                has_station_for_group[group_key] = True
            elif tour is not None:
                has_tour_for_group[group_key] = True

            all_entries.append((day, variation, amount, tour, station))

        # Second pass: emit only the highest-specificity tier present
        # for each (day, variation) group.
        day_variations: list[tuple[str, str, Decimal, str | None, str | None]] = []
        for entry in all_entries:
            day, variation, _amount, tour, station = entry
            group_key = (day, variation)

            if has_station_for_group.get(group_key):
                # Stations-tier group → keep ONLY station entries.
                if station is None:
                    continue
            elif has_tour_for_group.get(group_key):
                # Tours-tier group → keep ONLY tour entries.
                if tour is None:
                    continue
            # else: bare-only group → keep the bare entries.

            day_variations.append(entry)

        return day_variations

    @staticmethod
    def _get_share_article(share_article_id: str) -> ShareArticle:
        """Get ShareArticle by ID."""
        try:
            return ShareArticle.objects.get(id=share_article_id)
        except ShareArticle.DoesNotExist as exc:
            raise ShareArticleNotFound(
                f"ShareArticle with id {share_article_id} does not exist",
                details={"share_article_id": share_article_id},
            ) from exc
