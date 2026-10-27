from __future__ import annotations

import datetime as _dt
import logging
from decimal import Decimal
from typing import Any, TypeVar

from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone as _tz
from isoweek import Week

from ..constants import PURCHASE_DAY
from ..models import (
    Harvest,
    MovementShareArticle,
    Purchase,
    Waste,
)
from ..models.choices import MovementTypeOptions
from ..utils import (
    clean_storage_fields,
    extract_selected_storage_id,
)
from .snapshot_service import SnapshotService

logger = logging.getLogger(__name__)

DocumentationModel = Harvest | Purchase | Waste
_DocumentationModelT = TypeVar("_DocumentationModelT", Harvest, Purchase, Waste)

# Maps model class → the FK field name on MovementShareArticle that points to it,
# and the callable that creates the movement for that type.
_MODEL_REGISTRY: dict[type[models.Model], str] = {
    Harvest: "harvest",
    Purchase: "purchase",
    Waste: "waste",
}

# The movement type each source FK writes.
_MOVEMENT_TYPE_BY_FK: dict[str, str] = {
    "harvest": MovementTypeOptions.HARVEST,
    "purchase": MovementTypeOptions.PURCHASE,
    "waste": MovementTypeOptions.WASTE,
}


class GenericDocumentationService:
    """Service for Harvest / Purchase / Waste CRUD with automatic Movement creation."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def create_with_related_objects(
        model_class: type[_DocumentationModelT], validated_data: dict[str, Any]
    ) -> _DocumentationModelT:
        storage_id = extract_selected_storage_id(validated_data)
        clean_storage_fields(validated_data)
        if storage_id:
            validated_data["storage_id"] = storage_id

        instance = model_class.objects.create(**validated_data)
        GenericDocumentationService._create_movement(instance)
        return instance

    @staticmethod
    @transaction.atomic
    def update_with_related_objects(
        instance: _DocumentationModelT, validated_data: dict[str, Any]
    ) -> _DocumentationModelT:
        storage_id = extract_selected_storage_id(validated_data)
        clean_storage_fields(validated_data)
        if storage_id:
            validated_data["storage_id"] = storage_id

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        GenericDocumentationService._upsert_movement(instance)
        return instance

    # Convenience wrappers (preserve existing call-sites) ---------------

    @staticmethod
    def create_harvest_with_related_objects(
        validated_data: dict[str, Any],
    ) -> Harvest:
        return GenericDocumentationService.create_with_related_objects(
            Harvest, validated_data
        )

    @staticmethod
    def update_harvest_with_related_objects(
        instance: Harvest, validated_data: dict[str, Any]
    ) -> Harvest:
        return GenericDocumentationService.update_with_related_objects(
            instance, validated_data
        )

    @staticmethod
    @transaction.atomic
    def create_purchase_with_related_objects(
        validated_data: dict[str, Any],
    ) -> Purchase:
        """Create a purchase, or fill the empty planning placeholder its values
        land on (see ``empty_purchase_placeholder``)."""
        placeholder = GenericDocumentationService.empty_purchase_placeholder(
            validated_data, lock=True
        )
        if placeholder is not None:
            return GenericDocumentationService.update_with_related_objects(
                placeholder, validated_data
            )
        return GenericDocumentationService.create_with_related_objects(
            Purchase, validated_data
        )

    @staticmethod
    def empty_purchase_placeholder(
        values: dict[str, Any], *, lock: bool = False
    ) -> Purchase | None:
        """The row a purchase with these values would duplicate, while nothing
        has been documented on it yet (``amount`` NULL): the placeholder the
        planner writes for a planned purchase, on the same weekly slot, supplier
        and storage. A new purchase fills it rather than adding a second row the
        office can't tell apart from it."""
        rows = Purchase.objects.filter(
            year=values["year"],
            delivery_week=values["delivery_week"],
            day_number=values.get("day_number"),
            share_article=values.get("share_article"),
            unit=values.get("unit"),
            size=values.get("size"),
            storage=extract_selected_storage_id(values) or values.get("storage"),
            seller=values.get("seller"),
            amount__isnull=True,
        )
        return (rows.select_for_update() if lock else rows).first()

    @staticmethod
    def update_purchase_with_related_objects(
        instance: Purchase, validated_data: dict[str, Any]
    ) -> Purchase:
        return GenericDocumentationService.update_with_related_objects(
            instance, validated_data
        )

    @staticmethod
    def create_waste_with_related_objects(
        validated_data: dict[str, Any],
    ) -> Waste:
        return GenericDocumentationService.create_with_related_objects(
            Waste, validated_data
        )

    @staticmethod
    def update_waste_with_related_objects(
        instance: Waste, validated_data: dict[str, Any]
    ) -> Waste:
        return GenericDocumentationService.update_with_related_objects(
            instance, validated_data
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _carries_theoreticals(instance: DocumentationModel) -> bool:
        """Return *True* when the storage is a HARVEST storage (short OR long
        term) — i.e. one that holds theoretical HARVEST/PURCHASE movements, so an
        actual count against it must run in correction mode (``amount = counted −
        Σtheoretical``), not as a plain add. A ``comes_from_long_term`` line plans
        its harvest onto the LONG-term storage (Storage.select_harvest), so that
        storage carries theoreticals exactly like the short-term one — gating only
        on short-term double-counts the long-term theoretical."""
        storage = instance.storage
        return (
            storage.is_short_term_harvest_storage
            or storage.is_long_term_harvest_storage
        )

    @staticmethod
    def _movement_datetime(
        year: int, delivery_week: int, day_number: int | None
    ) -> _dt.datetime:
        """Build a datetime from ISO year/week/day_number. Defaults to Monday when *day_number* is ``None``."""
        week = Week(year, delivery_week)
        day_methods = [
            week.monday,
            week.tuesday,
            week.wednesday,
            week.thursday,
            week.friday,
            week.saturday,
            week.sunday,
        ]
        movement_date = day_methods[day_number if day_number is not None else 0]()
        return _tz.make_aware(_dt.datetime.combine(movement_date, _dt.time(12, 0, 0)))

    # Types that have theoretical counterparts (Harvest, Purchase).
    # Waste has no theoretical — it's always an absolute outflow.
    _CORRECTION_TYPES: set[str] = {"harvest", "purchase"}

    @staticmethod
    def movement_day_number(day_number: int | None, movement_type: str) -> int:
        """The weekday a movement is dated on. The office records purchases per
        week, without one: a purchase lands on ``PURCHASE_DAY`` with its planned
        purchase, so the two net. Anything else without a weekday is dated
        Monday.
        """
        if day_number is not None:
            return day_number
        return PURCHASE_DAY if movement_type == MovementTypeOptions.PURCHASE else 0

    @staticmethod
    def _movement_kwargs(instance: DocumentationModel) -> dict[str, Any]:
        """Return the common fields for creating a ``MovementShareArticle``.

        For Harvest / Purchase with ``amount is not None`` the movement acts
        as a *correction* against existing theoretical movements:
          ``counted_amount`` = the actual number entered by the user
          ``amount`` = counted_amount − Σ(theoretical movements for same dimension)
        (``_create_movement`` then re-nets the day's corrections, so the day's
        theoretical is subtracted from only one of them.)

        For Waste the amount is always negated and used directly.
        """
        fk_field = _MODEL_REGISTRY.get(type(instance))
        if fk_field is None:
            raise ValueError(f"Unsupported model: {type(instance).__name__}")

        mtype = _MOVEMENT_TYPE_BY_FK[fk_field]
        day_number = GenericDocumentationService.movement_day_number(
            instance.day_number, mtype
        )

        base = {
            "date": GenericDocumentationService._movement_datetime(
                instance.year, instance.delivery_week, day_number
            ),
            "movement_type": mtype,
            fk_field: instance,
            "share_article": instance.share_article,
            "unit": instance.unit,
            "size": instance.size,
            "storage": instance.storage,
            "note": instance.note,
            "is_theoretical": False,
        }

        if isinstance(instance, Waste):
            raw = instance.amount or 0
            base["amount"] = -abs(raw) if raw else 0
            return base

        # Harvest / Purchase on a harvest storage (short OR long term) → correction
        # mode (counted_amount anchors the actual; amount = counted − Σ theoretical)
        if GenericDocumentationService._carries_theoreticals(instance):
            counted = Decimal(str(instance.amount))
            base["counted_amount"] = counted

            theoretical_sum = GenericDocumentationService._sum_theoretical(
                share_article_id=str(instance.share_article_id),
                unit=instance.unit,
                size=instance.size,
                storage_id=str(instance.storage_id),
                movement_type=mtype,
                up_to=base["date"],
            )

            base["amount"] = counted - theoretical_sum
            return base

        # Harvest / Purchase on a non-harvest storage → plain movement, no correction
        raw = instance.amount or 0
        base["amount"] = Decimal(str(raw))
        return base

    @staticmethod
    def _sum_theoretical(
        share_article_id: str,
        unit: str | None,
        size: str | None,
        storage_id: str,
        movement_type: str,
        up_to,
    ) -> Decimal:
        """Sum all theoretical movement amounts for a dimension.

        Must be called from inside a transaction. Acquires a Postgres
        advisory lock keyed by the dimension tuple so concurrent
        writers creating correction movements for the same
        (share_article, unit, size, storage, movement_type) serialise.
        Without the lock, two writers would both read the same
        theoretical_sum, both subtract it from their counted amount,
        and silently double-count the correction.

        ``.select_for_update().aggregate(...)`` would not serialise them — FOR
        UPDATE has no effect on aggregate queries.
        """
        from core.db_locks import acquire_advisory_xact_lock

        lock_key = (
            f"theoretical_sum:{share_article_id}:{unit or ''}:{size or ''}"
            f":{storage_id or ''}:{movement_type}"
        )
        acquire_advisory_xact_lock(lock_key)

        # Day-scoped: net only the theoretical(s) for the correction's OWN
        # harvesting day (``date == up_to``), matching recalculate_actual_corrections.
        # Theoretical + actual movements for a (year, week, day) dimension share
        # the same noon datetime; a cumulative ``date__lte`` re-subtracts an
        # earlier day's plan from every later day's correction.
        q = Q(
            share_article_id=share_article_id,
            unit=unit,
            size=size,
            storage_id=storage_id,
            movement_type=movement_type,
            is_theoretical=True,
            date=up_to,
        )

        return MovementShareArticle.objects.filter(q).aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0")

    @staticmethod
    @transaction.atomic
    def _create_movement(
        instance: DocumentationModel, _data: Any = None
    ) -> MovementShareArticle | None:
        fk_field = _MODEL_REGISTRY.get(type(instance))
        # Skip placeholder Harvest/Purchase on a harvest storage (short OR long
        # term, amount=None) — theoreticals already cover stock for that dimension.
        if (
            fk_field in GenericDocumentationService._CORRECTION_TYPES
            and instance.amount is None
            and GenericDocumentationService._carries_theoreticals(instance)
        ):
            return None

        kwargs = GenericDocumentationService._movement_kwargs(instance)
        movement = MovementShareArticle.objects.create(**kwargs)
        corrected: list[MovementShareArticle] = []
        if movement.counted_amount is not None:
            from .theoretical_objects import recalculate_actual_corrections

            # Another correction of the day may have carried its theoretical
            # so far, and this one may take it over.
            recalculate_actual_corrections([movement], collect_movements=corrected)
            movement.refresh_from_db(fields=["amount"])
        SnapshotService.cascade_for_movements([movement, *corrected])
        return movement

    @staticmethod
    @transaction.atomic
    def _upsert_movement(instance: DocumentationModel) -> MovementShareArticle | None:
        """Delete the existing movement (if any) and recreate it from current data.

        The day the old correction leaves is re-netted, as it may have carried
        that day's theoretical. A purchase without a weekday also has the
        movements of its additional planned amounts re-synced, so they stay on
        its day.
        """
        from .theoretical_objects import (
            correction_dimension,
            lock_theoretical_sums,
            recalculate_actual_corrections,
        )

        fk_field = _MODEL_REGISTRY.get(type(instance))
        if fk_field is None:
            raise ValueError(f"Unsupported model: {type(instance).__name__}")

        # Capture old movements so we can cascade for their entities too
        # (the entity may have changed, e.g. different storage).
        old_movements = list(
            MovementShareArticle.objects.filter(**{fk_field: instance})
        )
        old_corrections = [m for m in old_movements if m.counted_amount is not None]
        dimensions = {correction_dimension(m) for m in old_corrections}
        if fk_field in GenericDocumentationService._CORRECTION_TYPES:
            dimensions.add(
                (
                    str(instance.share_article_id),
                    instance.unit,
                    instance.size,
                    str(instance.storage_id) if instance.storage_id else None,
                    _MOVEMENT_TYPE_BY_FK[fk_field],
                )
            )
        lock_theoretical_sums(dimensions)

        MovementShareArticle.objects.filter(**{fk_field: instance}).delete()

        if isinstance(instance, Purchase) and instance.day_number is None:
            GenericDocumentationService._resync_additional_purchases(instance)

        # _create_movement may return None for placeholder Harvest/Purchase.
        new_movement = GenericDocumentationService._create_movement(instance)

        if old_movements:
            corrected: list[MovementShareArticle] = []
            if old_corrections:
                recalculate_actual_corrections(
                    old_corrections, collect_movements=corrected
                )
            SnapshotService.cascade_for_movements([*old_movements, *corrected])

        return new_movement

    @staticmethod
    def _resync_additional_purchases(instance: Purchase) -> None:
        """Re-sync the movements of the purchase's additional planned amounts
        (``AdditionalTheoreticalPurchase`` rows with its key, its seller and no
        weekday either), so they are dated on its day."""
        from ..models import AdditionalTheoreticalPurchase
        from .documentation_summary_service import DocumentationSummaryService

        additional_entries = AdditionalTheoreticalPurchase.objects.filter(
            year=instance.year,
            delivery_week=instance.delivery_week,
            day_number__isnull=True,
            share_article_id=instance.share_article_id,
            unit=instance.unit,
            size=instance.size,
            storage_id=instance.storage_id,
            seller_id=instance.seller_id,
        )
        for additional_entry in additional_entries:
            DocumentationSummaryService._sync_additional_movement(
                additional_entry,
                additional_entry.amount,
                {
                    "year": additional_entry.year,
                    "delivery_week": additional_entry.delivery_week,
                    "day_number": None,
                    "unit": additional_entry.unit,
                    "size": additional_entry.size,
                },
                additional_entry.share_article,
                additional_entry.storage,
                "additional_theoretical_purchase",
                MovementTypeOptions.PURCHASE,
            )
