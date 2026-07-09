"""
Shared helpers for creating theoretical objects (TheoreticalHarvest,
TheoreticalPurchase, TheoreticalWashAmount, TheoreticalCleanAmount)
from both ShareContent and OrderContent sources.

After bulk-creating the theoretical objects, this module also creates
the corresponding *theoretical movements* (``is_theoretical=True``) so
that stock calculations include planning data automatically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any, NamedTuple

from django.db import transaction

from ..constants import PURCHASE_DAY
from ..models import (
    CleanAmount,
    Harvest,
    MovementShareArticle,
    Purchase,
    Storage,
    TheoreticalCleanAmount,
    TheoreticalHarvest,
    TheoreticalPurchase,
    TheoreticalWashAmount,
    WashAmount,
)
from ..utils.iso_week_utils import compute_rolled_back_week, make_noon_datetime

logger = logging.getLogger(__name__)

_AMOUNT_PER_PU_MAP: dict[str, str] = {
    "KG": "default_kg_per_pu_harvest",
    "PCS": "default_pieces_per_pu_harvest",
    "BUNCH": "default_bunches_per_pu_harvest",
}


# ──────────────────────────────────────────────────────
# Unified descriptor for a source item (ShareContent or OrderContent)
# ──────────────────────────────────────────────────────


class TheoreticalSourceData:
    """Normalised view of a ShareContent or OrderContent for theoretical object creation."""

    def __init__(
        self,
        *,
        year: int,
        delivery_week: int,
        delivery_day: int,
        harvesting_day: int | None,
        washing_day: int | None,
        cleaning_day: int | None,
        share_article,
        amount,
        unit: str | None,
        size: str | None,
        note: str | None,
        washing: bool,
        cleaning: bool,
        forecast=None,
        seller=None,
        is_purchased: bool = False,
        # One of these will be set
        share_content=None,
        order_content=None,
        storage: Storage | None = None,
        # For share_contents: pre-computed total amount (amount * total_quantity)
        total_amount_for_shares=None,
        # For share_contents: size from forecast
        harvest_size: str | None = None,
        comes_from_long_term_storage: bool = False,
    ):
        self.year = year
        self.delivery_week = delivery_week
        self.delivery_day = delivery_day
        self.harvesting_day = harvesting_day
        self.washing_day = washing_day
        self.cleaning_day = cleaning_day
        self.share_article = share_article
        self.amount = amount
        self.unit = unit
        self.size = size
        self.note = note
        self.washing = washing
        self.cleaning = cleaning
        self.forecast = forecast
        self.seller = seller
        self.is_purchased = is_purchased
        self.share_content = share_content
        self.order_content = order_content
        self.storage = storage
        self.total_amount_for_shares = (
            total_amount_for_shares if total_amount_for_shares is not None else amount
        )
        self.harvest_size = harvest_size if harvest_size is not None else size
        self.comes_from_long_term_storage = comes_from_long_term_storage

    @property
    def has_forecast(self) -> bool:
        return self.forecast is not None

    @property
    def needs_harvest(self) -> bool:
        # A purchased article is supplied via TheoreticalPurchase, never
        # harvested — even if it ALSO carries a Forecast row (planning can
        # attach one). Without the ``not is_purchased`` guard both a harvest AND
        # a purchase are built for it, supplying the same demand twice
        # (goods-flow audit #4). ``needs_harvest`` / ``needs_purchase`` are thus
        # mutually exclusive.
        return self.has_forecast and not self.is_purchased

    @property
    def needs_purchase(self) -> bool:
        return self.is_purchased

    @property
    def needs_wash(self) -> bool:
        return bool(self.washing)

    @property
    def needs_clean(self) -> bool:
        return bool(self.cleaning)

    @property
    def has_positive_amount(self) -> bool:
        return bool(self.amount and self.amount > 0)

    @property
    def content_kwargs(self) -> dict[str, Any]:
        """Return the FK kwarg pointing to the source (share_content or order_content)."""
        if self.share_content is not None:
            return {"share_content": self.share_content}
        return {"order_content": self.order_content}


# ──────────────────────────────────────────────────────
# Builder functions for individual theoretical objects
# ──────────────────────────────────────────────────────


def _build_theoretical_harvest(src: TheoreticalSourceData) -> TheoreticalHarvest | None:
    if src.harvesting_day is None:
        return None

    harvest_year, harvest_week = compute_rolled_back_week(
        src.year,
        src.delivery_week,
        src.harvesting_day,
        src.delivery_day,
    )

    return TheoreticalHarvest(
        year=harvest_year,
        delivery_week=harvest_week,
        day_number=src.harvesting_day,
        share_article=src.share_article,
        amount=src.total_amount_for_shares,
        unit=src.unit,
        size=src.harvest_size,
        forecast=src.forecast,
        note=src.note,
        storage=src.storage,
        **src.content_kwargs,
    )


def _ensure_harvest_placeholder(
    src: TheoreticalSourceData, harvest_year: int, harvest_week: int
) -> None:
    """Create or update the placeholder Harvest row (for the harvesting list)."""
    harvest, _ = Harvest.objects.get_or_create(
        year=harvest_year,
        delivery_week=harvest_week,
        day_number=src.harvesting_day,
        share_article=src.share_article,
        unit=src.unit,
        size=src.size,
        storage=src.storage,
        defaults={"amount": None},
    )

    amount_per_pu_attr = _AMOUNT_PER_PU_MAP.get(src.unit)
    harvest.harvesting_crate = src.share_article.default_crate_harvest
    # When ``amount_per_pu_attr`` resolves, it's a known ShareArticle
    # column from ``_AMOUNT_PER_PU_MAP`` — no default. The outer ``if``
    # already handles the "unit not in map" case.
    harvest.amount_per_pu = (
        getattr(src.share_article, amount_per_pu_attr) if amount_per_pu_attr else None
    )
    harvest.washing = src.washing
    harvest.cleaning = src.cleaning
    harvest.save(
        update_fields=["harvesting_crate", "amount_per_pu", "washing", "cleaning"]
    )


def _build_theoretical_purchase(src: TheoreticalSourceData) -> TheoreticalPurchase:
    return TheoreticalPurchase(
        year=src.year,
        delivery_week=src.delivery_week,
        day_number=PURCHASE_DAY,
        share_article=src.share_article,
        amount=src.total_amount_for_shares,
        unit=src.unit,
        size=src.size,
        seller=src.seller,
        note=src.note,
        storage=src.storage,
        **src.content_kwargs,
    )


def _ensure_purchase_placeholder(src: TheoreticalSourceData) -> None:
    purchase, _ = Purchase.objects.get_or_create(
        year=src.year,
        delivery_week=src.delivery_week,
        day_number=PURCHASE_DAY,
        share_article=src.share_article,
        unit=src.unit,
        size=src.size,
        storage=src.storage,
        defaults={"amount": None},
    )
    if src.seller and purchase.seller != src.seller:
        purchase.seller = src.seller
        purchase.save(update_fields=["seller"])


def _processing_storage(
    src: TheoreticalSourceData, short_term_storage: Storage | None
) -> Storage | None:
    """Storage a wash/clean theoretical must use — always the SHORT-term harvest
    storage (where washed/cleaned produce lands). For a long-term line
    ``src.storage`` is the LONG-term storage, so substitute the resolved
    short-term one; a short-term line's ``src.storage`` already is it. Falls back
    to ``src.storage`` if no short-term storage was resolved (misconfiguration).
    Wash/Clean theoreticals carry ``RequiresShortTermStorageMixin``, so this is
    the invariant the bulk_create path must honour."""
    if src.comes_from_long_term_storage and short_term_storage is not None:
        return short_term_storage
    return src.storage


class _ProcessingSpec(NamedTuple):
    """Wash-vs-Clean parametrization for the theoretical processing paths.

    The two paths were byte-identical bar the models, the day/needs field and the
    movement's ``movement_type`` + FK. Capturing that here lets the build,
    placeholder, create-branch and movement loops each exist exactly once, so a
    fix to one can never silently drift from the other.
    """

    created_key: str  # key under ``created_objects`` ("washes" / "cleans")
    theoretical_model: type  # Theoretical{Wash,Clean}Amount
    placeholder_model: type  # {Wash,Clean}Amount (actual placeholder)
    day_field: str  # attr on the source ("washing_day" / "cleaning_day")
    needs_field: str  # attr on the source ("needs_wash" / "needs_clean")
    movement_type: str  # MovementShareArticle.movement_type
    movement_fk_field: str  # FK on the movement pointing back to the theoretical


_PROCESSING: list[_ProcessingSpec] = [
    _ProcessingSpec(
        created_key="washes",
        theoretical_model=TheoreticalWashAmount,
        placeholder_model=WashAmount,
        day_field="washing_day",
        needs_field="needs_wash",
        movement_type="WASH",
        movement_fk_field="theoretical_wash_amount",
    ),
    _ProcessingSpec(
        created_key="cleans",
        theoretical_model=TheoreticalCleanAmount,
        placeholder_model=CleanAmount,
        day_field="cleaning_day",
        needs_field="needs_clean",
        movement_type="CLEAN",
        movement_fk_field="theoretical_clean_amount",
    ),
]


def _build_theoretical_processing(
    spec: _ProcessingSpec,
    src: TheoreticalSourceData,
    short_term_storage: Storage | None = None,
):
    """Build the theoretical Wash/Clean object for *src* (or ``None`` when the
    source has no processing day for *spec*)."""
    day_number = getattr(src, spec.day_field)
    if day_number is None:
        return None

    processing_year, processing_week = compute_rolled_back_week(
        src.year,
        src.delivery_week,
        day_number,
        src.delivery_day,
    )

    return spec.theoretical_model(
        year=processing_year,
        delivery_week=processing_week,
        day_number=day_number,
        share_article=src.share_article,
        amount=src.total_amount_for_shares,
        unit=src.unit,
        size=src.size,
        storage=_processing_storage(src, short_term_storage),
        note=src.note,
        **src.content_kwargs,
    )


def _ensure_processing_placeholder(
    spec: _ProcessingSpec,
    src: TheoreticalSourceData,
    processing_year: int,
    processing_week: int,
    short_term_storage: Storage | None = None,
) -> None:
    # The actual placeholder must share its theoretical's storage — the SHORT-term
    # harvest storage (via _processing_storage), NOT src.storage which is LONG-term
    # for a comes_from_long_term line. Otherwise actual + theoretical land in
    # different storage groups (summary mis-group) and the storage-less unique
    # constraint makes add_additional_theoretical_amount collide (MOV-2).
    spec.placeholder_model.objects.get_or_create(
        year=processing_year,
        delivery_week=processing_week,
        day_number=getattr(src, spec.day_field),
        share_article=src.share_article,
        unit=src.unit,
        size=src.size,
        defaults={
            "amount": None,
            "storage": _processing_storage(src, short_term_storage),
        },
    )


# ──────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────


@transaction.atomic
def create_theoretical_objects(
    sources: list[TheoreticalSourceData],
    *,
    create_placeholders: bool = True,
    collect_movements: list[MovementShareArticle] | None = None,
) -> dict[str, list]:
    """Create all theoretical objects for a batch of source items.

    Args:
        sources: Normalised descriptors for each ShareContent / OrderContent.
        create_placeholders: If True, also create placeholder Harvest/Purchase/
            WashAmount/CleanAmount rows.
        collect_movements: When given, the snapshot cascade is DEFERRED — every
            movement this call would have cascaded (the new theoretical
            movements and any re-derived actual corrections) is appended to
            this list instead, and the caller runs ONE
            ``SnapshotService.cascade_for_movements`` over the accumulated
            union at the end of its transaction. That collapses the multi-pass
            per-entity ``current_balance:*`` advisory-lock acquisition of a
            wipe-and-rebuild recompute into a single canonically-sorted pass,
            so two concurrent overlapping recomputes cannot AB/BA-deadlock.
            Correction mutations still happen here either way — only the
            cascade moves.
    """
    theoretical_harvests: list[TheoreticalHarvest] = []
    theoretical_purchases: list[TheoreticalPurchase] = []
    # Wash/Clean theoreticals + their comes_from_long_term flags, keyed by
    # ``_ProcessingSpec.created_key`` so the two paths share one accumulator.
    processing_theoreticals: dict[str, list] = {
        spec.created_key: [] for spec in _PROCESSING
    }
    processing_long_term_flags: dict[str, list[bool]] = {
        spec.created_key: [] for spec in _PROCESSING
    }

    # Placeholder dedup. Placeholders are keyed WITHOUT the station, so a
    # season-wide batch (one source per station × week) would otherwise
    # re-run the same get_or_create dozens of times per week. Each key
    # includes every per-source value the ensure writes, so the first
    # occurrence of each value-combination wins. When conflicting
    # combinations recur non-contiguously the surviving values can
    # differ from the old last-one-wins loop — both pick an arbitrary
    # winner among conflicting sources, so no canonical result exists.
    ensured_harvests: set[tuple] = set()
    ensured_purchases: set[tuple] = set()
    processing_ensured: dict[str, set[tuple]] = {
        spec.created_key: set() for spec in _PROCESSING
    }

    # Resolved once for the whole batch (avoids an N+1 across sources): wash/
    # clean theoreticals must land in the short-term harvest storage.
    short_term_storage = Storage.short_term_harvest()

    for src in sources:
        if not src.has_positive_amount:
            continue

        # ── Harvest ──
        if src.needs_harvest:
            theoretical_harvest = _build_theoretical_harvest(src)
            if theoretical_harvest is not None:
                theoretical_harvests.append(theoretical_harvest)
                if create_placeholders:
                    harvest_key = (
                        theoretical_harvest.year,
                        theoretical_harvest.delivery_week,
                        src.harvesting_day,
                        src.share_article.id,
                        src.unit,
                        src.size,
                        src.storage.id if src.storage else None,
                        src.washing,
                        src.cleaning,
                    )
                    if harvest_key not in ensured_harvests:
                        ensured_harvests.add(harvest_key)
                        _ensure_harvest_placeholder(
                            src,
                            theoretical_harvest.year,
                            theoretical_harvest.delivery_week,
                        )

        # ── Purchase ──
        if src.needs_purchase:
            theoretical_purchases.append(_build_theoretical_purchase(src))
            if create_placeholders:
                purchase_key = (
                    src.year,
                    src.delivery_week,
                    src.share_article.id,
                    src.unit,
                    src.size,
                    src.storage.id if src.storage else None,
                    src.seller.id if src.seller else None,
                )
                if purchase_key not in ensured_purchases:
                    ensured_purchases.add(purchase_key)
                    _ensure_purchase_placeholder(src)

        # ── Wash / Clean (spec-driven; identical shape bar model + day field) ──
        for spec in _PROCESSING:
            if not getattr(src, spec.needs_field):
                continue
            theoretical = _build_theoretical_processing(spec, src, short_term_storage)
            if theoretical is None:
                continue
            processing_theoreticals[spec.created_key].append(theoretical)
            processing_long_term_flags[spec.created_key].append(
                src.comes_from_long_term_storage
            )
            if create_placeholders:
                processing_key = (
                    theoretical.year,
                    theoretical.delivery_week,
                    getattr(src, spec.day_field),
                    src.share_article.id,
                    src.unit,
                    src.size,
                )
                ensured = processing_ensured[spec.created_key]
                if processing_key not in ensured:
                    ensured.add(processing_key)
                    _ensure_processing_placeholder(
                        spec,
                        src,
                        theoretical.year,
                        theoretical.delivery_week,
                        short_term_storage,
                    )

    created_objects: dict[str, list] = {}
    if theoretical_harvests:
        created_objects["harvests"] = TheoreticalHarvest.objects.bulk_create(
            theoretical_harvests
        )
    if theoretical_purchases:
        created_objects["purchases"] = TheoreticalPurchase.objects.bulk_create(
            theoretical_purchases
        )
    for spec in _PROCESSING:
        items = processing_theoreticals[spec.created_key]
        if items:
            created_objects[spec.created_key] = (
                spec.theoretical_model.objects.bulk_create(items)
            )

    # ── Create theoretical movements for the new objects ──
    movements = _create_theoretical_movements(
        created_objects,
        processing_long_term_flags["washes"],
        processing_long_term_flags["cleans"],
    )

    # ── Recalculate actual correction movements if any exist ──
    if movements:
        # Corrections are mutated FIRST (so any cascade sees the corrected
        # actual amounts), but their cascade is always folded into the same
        # union as the new movements: cascading the corrected subset in a
        # separate earlier pass would acquire a subset of the entity locks
        # before the sorted full set — the subset-then-superset order can
        # AB/BA-deadlock against a concurrent single-pass acquirer.
        union: list[MovementShareArticle] = (
            collect_movements if collect_movements is not None else []
        )
        _recalculate_actual_corrections_for_movements(
            movements, collect_movements=union
        )
        union.extend(movements)

        if collect_movements is None:
            # The new theoretical movements shift the running balance of their
            # (share_article, unit, size, storage) entities. Cascade them so any
            # pre-existing INVENTORY snapshot dated at/after the theoretical date
            # is wiped — otherwise that snapshot shadows the new movement and
            # compute_balance returns a stale, too-low balance — and the
            # CurrentStockBalance projection is refreshed. This enforces, for the
            # theoretical-creation path, the same baseline-wipe invariant every
            # other movement chokepoint already keeps (create_movements, the
            # INVENTORY paths). One sorted union pass (new movements + corrected
            # actuals); when ``collect_movements`` is given the enclosing caller
            # runs it instead.
            from .snapshot_service import SnapshotService

            SnapshotService.cascade_for_movements(union)

    return created_objects


# ──────────────────────────────────────────────────────
# Theoretical movement creation
# ──────────────────────────────────────────────────────


def _create_theoretical_movements(
    created_objects: dict[str, list],
    wash_long_term_flags: list[bool] | None = None,
    clean_long_term_flags: list[bool] | None = None,
) -> list[MovementShareArticle]:
    """Create MovementShareArticle rows for newly created theoretical objects.

    For WASH/CLEAN movements, behaviour depends on ``comes_from_long_term_storage``:
    * **True** – create two movements: a negative movement for the long-term
      storage (stock leaves) and a positive movement for the short-term
      storage (stock arrives).
    * **False** – skip WASH/CLEAN movement creation entirely.
    """
    movements_to_create: list[MovementShareArticle] = []

    # Normalise the per-spec long-term flag lists (a missing list defaults to
    # all-False, sized to that spec's created objects).
    provided_flags = {"washes": wash_long_term_flags, "cleans": clean_long_term_flags}
    long_term_flags_by_key: dict[str, list[bool]] = {}
    for spec in _PROCESSING:
        flags = provided_flags.get(spec.created_key)
        if flags is None:
            flags = [False] * len(created_objects.get(spec.created_key, []))
        long_term_flags_by_key[spec.created_key] = flags

    for theoretical_harvest in created_objects.get("harvests", []):
        if theoretical_harvest.amount and theoretical_harvest.amount > 0:
            movements_to_create.append(
                MovementShareArticle(
                    date=make_noon_datetime(
                        theoretical_harvest.year,
                        theoretical_harvest.delivery_week,
                        theoretical_harvest.day_number,
                    ),
                    movement_type="HARVEST",
                    theoretical_harvest=theoretical_harvest,
                    share_article=theoretical_harvest.share_article,
                    unit=theoretical_harvest.unit,
                    size=theoretical_harvest.size,
                    amount=Decimal(str(theoretical_harvest.amount)),
                    storage=theoretical_harvest.storage,
                    is_theoretical=True,
                )
            )

    for theoretical_purchase in created_objects.get("purchases", []):
        if theoretical_purchase.amount and theoretical_purchase.amount > 0:
            # ``tp.day_number or PURCHASE_DAY`` would silently rewrite a
            # Monday purchase (day_number=0) to PURCHASE_DAY=1 (Tuesday).
            # Unreachable on current data because every TheoreticalPurchase
            # is created with day_number=PURCHASE_DAY above, but use
            # ``is not None`` for defense-in-depth.
            theoretical_purchase_day = (
                theoretical_purchase.day_number
                if theoretical_purchase.day_number is not None
                else PURCHASE_DAY
            )
            movements_to_create.append(
                MovementShareArticle(
                    date=make_noon_datetime(
                        theoretical_purchase.year,
                        theoretical_purchase.delivery_week,
                        theoretical_purchase_day,
                    ),
                    movement_type="PURCHASE",
                    theoretical_purchase=theoretical_purchase,
                    share_article=theoretical_purchase.share_article,
                    unit=theoretical_purchase.unit,
                    size=theoretical_purchase.size,
                    amount=Decimal(str(theoretical_purchase.amount)),
                    storage=theoretical_purchase.storage,
                    is_theoretical=True,
                )
            )

    # ── WASH / CLEAN movements (conditional on comes_from_long_term_storage) ──
    # A long-term line transfers stock: a negative movement leaving long-term
    # storage and a positive one arriving in short-term storage; a non-long-term
    # line creates no processing movement. The storage lookups are cached across
    # BOTH specs (BL-8: the membership guard honours a legitimately cached None so
    # an unconfigured storage isn't re-queried per row).
    storage_cache: dict[str, Storage | None] = {}

    def _cached_storage(cache_key: str, fetch) -> Storage | None:
        if cache_key not in storage_cache:
            storage_cache[cache_key] = fetch()
        return storage_cache[cache_key]

    for spec in _PROCESSING:
        for theoretical, from_long_term in zip(
            created_objects.get(spec.created_key, []),
            long_term_flags_by_key[spec.created_key],
            strict=True,
        ):
            if not (theoretical.amount and theoretical.amount > 0):
                continue
            if not from_long_term:
                # Not from long-term storage → no WASH/CLEAN movements
                continue

            dt = make_noon_datetime(
                theoretical.year,
                theoretical.delivery_week,
                theoretical.day_number,
            )
            amt = Decimal(str(theoretical.amount))

            long_term_storage = _cached_storage("long_term", Storage.long_term_harvest)
            short_term_storage = _cached_storage(
                "short_term", Storage.short_term_harvest
            )

            # Negative movement for the long-term storage (stock leaves)
            if long_term_storage:
                movements_to_create.append(
                    MovementShareArticle(
                        date=dt,
                        movement_type=spec.movement_type,
                        share_article=theoretical.share_article,
                        unit=theoretical.unit,
                        size=theoretical.size,
                        amount=-amt,
                        storage=long_term_storage,
                        is_theoretical=True,
                        **{spec.movement_fk_field: theoretical},
                    )
                )

            # Positive movement for the short-term storage (stock arrives)
            if short_term_storage:
                movements_to_create.append(
                    MovementShareArticle(
                        date=dt,
                        movement_type=spec.movement_type,
                        share_article=theoretical.share_article,
                        unit=theoretical.unit,
                        size=theoretical.size,
                        amount=amt,
                        storage=short_term_storage,
                        is_theoretical=True,
                        **{spec.movement_fk_field: theoretical},
                    )
                )

    if not movements_to_create:
        return []

    return list(MovementShareArticle.objects.bulk_create(movements_to_create))


# ──────────────────────────────────────────────────────
# Actual correction recalculation
# ──────────────────────────────────────────────────────


def _recalculate_actual_corrections_for_movements(
    theoretical_movements: list[MovementShareArticle],
    *,
    collect_movements: list[MovementShareArticle] | None = None,
) -> None:
    """Recalculate actual correction deltas for dimensions affected by
    the given theoretical movements.

    An actual correction movement (e.g. harvest with ``counted_amount``)
    stores ``amount = counted_amount − Σ(theoretical movements for same dimension)``.
    When theoretical movements change, this delta must be recomputed.
    """
    # Collect unique movement_types to find affected actual correction movements.
    affected_types: set[str] = set()
    for movement in theoretical_movements:
        affected_types.add(movement.movement_type)

    if not affected_types:
        return

    recalculate_actual_corrections(
        theoretical_movements, affected_types, collect_movements=collect_movements
    )


@transaction.atomic
def recalculate_actual_corrections(
    reference_movements: list[MovementShareArticle],
    movement_types: set[str] | None = None,
    *,
    collect_movements: list[MovementShareArticle] | None = None,
) -> None:
    """Recalculate all actual correction movements whose dimensions overlap
    with the given reference movements.

    For each actual movement (``is_theoretical=False`` + ``counted_amount IS NOT NULL``)
    matching the same (share_article, unit, size, storage, movement_type):
        new_amount = counted_amount − Σ(theoretical amounts for same dimension & date)

    ``collect_movements``: when given, the mutated corrections are appended to
    it instead of cascaded here — the caller runs one union cascade at the end
    of its transaction (single sorted advisory-lock pass; see
    ``create_theoretical_objects``). The correction rows are saved either way.
    """
    from django.db.models import Q

    from core.db_locks import acquire_advisory_xact_lock

    from .snapshot_service import SnapshotService

    if movement_types is None:
        movement_types = {movement.movement_type for movement in reference_movements}

    # Build dimension keys from the reference movements
    dimension_keys: set[tuple] = set()
    for movement in reference_movements:
        dimension_keys.add(
            (
                str(movement.share_article_id),
                movement.unit,
                movement.size,
                str(movement.storage_id) if movement.storage_id else None,
                movement.movement_type,
            )
        )

    cascaded_movements: list[MovementShareArticle] = []

    # Serialize per-dimension with the count-entry path (goods-flow audit #6): a
    # concurrent recompute and an actual-count entry must net against the SAME
    # theoretical set, else write-skew leaves the correction permanently off.
    # Take the same ``theoretical_sum:*`` transaction lock ``_sum_theoretical``
    # takes, in canonical sorted dimension order so two acquirers can't deadlock
    # (AB/BA). Held to the outer commit and acquired BEFORE the current_balance
    # cascade below, preserving the global theoretical_sum → current_balance order.
    for sa_id, unit, size, storage_id, mtype in sorted(
        dimension_keys,
        key=lambda k: (k[0], k[1] or "", k[2] or "", k[3] or "", k[4]),
    ):
        acquire_advisory_xact_lock(
            f"theoretical_sum:{sa_id}:{unit or ''}:{size or ''}"
            f":{storage_id or ''}:{mtype}"
        )
        # Find actual correction movements for this dimension
        q = Q(
            share_article_id=sa_id,
            movement_type=mtype,
            is_theoretical=False,
            counted_amount__isnull=False,
        )
        q &= Q(unit=unit) if unit else Q(unit__isnull=True)
        q &= Q(size=size) if size else Q(size__isnull=True)
        if storage_id:
            q &= Q(storage_id=storage_id)
        else:
            q &= Q(storage__isnull=True)

        actual_corrections = list(
            MovementShareArticle.objects.filter(q).order_by("date")
        )
        if not actual_corrections:
            continue

        # Batch-fetch all theoretical movements for this dimension (one query)
        tq_base = Q(
            share_article_id=sa_id,
            movement_type=mtype,
            is_theoretical=True,
        )
        tq_base &= Q(unit=unit) if unit else Q(unit__isnull=True)
        tq_base &= Q(size=size) if size else Q(size__isnull=True)
        if storage_id:
            tq_base &= Q(storage_id=storage_id)
        else:
            tq_base &= Q(storage__isnull=True)

        theoretical_movements = list(
            MovementShareArticle.objects.filter(tq_base)
            .order_by("date")
            .values_list("date", "amount")
        )

        for actual_correction in actual_corrections:
            # Day-scoped netting (MOV-3): a correction nets ONLY the theoretical(s)
            # for its OWN harvesting day — theoretical and actual movements for a
            # (year, week, day) dimension share the same noon datetime. A
            # cumulative ``date <= actual_correction.date`` would re-subtract an
            # earlier day's theoretical from EVERY later correction on the same
            # dimension (the Harvest/Purchase constraints permit one actual per
            # day), subtracting a single plan N times and even producing negative
            # HARVEST rows.
            theoretical_sum = sum(
                (theoretical_amount or Decimal("0"))
                for movement_date, theoretical_amount in theoretical_movements
                if movement_date == actual_correction.date
            )

            new_amount = actual_correction.counted_amount - theoretical_sum
            if actual_correction.amount != new_amount:
                actual_correction.amount = new_amount
                actual_correction.save(update_fields=["amount"])
                cascaded_movements.append(actual_correction)

    if cascaded_movements:
        if collect_movements is not None:
            collect_movements.extend(cascaded_movements)
        else:
            SnapshotService.cascade_for_movements(cascaded_movements)


def build_theoretical_objects_from_rows(
    rows: list,
    build_source: Callable[
        [Any, Storage | None, Storage | None], TheoreticalSourceData | None
    ],
    *,
    collect_movements: list[MovementShareArticle] | None = None,
) -> dict[str, list]:
    """Shared skeleton for the OrderContent / ShareContent
    ``create_all_theoretical_objects`` variants.

    Fetches both harvest storages ONCE, builds a ``TheoreticalSourceData``
    per row via the caller's ``build_source(row, short_term, long_term)``
    callback (returning ``None`` to skip a row), then creates the theoretical
    objects with placeholders. The only thing the two variants differ on is
    the per-row field mapping — that lives in the callback; the storage
    fetch, the long-vs-short selection (via ``Storage.select_harvest``), and
    the final ``create_theoretical_objects`` call are shared here.
    ``collect_movements`` defers the snapshot cascade to the caller — see
    ``create_theoretical_objects``."""
    short_term = Storage.short_term_harvest()
    long_term = Storage.long_term_harvest()
    sources: list[TheoreticalSourceData] = []
    for row in rows:
        source = build_source(row, short_term, long_term)
        if source is not None:
            sources.append(source)
    return create_theoretical_objects(
        sources, create_placeholders=True, collect_movements=collect_movements
    )
