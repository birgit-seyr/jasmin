from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .base import JasminModel
from .choices_text import (
    CultivationOriginOptions,
    MovementTypeOptions,
    SizeVegetableOptions,
    UnitOptions,
)
from .managers import DateActiveOnlyManager

# Module-level so that ``MovementShareArticle.Meta`` (a nested class) can reach
# them through normal global lookup. Python's class scopes do not extend into
# nested classes, so a class attribute would be invisible to ``Meta``.
_SOURCE_TO_TYPE: dict[str, str] = {
    "share_content": MovementTypeOptions.SHARE,
    "order_content": MovementTypeOptions.ORDERCONTENT,
    "harvest": MovementTypeOptions.HARVEST,
    "purchase": MovementTypeOptions.PURCHASE,
    "waste": MovementTypeOptions.WASTE,
    "wash_amount": MovementTypeOptions.WASH,
    "clean_amount": MovementTypeOptions.CLEAN,
    "theoretical_harvest": MovementTypeOptions.HARVEST,
    "theoretical_purchase": MovementTypeOptions.PURCHASE,
    "theoretical_wash_amount": MovementTypeOptions.WASH,
    "theoretical_clean_amount": MovementTypeOptions.CLEAN,
    "additional_theoretical_harvest": MovementTypeOptions.HARVEST,
    "additional_theoretical_purchase": MovementTypeOptions.PURCHASE,
    "additional_theoretical_wash_amount": MovementTypeOptions.WASH,
    "additional_theoretical_clean_amount": MovementTypeOptions.CLEAN,
}


def _build_source_fk_xor_constraint() -> models.CheckConstraint:
    """DB-level guarantee that exactly one source FK is set on non-INVENTORY rows.

    Catches bulk-create / raw paths that bypass ``clean()``.
    INVENTORY rows must have all source FKs NULL.
    """
    per_fk_terms = []
    for filled_field in _SOURCE_TO_TYPE:
        kwargs = {f"{filled_field}__isnull": False}
        for other in _SOURCE_TO_TYPE:
            if other == filled_field:
                continue
            kwargs[f"{other}__isnull"] = True
        per_fk_terms.append(models.Q(**kwargs))

    all_null_kwargs = {f"{f}__isnull": True for f in _SOURCE_TO_TYPE}
    inventory_branch = models.Q(
        movement_type=MovementTypeOptions.INVENTORY, **all_null_kwargs
    )
    non_inventory_branch = per_fk_terms[0]
    for term in per_fk_terms[1:]:
        non_inventory_branch = non_inventory_branch | term
    non_inventory_branch &= ~models.Q(movement_type=MovementTypeOptions.INVENTORY)

    return models.CheckConstraint(
        condition=inventory_branch | non_inventory_branch,
        name="movementsharearticle_exactly_one_source",
    )


# Single source of truth for the "capture both movement halves before a
# ShareContent cascade" filter (was hand-duplicated verbatim across 5
# delete/replace paths). These are the theoretical source FKs that each carry
# their OWN ``share_content`` FK — so they're reachable from a ShareContent and
# cascade-delete with it. The ``additional_theoretical_*`` sources are
# deliberately excluded: those models have no ``share_content`` FK (they're
# keyed by year/week/article dimensions plus the ``for_share_content`` /
# ``for_order_content`` flags), so they're out of scope here.
_SHARE_CONTENT_THEORETICAL_FKS = (
    "theoretical_harvest",
    "theoretical_purchase",
    "theoretical_wash_amount",
    "theoretical_clean_amount",
)


def _content_movement_q(contents, *, field_name: str) -> models.Q:
    """``Q`` matching every ``MovementShareArticle`` reachable from one or more
    content rows: the direct ``<field_name>`` half plus each ``theoretical_*``
    parent's ``<field_name>`` half. ``field_name`` is ``"share_content"`` or
    ``"order_content"``. Pass a single model instance OR an iterable / queryset.
    """
    suffix = "" if isinstance(contents, models.Model) else "__in"
    q = models.Q(**{f"{field_name}{suffix}": contents})
    for fk in _SHARE_CONTENT_THEORETICAL_FKS:
        q |= models.Q(**{f"{fk}__{field_name}{suffix}": contents})
    return q


def share_content_movement_q(share_contents) -> models.Q:
    """``Q`` matching every ``MovementShareArticle`` reachable from one or more
    ``ShareContent`` rows: the direct ``share_content`` half plus each
    ``theoretical_*`` half. Pass a single ``ShareContent`` instance OR an
    iterable / queryset of them (an extra term — e.g. ForecastViewSet's
    ``theoretical_harvest__forecast`` — can be OR-ed onto the result)."""
    return _content_movement_q(share_contents, field_name="share_content")


def order_content_movement_q(order_contents) -> models.Q:
    """``Q`` matching every ``MovementShareArticle`` reachable from one or more
    ``OrderContent`` rows: the direct ``order_content`` half plus each
    ``theoretical_*`` half. Pass a single ``OrderContent`` instance OR an
    iterable / queryset of them."""
    return _content_movement_q(order_contents, field_name="order_content")


class MovementShareArticleManager(models.Manager):
    def for_share_contents(self, share_contents):
        """All movements reachable from these ``ShareContent`` rows — see
        ``share_content_movement_q``."""
        return self.filter(share_content_movement_q(share_contents))

    def for_order_contents(self, order_contents):
        """All movements reachable from these ``OrderContent`` rows — see
        ``order_content_movement_q``."""
        return self.filter(order_content_movement_q(order_contents))


class MovementShareArticle(JasminModel):
    objects = MovementShareArticleManager()
    active = DateActiveOnlyManager(archive_months=2)

    date = models.DateTimeField(db_index=True)
    # movement_type is a sort of doubling, but it makes querying much faster than via foreignkey
    movement_type = models.CharField(
        choices=MovementTypeOptions.choices,
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
    )
    # where the movement comes from:
    # SHARECONTENT
    share_content = models.ForeignKey(
        "ShareContent", on_delete=models.CASCADE, blank=True, null=True
    )
    # ORDERCONTENT
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )
    # HARVEST
    harvest = models.ForeignKey(
        "Harvest", on_delete=models.CASCADE, blank=True, null=True
    )
    # PURCHASE
    purchase = models.ForeignKey(
        "Purchase", on_delete=models.CASCADE, blank=True, null=True
    )
    # WASTE
    waste = models.ForeignKey("Waste", on_delete=models.CASCADE, blank=True, null=True)

    # WASHING
    wash_amount = models.ForeignKey(
        "WashAmount", on_delete=models.CASCADE, blank=True, null=True
    )
    # CLEANING
    clean_amount = models.ForeignKey(
        "CleanAmount", on_delete=models.CASCADE, blank=True, null=True
    )

    # ── Theoretical source FKs ──
    # Exactly one source FK per movement (theoretical OR actual, never both).
    # on_delete=CASCADE: deleting the theoretical object auto-deletes its movement.
    theoretical_harvest = models.ForeignKey(
        "TheoreticalHarvest", on_delete=models.CASCADE, blank=True, null=True
    )
    theoretical_purchase = models.ForeignKey(
        "TheoreticalPurchase", on_delete=models.CASCADE, blank=True, null=True
    )
    theoretical_wash_amount = models.ForeignKey(
        "TheoreticalWashAmount", on_delete=models.CASCADE, blank=True, null=True
    )
    theoretical_clean_amount = models.ForeignKey(
        "TheoreticalCleanAmount", on_delete=models.CASCADE, blank=True, null=True
    )
    additional_theoretical_harvest = models.ForeignKey(
        "AdditionalTheoreticalHarvest", on_delete=models.CASCADE, blank=True, null=True
    )
    additional_theoretical_purchase = models.ForeignKey(
        "AdditionalTheoreticalPurchase",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    additional_theoretical_wash_amount = models.ForeignKey(
        "AdditionalTheoreticalWashAmount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    additional_theoretical_clean_amount = models.ForeignKey(
        "AdditionalTheoreticalCleanAmount",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    # True for movements created from theoretical/additional-theoretical objects.
    is_theoretical = models.BooleanField(default=False)

    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=3
    )  # this is always in the default_unit

    cultivation_origin = models.CharField(
        choices=CultivationOriginOptions.choices,
        max_length=5,
        blank=True,
        null=True,
    )
    storage = models.ForeignKey(
        "Storage", on_delete=models.PROTECT, blank=True, null=True
    )

    note = models.CharField(max_length=500, blank=True, null=True)

    # INVENTORY-specific fields (only used when movement_type=INVENTORY)
    washed = models.BooleanField(default=False)
    cleaned = models.BooleanField(default=False)
    for_shares = models.BooleanField(default=True)
    for_resellers = models.BooleanField(default=False)
    for_markets = models.BooleanField(default=False)
    is_finalized = models.BooleanField(default=False)
    counted_amount = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Absolute counted/actual value. For INVENTORY: physical count. "
        "For actual Harvest/Purchase/Wash/Clean: the real amount entered by the user. "
        "Used to recalculate the correction delta when theoretical movements change.",
    )

    _SOURCE_FK_FIELDS: list[str] = list(_SOURCE_TO_TYPE.keys())

    class Meta:
        constraints = [
            _build_source_fk_xor_constraint(),
            # MOV-6: INVENTORY is a per-(entity, day) physical count — at most one
            # row. The upsert's empty select_for_update() takes no gap lock under
            # READ COMMITTED, so two concurrent PATCHes could both insert; the read
            # paths then SUM all same-day INVENTORY rows and double-count. ``date``
            # is always 23:00 (_ywd_to_datetime), so it's effectively the calendar
            # day. nulls_distinct=False (PG15+) so two NULL-storage rows collide.
            models.UniqueConstraint(
                fields=["share_article", "unit", "size", "storage", "date"],
                condition=models.Q(movement_type=MovementTypeOptions.INVENTORY),
                name="one_inventory_per_entity_day",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["date", "movement_type"]),
            models.Index(fields=["date", "share_article"]),
            models.Index(fields=["date", "share_content"]),
            models.Index(fields=["date", "order_content"]),
            models.Index(fields=["date", "harvest"]),
            models.Index(fields=["date", "purchase"]),
            models.Index(fields=["date", "waste"]),
            models.Index(fields=["date", "wash_amount"]),
            models.Index(fields=["date", "clean_amount"]),
            models.Index(fields=["is_theoretical", "movement_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.share_article} {self.amount} ({self.date:%Y-%m-%d})"

    def clean(self) -> None:
        super().clean()

        # INVENTORY movements have no source FK
        if self.movement_type == MovementTypeOptions.INVENTORY:
            if any(getattr(self, f) is not None for f in self._SOURCE_FK_FIELDS):
                raise ValidationError("INVENTORY movements must not have a source FK")
            return

        filled = [f for f in self._SOURCE_FK_FIELDS if getattr(self, f) is not None]

        if len(filled) == 0:
            raise ValidationError("Movement must have exactly one source FK.")
        if len(filled) > 1:
            raise ValidationError(
                "Movement can only have one source, but multiple were provided: "
                + ", ".join(filled)
            )

        field_name = filled[0]
        expected_type = _SOURCE_TO_TYPE[field_name]
        if self.movement_type and self.movement_type != expected_type:
            raise ValidationError(
                f"movement_type must be '{expected_type}' when {field_name} is set, "
                f"but got '{self.movement_type}'"
            )

    def save(self, *args, **kwargs) -> None:
        self.derive_movement_type(self)
        self.full_clean()
        super().save(*args, **kwargs)

    @staticmethod
    def derive_movement_type(instance: MovementShareArticle) -> None:
        """Auto-set ``movement_type`` from whichever source FK is filled.

        Exposed as a staticmethod so service-layer ``bulk_create`` paths can
        call the same derivation that ``save()`` uses.
        """
        if instance.movement_type == MovementTypeOptions.INVENTORY:
            return
        for field_name, movement_type in _SOURCE_TO_TYPE.items():
            if getattr(instance, field_name) is not None:
                instance.movement_type = movement_type
                return
