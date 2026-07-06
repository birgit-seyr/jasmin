from __future__ import annotations

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from ..errors import CommissioningError, DocumentDateRequired, FinalizedError
from .base import JasminModel
from .choices_text import DayNumberOptions, SizeVegetableOptions, UnitOptions
from .mixin import (
    CreatedMixin,
    DateDocumentMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    FinalizedProtectedQuerySet,
    LinePricingMixin,
    NumberedDocumentMixin,
    PayableMixin,
    SourceSnapshotMixin,
    sum_brutto,
    sum_netto,
    tax_breakdown,
)

logger = logging.getLogger(__name__)


class OfferGroup(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200, blank=True, null=True)
    note = models.CharField(max_length=500, blank=True, null=True)
    rabatt_price_tier_2 = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    rabatt_price_tier_3 = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    # Each tenant is seeded with exactly one default offer group (see the
    # partial-unique constraint below). It is the offer group pre-selected for
    # new resellers and is protected from deletion — the office may rename /
    # renumber it, but one must always persist.
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # At most ONE offer group may be flagged as the default — a partial
            # unique constraint scoped by the boolean filter (the value is True
            # for every row in scope, so only one such row can exist).
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="offergroup_single_default",
            ),
        ]

    def __str__(self) -> str:
        return self.name or self.get_display_id()

    @classmethod
    def get_default(cls) -> OfferGroup | None:
        """The tenant's single default offer group (a partial-unique singleton
        — see ``Meta.constraints``). Seeded per tenant and protected from
        deletion. ``None`` only if the seed has not yet run."""
        return cls.objects.filter(is_default=True).first()


class Reseller(JasminModel):
    # Every reseller must have a contact (its address / e-mail / name live on
    # the linked ContactEntity). PROTECT — not SET_NULL — because the FK is
    # required: a contact can't be deleted out from under its reseller; delete
    # or reassign the reseller first.
    contact = models.ForeignKey("ContactEntity", on_delete=models.PROTECT)
    linked_user = models.OneToOneField(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="linked_reseller",
    )
    name_for_member_pages = models.CharField(max_length=200, blank=True, null=True)
    customer_number = models.PositiveIntegerField(unique=True, blank=True, null=True)
    filial_number = models.PositiveIntegerField(blank=True, null=True)
    is_seller = models.BooleanField(default=False)
    is_reseller = models.BooleanField(default=False)
    is_donation_recipient = models.BooleanField(default=False)
    is_supplier = models.BooleanField(default=False)
    is_active_seller = models.BooleanField(default=True)
    is_active_reseller = models.BooleanField(default=True)
    is_active_donation_recipient = models.BooleanField(default=True)
    is_active_supplier = models.BooleanField(default=True)
    offer_via_email = models.BooleanField(default=False, blank=True, null=True)
    order_via_email = models.BooleanField(default=False, blank=True, null=True)
    delivery_note_via_email = models.BooleanField(default=False, blank=True, null=True)
    invoice_via_email = models.BooleanField(default=True)
    offer_group = models.ForeignKey(
        "OfferGroup", on_delete=models.SET_NULL, blank=True, null=True
    )
    invoice_name = models.CharField(max_length=200, blank=True, null=True)
    invoice_name2 = models.CharField(max_length=200, blank=True, null=True)
    invoice_address = models.CharField(max_length=300, blank=True, null=True)
    invoice_plz = models.CharField(max_length=5, blank=True, null=True)
    invoice_city = models.CharField(max_length=100, blank=True, null=True)
    invoice_email = models.CharField(max_length=200, blank=True, null=True)

    # ── Payment conditions ──────────────────────────────────────────────
    # Per-reseller overrides for the tenant-level defaults
    # (``TenantSettings.payment_terms_reseller_in_days`` etc.). All three
    # are nullable — NULL means "fall back to the tenant default", a
    # concrete value means "this reseller has their own terms". See the
    # ``get_payment_terms_days`` / ``get_early_payment_discount`` helpers
    # below for the resolution order.
    payment_terms_in_days = models.PositiveIntegerField(blank=True, null=True)
    early_payment_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    early_payment_discount_days = models.PositiveIntegerField(blank=True, null=True)

    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        constraints = [
            # filial_number is unique only within the same customer_number
            # (e.g. "REWE filial 1", "REWE filial 2" — same customer, different filials).
            models.UniqueConstraint(
                fields=["customer_number", "filial_number"],
                condition=models.Q(
                    customer_number__isnull=False, filial_number__isnull=False
                ),
                name="reseller_unique_customer_filial",
            ),
            # One Reseller per ContactEntity — the ``get_or_create(contact=…)``
            # / ``.get(contact=…)`` callers assume 1:1. The constraint also
            # turns a concurrent ``get_or_create`` race into a catchable
            # IntegrityError that get_or_create re-fetches, instead of two rows
            # that later blow up ``.get(contact=…)`` with MultipleObjectsReturned.
            models.UniqueConstraint(
                fields=["contact"],
                condition=models.Q(contact__isnull=False),
                name="reseller_unique_contact",
            ),
        ]

    def __str__(self) -> str:
        if self.contact:
            return str(self.contact)
        return f"Reseller #{self.customer_number or self.get_display_id()}"

    # ── Payment-condition resolution ────────────────────────────────────
    # ``get_payment_terms_days`` / ``get_early_payment_discount`` are the
    # canonical entry points the PDF + ZUGFeRD generators call.
    # Resolution order:
    #   1. Per-reseller override on this row (NULL = not set)
    #   2. Tenant-level default from the current ``TenantSettings``
    #   3. Hard-coded safety value (14 days, no Skonto) so a fresh tenant
    #      without a settings row can still issue invoices.
    #
    # The Skonto helper returns ``(percent, days)`` as a paired tuple so
    # the caller can early-out cleanly: ``percent is None`` means "no
    # discount offered".
    def get_payment_terms_days(self) -> int:
        if self.payment_terms_in_days is not None:
            return self.payment_terms_in_days
        settings = self._current_tenant_settings()
        if settings is not None:
            return settings.payment_terms_reseller_in_days
        return 14

    def get_early_payment_discount(self) -> tuple[Decimal | None, int | None]:
        # Per-reseller takes precedence — including the case where the
        # office explicitly cleared the discount on a reseller whose
        # tenant default offers one.
        if (
            self.early_payment_discount_percent is not None
            or self.early_payment_discount_days is not None
        ):
            return (
                self.early_payment_discount_percent,
                self.early_payment_discount_days,
            )
        settings = self._current_tenant_settings()
        if settings is None:
            return (None, None)
        return (
            getattr(settings, "early_payment_discount_percent", None),
            getattr(settings, "early_payment_discount_days", None),
        )

    @staticmethod
    def _current_tenant_settings():
        # Lazy import — ``apps.commissioning`` is the "to-be-extracted"
        # tenant app, so we keep the cross-app import out of the module
        # namespace per CLAUDE.md ("isolation is one-way").
        from django.db import connection

        from apps.shared.tenants.models import TenantSettings

        tenant = getattr(connection, "tenant", None)
        if tenant is None:
            return None
        return TenantSettings.get_current_settings(tenant)


class OrderableItem(LinePricingMixin, JasminModel):
    offer = models.ForeignKey("Offer", on_delete=models.CASCADE, blank=True, null=True)
    share_article = models.ForeignKey(
        "ShareArticle", on_delete=models.PROTECT, blank=True, null=True
    )

    description = models.CharField(max_length=200, blank=True, null=True)
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    sort = models.CharField(max_length=200, blank=True, null=True)
    note = models.CharField(max_length=500, blank=True, null=True)
    rabatt = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        # Use ``*_id`` so the check doesn't trigger a SELECT to fetch the
        # related row just to test for presence.
        filled_refs = sum(
            [
                bool(self.offer_id),
                bool(self.share_article_id),
            ]
        )
        if filled_refs != 1:
            raise ValidationError("Must reference exactly one item type")


# FinalizedProtectedMixin must precede the concrete JasminModel in the MRO so its
# save()/delete() intercept (the other 9 protected models do this). With
# JasminModel first, Offer.save resolved straight to Model.save and the Python
# immutability layer was dead — leaving only the Postgres trigger.
class Offer(FinalizableMixin, FinalizedProtectedMixin, JasminModel):
    ALLOWED_FINALIZED_UPDATES = ["amount"]

    objects = FinalizedProtectedQuerySet.as_manager()

    year = models.PositiveSmallIntegerField(db_index=True)
    delivery_week = models.PositiveSmallIntegerField(
        db_index=True,
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    sort = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=40, blank=True, null=True)
    unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    size = models.CharField(
        max_length=1,
        choices=SizeVegetableOptions.choices,
        default=SizeVegetableOptions.M,
    )
    amount_per_pu = models.DecimalField(max_digits=7, decimal_places=3)
    used_crate = models.ForeignKey(
        "Crate", on_delete=models.PROTECT, blank=True, null=True
    )  # crate used for this offer

    offer_group = models.ForeignKey("OfferGroup", on_delete=models.PROTECT)
    reseller = models.ForeignKey(
        "Reseller", on_delete=models.PROTECT, blank=True, null=True
    )  # sometimes an offer is just for a specific reseller
    amount = models.DecimalField(
        max_digits=9, decimal_places=3
    )  # available amount in pu!!!
    # base_price = price_1
    # price_1, price_2, price_3 correspond to the tiers defined in TenantSettings
    price_1 = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    price_2 = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    price_3 = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    note = models.CharField(max_length=500, blank=True, null=True)

    cleaning = models.BooleanField(default=False)
    washing = models.BooleanField(default=False)
    comes_from_long_term_storage = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["year", "delivery_week"]),
        ]
        constraints = [
            # OFFER-2: at most ONE auto-created GENERAL offer (reseller IS NULL)
            # per slot. ``create_offers`` dedups in Python on this exact tuple,
            # but a double-click / two concurrent office users both pass the
            # one-shot ``exists()`` snapshot and INSERT → duplicate offers. The
            # constraint turns that race into a catchable IntegrityError and makes
            # the idempotency a real DB guarantee. PARTIAL on ``reseller IS NULL``
            # so a reseller-specific offer can still coexist with the general one
            # for the same slot (the ``reseller`` field's intended use).
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "share_article",
                    "unit",
                    "size",
                    "offer_group",
                ],
                condition=models.Q(reseller__isnull=True),
                name="offer_unique_general_per_slot",
            ),
            # Washed OR cleaned, never both (matches the planning/offers grid UI and
            # the OrderContent it seeds). Both-true double-transfers a long-term line
            # long→short in the goods-flow. NULL/False pass; only (True, True) fails.
            models.CheckConstraint(
                condition=~(models.Q(washing=True) & models.Q(cleaning=True)),
                name="offer_washing_cleaning_mutually_exclusive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.share_article.name} [{self.unit}] - ({self.amount_per_pu} {self.unit}/VPE)"

    def update_available_amount(self, ordered_amount: Decimal | int | float) -> None:
        if self.amount is None:
            raise ValidationError("No available amount set for this offer")
        ordered_amount = Decimal(str(ordered_amount))

        if self.amount < ordered_amount:
            raise ValidationError(
                f"Not enough stock available. Available: {self.amount}, Requested: {ordered_amount}"
            )
        self.amount -= ordered_amount
        self.save(update_fields=["amount"])

    def check_availability(self, requested_amount: Decimal | int | float) -> bool:
        if self.amount is None:
            return False
        return self.amount >= Decimal(str(requested_amount))


class Order(
    NumberedDocumentMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    CreatedMixin,
    JasminModel,
):
    DOCUMENT_TYPE = "order"  # this is for the NumberedDocumentMixin
    ALLOWED_FINALIZED_UPDATES = ["note"]
    # GoBD: order numbers form a gap-free monotonic sequence; the
    # finalized → unfinalized transition is refused at both the Python
    # save() layer and the Postgres trigger. See FinalizedProtectedMixin.
    IS_FINALIZED_ONE_WAY = True

    objects = FinalizedProtectedQuerySet.as_manager()

    year = models.PositiveSmallIntegerField(db_index=True)
    delivery_week = models.PositiveSmallIntegerField(
        db_index=True,
        validators=[MinValueValidator(1), MaxValueValidator(53)],
    )
    day_number = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )

    last_possible_ordering_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    harvesting_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    packing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    washing_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    cleaning_day = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    reseller = models.ForeignKey("Reseller", on_delete=models.PROTECT)
    is_donation = models.BooleanField(default=False)
    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["year", "delivery_week", "day_number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "number"],
                condition=models.Q(number__isnull=False),
                name="order_unique_prefix_number",
            ),
            # One order per reseller per delivery slot. The order-content and
            # crate-order-content services both ``get_or_create`` on exactly
            # these four fields, so duplicates would make that lookup raise
            # MultipleObjectsReturned; this constraint backs the invariant and
            # makes concurrent get_or_create race-safe.
            models.UniqueConstraint(
                fields=["reseller", "year", "delivery_week", "day_number"],
                name="order_unique_reseller_slot",
            ),
        ]

    def __str__(self) -> str:
        return f"Order {self.display_number} - {self.reseller} - Week {self.delivery_week}/{self.year}"

    def save(self, *args, **kwargs) -> None:
        self.save_with_number_retry(*args, **kwargs)

    def unfinalize(self) -> None:
        """Orders are legally one-way once finalized.

        Order numbers must form a gap-free, monotonic sequence (GoBD).
        Allowing unfinalize → edit → re-finalize would silently change the
        document the number points to. To revise, create a new order.
        """
        raise FinalizedError(
            "Cannot unfinalize Order — finalized orders are immutable."
            " To revise, create a new order."
        )

    def _all_crate_contents(self) -> list:
        # CrateOrderContent has a XOR parent: attached EITHER directly to the
        # order OR to an OrderContent (an offer-bound deposit, with order=NULL).
        # crateordercontent_set sees only the direct ones, so the offer-bound
        # deposits must be added explicitly — the DN/invoice already include them
        # (create_from_order copies Q(order=...) | Q(order_content__order=...)),
        # so without this the order PREVIEW total understates net and jumps the
        # moment a delivery note is created. Mirrors finalize_order.
        # Built from the reverse accessors (not a fresh filter) so a list endpoint
        # prefetching both edges — crateordercontent_set +
        # ordercontent_set__crateordercontent_set — stays query-free per order.
        contents = list(self.crateordercontent_set.all())
        for order_content in self.ordercontent_set.all():
            contents.extend(order_content.crateordercontent_set.all())
        return contents

    @property
    def sum_netto(self) -> Decimal:
        return sum_netto(self.ordercontent_set.all()) + sum_netto(
            self._all_crate_contents()
        )

    @property
    def tax_breakdown(self) -> list[dict]:
        return tax_breakdown(self.ordercontent_set.all(), self._all_crate_contents())

    @property
    def sum_brutto(self) -> Decimal:
        return sum_brutto(
            list(self.ordercontent_set.all()) + list(self._all_crate_contents())
        )


class OrderContent(FinalizableMixin, FinalizedProtectedMixin, OrderableItem):
    PARENT_FK_FIELDS = ["order"]
    order = models.ForeignKey("Order", on_delete=models.PROTECT)

    objects = FinalizedProtectedQuerySet.as_manager()

    amount = models.DecimalField(max_digits=7, decimal_places=3, blank=True, null=True)

    cleaning = models.BooleanField(default=False, blank=True, null=True)
    washing = models.BooleanField(default=False, blank=True, null=True)
    comes_from_long_term_storage = models.BooleanField(
        default=False, blank=True, null=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "offer"],
                name="unique_offer_per_order",
                condition=models.Q(offer__isnull=False),
            ),
            # Washed OR cleaned, never both (matches the orders grid UI + the offer
            # it inherits from). Both-true double-transfers a long-term line long→short
            # in the goods-flow. NULL/False pass; only (True, True) is rejected.
            models.CheckConstraint(
                condition=~(models.Q(washing=True) & models.Q(cleaning=True)),
                name="ordercontent_washing_cleaning_mutually_exclusive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.share_article} x{self.amount} (Order {self.order_id})"

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Cascade-delete the parent ``Order`` when removing the last content.

        The order is auto-removed only when **both** ``OrderContent`` and
        ``CrateOrderContent`` (loose crates attached directly to the order)
        are gone. Otherwise the order would be deleted out from under a
        still-referenced crate row.
        """
        order = self.order
        result = super().delete(*args, **kwargs)
        if (
            order
            and not order.ordercontent_set.exists()
            and not order.crateordercontent_set.exists()
        ):
            order.delete()
        return result

    # ------------------------------------------------------------------ #
    # Effective-field resolution
    #
    # ``unit`` and ``size`` live directly on the OrderContent row (they
    # are inherited NOT-NULL fields from ``OrderableItem`` with a model
    # default for ``size``). Read them as ``self.unit`` / ``self.size``;
    # there is no fallback chain for these.
    #
    # ``share_article`` MAY live on the row or be inherited from the
    # offer; ``amount_per_pu`` does NOT exist on OrderContent at all
    # (it's only on ``Offer``). Both of these get resolved here so every
    # reader (line pricing, the commissioning list, serializers,
    # snapshot/movement creation) agrees on precedence. See
    # ``tests_model_methods_and_mixins/test_order_content_resolvers.py``
    # for the lock-down test.
    # ------------------------------------------------------------------ #

    def resolve_share_article(self):
        """The ``ShareArticle`` this content effectively represents.

        By model invariant (``OrderableItem.clean``) an OrderContent has
        EXACTLY ONE of ``offer`` / ``share_article`` populated, so only
        one of these branches is ever live on a persisted row:

          * Offer-bound OC → returns ``offer.share_article``.
          * Ad-hoc OC      → returns ``self.share_article``.

        The content-first ordering and the final ``None`` return are
        defensive against rows written via raw SQL (bypassing clean) or
        future schema drift; normal data never reaches them.
        """
        if self.share_article_id:
            return self.share_article
        if self.offer and self.offer.share_article_id:
            return self.offer.share_article
        return None

    def resolve_amount_per_pu(self) -> Decimal:
        """Fallback chain: offer → share_article default (for ``self.unit``) → 1.

        ``amount_per_pu`` is not a column on OrderContent; the offer is
        the primary source. When there is no offer (ad-hoc line), the
        share article's ``default_{kg,pieces,bunches}_per_pu_reseller``
        for the line's ``unit`` is the next-best source. Last resort is
        ``Decimal("1")`` so line_netto never silently zeroes out.
        """
        if self.offer and self.offer.amount_per_pu:
            return Decimal(self.offer.amount_per_pu)
        article = self.resolve_share_article()
        if article is not None:
            article_value = article.get_amount_per_pu_for_reseller(self.unit)
            if article_value:
                return Decimal(article_value)
        return Decimal("1")

    # ``line_netto`` / ``line_brutto`` are inherited UNCHANGED from
    # LinePricingMixin: ``amount × price_per_unit × (1 − rabatt/100)``.
    # ``OrderContent.amount`` is in physical UNITS (kg/pcs/bunch) and
    # ``price_per_unit`` is €/unit, so there is NO ``amount_per_pu`` factor in
    # the price — the same formula the frontend mirror (``computeLineNetto``)
    # and the delivery-note / invoice content lines use, so the net reconciles
    # order == delivery note == invoice. (``amount_per_pu`` is for PU conversion
    # only — ``ordered_amount`` and offer-stock debiting — and is surfaced for
    # display via ``resolve_amount_per_pu``; it must NOT enter line pricing.)


class CrateOrderContent(
    LinePricingMixin, FinalizableMixin, FinalizedProtectedMixin, JasminModel
):
    PARENT_FK_FIELDS = ["order", "order_content"]
    objects = FinalizedProtectedQuerySet.as_manager()

    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )
    order = models.ForeignKey("Order", on_delete=models.CASCADE, blank=True, null=True)

    crate_type = models.ForeignKey("Crate", on_delete=models.PROTECT)
    amount = models.IntegerField()
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    rabatt = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        constraints = [
            # Exactly one of (order_content, order) must be set.
            models.CheckConstraint(
                condition=(
                    models.Q(order_content__isnull=False, order__isnull=True)
                    | models.Q(order_content__isnull=True, order__isnull=False)
                ),
                name="crateordercontent_xor_parent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.crate_type} x{self.amount}"

    def clean(self) -> None:
        super().clean()
        if bool(self.order_content_id) == bool(self.order_id):
            raise ValidationError(
                "Set exactly one of order_content / order on CrateOrderContent."
            )

    def delete(self, *args, **kwargs):
        """Mirror :meth:`OrderContent.delete` cascade.

        When this crate row is the last child of its order (no more
        ``OrderContent`` and no more ``CrateOrderContent``), remove the
        now-empty order too. Crates attached via ``order_content`` rather
        than directly to ``order`` rely on the OrderContent cascade.
        """
        order = self.order or (self.order_content.order if self.order_content else None)
        result = super().delete(*args, **kwargs)
        if (
            order
            and not order.ordercontent_set.exists()
            and not order.crateordercontent_set.exists()
        ):
            order.delete()
        return result


class CrateDeliveryNoteContent(
    SourceSnapshotMixin,
    LinePricingMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    JasminModel,
):
    PARENT_FK_FIELDS = ["delivery_note"]
    objects = FinalizedProtectedQuerySet.as_manager()

    delivery_note = models.ForeignKey(
        "DeliveryNoteReseller",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="crate_items",
    )
    crate_type = models.ForeignKey("Crate", on_delete=models.PROTECT)
    amount = models.IntegerField()
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    rabatt = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
    )
    note = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.crate_type} x{self.amount}"

    def delete(self, *args, **kwargs):
        """Mirror :meth:`DeliveryNoteContent.delete` cascade.

        When this is the last child of the delivery note (no more items and
        no more crate items), remove the now-empty DN too.
        """
        delivery_note = self.delivery_note
        result = super().delete(*args, **kwargs)
        if (
            delivery_note
            and not delivery_note.items.exists()
            and not delivery_note.crate_items.exists()
        ):
            delivery_note.delete()
        return result


class CrateContentInvoiceReseller(
    SourceSnapshotMixin,
    LinePricingMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    JasminModel,
):
    PARENT_FK_FIELDS = ["invoice"]
    objects = FinalizedProtectedQuerySet.as_manager()

    invoice = models.ForeignKey(
        "InvoiceReseller",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="crate_items",
    )

    crate_type = models.ForeignKey("Crate", on_delete=models.PROTECT)
    amount = models.IntegerField()
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    rabatt = models.PositiveSmallIntegerField(
        blank=True, null=True, validators=[MaxValueValidator(100)]
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)
    note = models.CharField(max_length=500, blank=True, null=True)
    # Provenance link to the source crate delivery-note lines, mirroring
    # InvoiceResellerContent.delivery_note_contents for article lines. Without
    # it a crate-only delivery note (no article lines, so an empty article M2M)
    # is invisible to every "which invoice belongs to this DN / is it already
    # invoiced" guard — making it double-billable and unreachable by the
    # finalize/delete/set-paid/reminder paths. Set once at invoice creation
    # (before finalization), never mutated after.
    crate_delivery_note_contents = models.ManyToManyField(
        "CrateDeliveryNoteContent",
        blank=True,
        related_name="+",
    )

    def __str__(self) -> str:
        return f"{self.crate_type} x{self.amount} (Invoice {self.invoice_id})"

    def delete(self, *args, **kwargs):
        """Auto-delete parent invoice when **both** items and crate-items gone."""
        invoice = self.invoice
        result = super().delete(*args, **kwargs)

        if invoice and not invoice.items.exists() and not invoice.crate_items.exists():
            invoice.delete()

        return result


class DeliveryNoteContent(
    SourceSnapshotMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    OrderableItem,
):
    PARENT_FK_FIELDS = ["delivery_note"]
    objects = FinalizedProtectedQuerySet.as_manager()

    delivery_note = models.ForeignKey(
        "DeliveryNoteReseller", on_delete=models.CASCADE, related_name="items"
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.PROTECT, blank=True, null=True
    )
    amount = models.DecimalField(max_digits=7, decimal_places=3, blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.share_article} x{self.amount}"

    def delete(self, *args, **kwargs):
        """Auto-delete parent DN when **both** items and crate-items gone."""
        delivery_note = self.delivery_note
        result = super().delete(*args, **kwargs)

        if (
            delivery_note
            and not delivery_note.items.exists()
            and not delivery_note.crate_items.exists()
        ):
            delivery_note.delete()

        return result


class InvoiceResellerContent(
    SourceSnapshotMixin, FinalizableMixin, FinalizedProtectedMixin, OrderableItem
):
    ALLOWED_FINALIZED_UPDATES: list[str] = []
    PARENT_FK_FIELDS = ["invoice"]

    objects = FinalizedProtectedQuerySet.as_manager()

    invoice = models.ForeignKey(
        "InvoiceReseller", on_delete=models.CASCADE, related_name="items"
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )
    delivery_note_contents = models.ManyToManyField(
        "DeliveryNoteContent",
        blank=True,
        related_name="+",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=3)

    def __str__(self) -> str:
        return f"{self.share_article} x{self.amount} (Invoice {self.invoice_id})"

    def delete(self, *args, **kwargs):
        """Auto-delete parent invoice when **both** items and crate-items gone."""
        invoice = self.invoice
        result = super().delete(*args, **kwargs)

        if invoice and not invoice.items.exists() and not invoice.crate_items.exists():
            invoice.delete()

        return result


class DeliveryNoteReseller(
    DateDocumentMixin,
    NumberedDocumentMixin,
    CreatedMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    JasminModel,
):
    DOCUMENT_TYPE = "delivery_note"  # this is for the NumberedDocumentMixin

    ALLOWED_FINALIZED_UPDATES = [
        "file",
        "has_been_sent_to_reseller_at",
    ]
    # HGB §257: issued Lieferscheine are archived unchanged.
    IS_FINALIZED_ONE_WAY = True

    objects = FinalizedProtectedQuerySet.as_manager()

    order = models.OneToOneField(
        "Order", on_delete=models.CASCADE, related_name="delivery_note"
    )

    file = models.FileField(upload_to="deliverynotesresellers/", blank=True, null=True)

    # Single source of truth for the "we sent it" state — the
    # timestamp. ``has_been_sent_to_reseller`` is derived from it
    # (see property below). A previous schema kept a redundant
    # boolean column, which created a drift hazard whenever code
    # forgot to update both fields. Dropped pre-squash.
    has_been_sent_to_reseller_at = models.DateTimeField(blank=True, null=True)

    is_cancelled = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "number"],
                condition=models.Q(number__isnull=False),
                name="deliverynotereseller_unique_prefix_number",
            ),
        ]

    def __str__(self) -> str:
        return f"Delivery Note {self.display_number} - {self.order.reseller}"

    def clean(self) -> None:
        super().clean()
        # The document ``date`` (a DateField) must not be later than the
        # timestamps stamped when the note is finalized / sent (both
        # DateTimeFields). Compare on the date component. NULL-tolerant: each
        # pair is only enforced when both members are set. These cross-type
        # (DateField vs DateTimeField) rules live in ``clean()`` only — a DB
        # CheckConstraint would need a Cast on the timestamp column.
        if (
            self.date is not None
            and self.finalized_at is not None
            and self.date > self.finalized_at.date()
        ):
            raise ValidationError(
                {"date": "Document date must be on or before the finalization date."}
            )
        if (
            self.date is not None
            and self.has_been_sent_to_reseller_at is not None
            and self.date > self.has_been_sent_to_reseller_at.date()
        ):
            raise ValidationError(
                {
                    "date": (
                        "Document date must be on or before the date it was sent "
                        "to the reseller."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:

        if not self.date:
            raise DocumentDateRequired(
                "DeliveryNoteReseller.date is required — pass it explicitly"
                " or go through DeliveryNoteService.create_from_order."
            )
        self.save_with_number_retry(*args, **kwargs)

    @property
    def has_been_sent_to_reseller(self) -> bool:
        """True iff ``DeliveryNoteService.send_to_reseller`` has
        flipped the timestamp. The serializer + the view-layer
        aggregation read this property instead of a stored field —
        single source of truth, zero drift."""
        return self.has_been_sent_to_reseller_at is not None

    def unfinalize(self) -> None:
        """Delivery notes are legally one-way once finalized.

        Once issued (Lieferschein), the document and its number must be
        archived unchanged (GoBD / HGB §257). To revise, cancel and create
        a new delivery note.
        """
        raise FinalizedError(
            "Cannot unfinalize DeliveryNoteReseller — finalized"
            " delivery notes are immutable. To revise, cancel and create"
            " a new delivery note."
        )

    @property
    def sum_netto(self) -> Decimal:
        return sum_netto(self.items.all()) + sum_netto(self.crate_items.all())

    @property
    def tax_breakdown(self) -> list[dict]:
        return tax_breakdown(self.items.all(), self.crate_items.all())

    @property
    def sum_brutto(self) -> Decimal:
        return sum_brutto(list(self.items.all()) + list(self.crate_items.all()))


class InvoiceReseller(
    DateDocumentMixin,
    NumberedDocumentMixin,
    CreatedMixin,
    FinalizableMixin,
    FinalizedProtectedMixin,
    PayableMixin,
    JasminModel,
):
    DOCUMENT_TYPE = "invoice_reseller"  # this is for the NumberedDocumentMixin
    # Note: ``cancelled_at`` and ``cancelled_by`` are NOT on this model —
    # cancellation is tracked via ``cancelled_by_invoice`` (the storno).
    # Earlier ALLOWED entries for those two fields were dead refs from a
    # removed ``CancellableMixin`` inheritance; dropped in the 2026-05-24
    # state-transition audit.
    ALLOWED_FINALIZED_UPDATES = [
        "has_been_paid",
        "paid_at",
        "cancelled_by_invoice",
        "has_been_sent_to_reseller_at",
        "has_been_sent_to_accounting_at",
        "file",
        "xml_file",
        # ``note`` is internal office annotation, not part of the legally
        # immutable invoice document (Order allows it for the same reason).
        # The matching Postgres trigger allowlist lives in
        # ``PROTECTED_TABLES`` in migration
        # ``0002_finalized_protection_and_reference_data`` — keep the two in
        # sync (see the FinalizedProtectedMixin note in CLAUDE.md).
        "note",
    ]
    # UStG §14: issued invoices are legally immutable. To reverse, create
    # a storno; to revise, issue a correction document.
    IS_FINALIZED_ONE_WAY = True

    objects = FinalizedProtectedQuerySet.as_manager()
    reseller = models.ForeignKey(
        "Reseller", on_delete=models.PROTECT, related_name="invoices"
    )

    file = models.FileField(upload_to="invoicesresellers/", blank=True, null=True)
    xml_file = models.FileField(
        upload_to="invoicesresellers/xml/", blank=True, null=True
    )

    document_hash = models.CharField(max_length=64, blank=True, null=True)
    # Which ``build_hash_payload`` shape produced ``document_hash``. v1 (the
    # legacy default) seals number/prefix/date/reseller_id + line items only;
    # v2 additionally seals the resolved §14/§14a recipient block and the
    # document-type / cancellation identity. Stored per-invoice so legacy v1
    # documents keep validating against their original hash (no mass false
    # drift) while newly finalized invoices get the wider tamper surface.
    document_hash_version = models.PositiveSmallIntegerField(default=1)

    # Frozen §14/§14a recipient block, captured from the live Reseller/Contact
    # at finalization and sealed into ``document_hash`` (v2). Makes the invoice
    # self-contained: a later edit — or GDPR anonymization — of the reseller's
    # general record can neither re-render nor drift the immutable document.
    # Set on the (still-unfinalized) finalize save, then immutable; the generic
    # FinalizedProtected trigger protects it like every other sealed column.
    recipient_snapshot = models.JSONField(blank=True, null=True)

    # Single source of truth for both "sent" states — just the
    # timestamps. The previous schema also stored
    # ``has_been_sent_via_email`` and ``has_been_sent_to_accounting``
    # booleans, which created a drift hazard whenever code forgot to
    # update both. ``has_been_sent_to_reseller`` and
    # ``has_been_sent_to_accounting`` are derived properties on the
    # model (see below). Dropped pre-squash.
    has_been_sent_to_reseller_at = models.DateTimeField(blank=True, null=True)
    has_been_sent_to_accounting_at = models.DateTimeField(blank=True, null=True)
    has_been_paid = models.BooleanField(default=False)
    # Document type and relationships
    document_type = models.CharField(
        max_length=20,
        choices=[
            ("invoice", "Invoice"),
            ("storno", "Storno/Cancellation"),
            ("correction", "Correction"),
        ],
        default="invoice",
    )

    # References to related documents
    cancels_invoice = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,  # Don't allow deletion of referenced invoice
        blank=True,
        null=True,
        related_name="+",
        help_text="If this is a storno, reference to the original invoice being cancelled",
    )

    cancelled_by_invoice = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="If this invoice was cancelled, reference to the storno document",
    )

    # Reason for corrections/stornos
    correction_reason = models.TextField(
        blank=True,
        null=True,
        help_text="Explanation for why this correction/storno was created",
    )
    items_are_grouped = models.BooleanField(default=False)
    note = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        constraints = [
            # ``document_type`` is part of the key because invoice and
            # storno run independent number sequences (see
            # _base_number_queryset). Without it, a fresh tenant that
            # hasn't set ``correction_invoice_number_prefix`` would have
            # both sequences default to the same prefix and the DB would
            # refuse the second one — even though they're legitimately
            # different documents.
            models.UniqueConstraint(
                fields=["prefix", "number", "document_type"],
                condition=models.Q(number__isnull=False),
                name="invoicereseller_unique_prefix_number",
            ),
            # At most one storno per cancelled invoice. Backstops the
            # ``select_for_update`` re-check in ``InvoiceService.create_storno``
            # so even a non-locking write path cannot mint a second,
            # immutable credit note for the same original (double VAT
            # reversal). Scoped to ``storno`` only so a future ``correction``
            # document for the same invoice is not blocked.
            models.UniqueConstraint(
                fields=["cancels_invoice"],
                condition=models.Q(document_type="storno"),
                name="invoicereseller_unique_storno_per_invoice",
            ),
            # The payment due date must not precede the invoice ``date`` (both
            # DateFields). NULL-tolerant: only enforced when both are set.
            # ``paid_at >= due_date`` comes from PayableMixin.clean()
            # (datetime-vs-date, no DB constraint). A Meta CheckConstraint is
            # independent of the FinalizedProtected trigger allowlist.
            models.CheckConstraint(
                condition=Q(due_date__isnull=True)
                | Q(date__isnull=True)
                | Q(due_date__gte=F("date")),
                name="invoicereseller_due_date_after_date",
            ),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.display_number} - {self.reseller}"

    def clean(self) -> None:
        super().clean()

        # The payment due date must not precede the invoice date (both
        # DateFields). NULL-tolerant: only enforced when both are set.
        # ``paid_at >= due_date`` is enforced by PayableMixin.clean().
        if (
            self.due_date is not None
            and self.date is not None
            and self.due_date < self.date
        ):
            raise ValidationError(
                {"due_date": "Due date must be on or after the invoice date."}
            )

        if self.cancels_invoice == self:
            raise CommissioningError(
                "Invoice cannot cancel itself",
                code="invoice.cannot_cancel_self",
            )

        if self.cancels_invoice and self.cancels_invoice.cancels_invoice == self:
            raise CommissioningError(
                "Circular cancellation reference detected",
                code="invoice.circular_cancellation",
            )

        if self.document_type == "storno":
            if not self.cancels_invoice:
                raise CommissioningError(
                    "Storno must reference an invoice being cancelled",
                    code="invoice.storno_missing_target",
                )
            if self.cancels_invoice.document_type == "storno":
                raise CommissioningError(
                    "Cannot storno a storno",
                    code="invoice.cannot_storno_storno",
                )

        if self.document_type == "invoice" and self.cancels_invoice:
            raise ValidationError(
                "Regular invoice cannot have cancellation/replacement references"
            )

    def save(self, *args, **kwargs) -> None:
        # See ``DeliveryNoteReseller.save``: invoices are GoBD / UStG
        # documents — refuse to silently date them to "today" when the
        # caller forgot to resolve the date via
        # ``coerce_document_date`` / the service layer.
        if not self.date:
            raise DocumentDateRequired(
                "InvoiceReseller.date is required — pass it explicitly"
                " or go through InvoiceService."
            )
        self.full_clean()
        self.save_with_number_retry(*args, **kwargs)

    @property
    def has_been_sent_to_reseller(self) -> bool:
        """True iff ``InvoiceService.send_to_reseller`` has flipped
        the timestamp. Derived from
        ``has_been_sent_to_reseller_at`` — single source of truth,
        zero drift. See sibling property + the matching pattern on
        DeliveryNoteReseller."""
        return self.has_been_sent_to_reseller_at is not None

    @property
    def has_been_sent_to_accounting(self) -> bool:
        """True iff ``InvoiceService.send_to_accounting`` has
        flipped the timestamp. Derived from
        ``has_been_sent_to_accounting_at``."""
        return self.has_been_sent_to_accounting_at is not None

    def unfinalize(self) -> None:
        """Invoices are legally one-way once finalized.

        Once issued (Rechnung), the document and its number must be
        archived unchanged (GoBD / UStG §14). To reverse, create a
        storno; to revise, issue a correction document.
        """
        raise FinalizedError(
            "Cannot unfinalize InvoiceReseller — finalized invoices are"
            " immutable. To reverse, create a storno; to revise, issue a"
            " correction document."
        )

    def delete(self, *args, **kwargs):
        # Defence in depth: storno / correction documents stay locked even
        # if they were ever unfinalized through some back-door path — the
        # audit link (``cancelled_by_invoice``) must be preserved.
        if self.document_type in ("storno", "correction"):
            raise FinalizedError(
                f"Cannot delete {self.document_type} document — it is"
                " legally immutable."
            )
        return super().delete(*args, **kwargs)

    def can_be_cancelled(self) -> bool:
        """True iff a storno can legally be created for this invoice.

        A storno is itself an auto-finalized invoice that points back via
        ``cancels_invoice``. To keep the audit chain unambiguous we require:

        * this is a regular ``invoice`` (cannot storno a storno or correction);
        * it is finalized (unfinalized drafts can simply be deleted);
        * it has not already been cancelled (no double storno).
        """
        return (
            self.document_type == "invoice"
            and self.is_finalized
            and self.cancelled_by_invoice_id is None
        )

    def resolved_recipient(self) -> dict:
        """The §14 / §14a recipient block as RENDERED on the invoice.

        For a FINALIZED invoice this returns the frozen ``recipient_snapshot``
        captured at finalization — the legally-retained (UStG §14b) recipient as
        of issue. So a later edit to the live Reseller / Contact row — including
        GDPR anonymization of the reseller's general record — neither re-renders
        the immutable PDF nor drifts ``document_hash``. A draft (no snapshot yet)
        resolves live so the preview tracks current data.
        """
        if self.recipient_snapshot is not None:
            return self.recipient_snapshot
        return self._live_recipient()

    def _live_recipient(self) -> dict:
        """Resolve the recipient block from the LIVE Reseller / Contact rows —
        the reseller's ``invoice_*`` billing overrides with a fallback to
        ``contact.*`` (mirrors ``InvoiceResellerSerializer``'s ``reseller_*``
        resolution). Frozen into ``recipient_snapshot`` at finalization (see
        ``resolved_recipient``); not read directly off a finalized invoice."""
        reseller = self.reseller
        contact = getattr(reseller, "contact", None)

        def pick(invoice_attr: str, contact_attr: str):
            value = getattr(reseller, invoice_attr, None)
            if value:
                return value
            return getattr(contact, contact_attr, None) if contact else None

        return {
            "name": pick("invoice_name", "name"),
            "name2": getattr(reseller, "invoice_name2", None),
            "address": pick("invoice_address", "address"),
            "zip": pick("invoice_plz", "zip_code"),
            "city": pick("invoice_city", "city"),
            "country": getattr(contact, "country", None) if contact else None,
            "uid": getattr(contact, "uid", None) if contact else None,
        }

    def _get_tenant_settings_fields(self) -> tuple[str, str]:
        if self.document_type in ("storno", "correction"):
            return (
                "invoice_numbers_start_new_at_year_change",
                "correction_invoice_number_prefix",
            )
        return super()._get_tenant_settings_fields()

    def _base_number_queryset(self) -> models.QuerySet:
        """Filter by ``document_type`` so invoices and stornos have separate sequences."""
        is_storno = self.document_type in ("storno", "correction")
        if is_storno:
            return self.__class__.objects.filter(
                document_type__in=["storno", "correction"]
            )
        return self.__class__.objects.filter(document_type="invoice")

    def _advisory_lock_key(self) -> str:
        """Two independent sequences live in this table — invoice and
        storno/correction — so the advisory lock must include the
        sequence discriminator. Without it, finalising an invoice would
        block finalising an unrelated storno on the same connection
        for no reason.
        """
        sequence = (
            "storno" if self.document_type in ("storno", "correction") else "invoice"
        )
        return f"numbered_doc:{self.__class__.__name__}:{sequence}"

    def mark_as_paid(self, user: object | None = None) -> None:
        self.has_been_paid = True
        self.paid_at = timezone.now()
        self.save(update_fields=["has_been_paid", "paid_at"])

    def mark_as_unpaid(self) -> None:
        self.has_been_paid = False
        self.paid_at = None
        self.save(update_fields=["has_been_paid", "paid_at"])

    @property
    def sum_netto(self) -> Decimal:
        return sum_netto(self.items.all()) + sum_netto(self.crate_items.all())

    @property
    def tax_breakdown(self) -> list[dict]:
        return tax_breakdown(self.items.all(), self.crate_items.all())

    @property
    def sum_brutto(self) -> Decimal:
        return sum_brutto(list(self.items.all()) + list(self.crate_items.all()))


class LabelTemplate(JasminModel):
    """Reserved for a future label-printing feature — intentionally unwired.

    Defined here and in ``0001_initial`` only: not exported from
    ``models/__init__`` and with no serializer, viewset, service or read path.
    Kept on purpose until the feature is built or deliberately dropped.
    """

    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    # Physical dimensions in mm (for printing)
    width_mm = models.IntegerField(
        validators=[MinValueValidator(10), MaxValueValidator(300)],
        help_text="Label width in millimeters",
    )
    height_mm = models.IntegerField(
        validators=[MinValueValidator(5), MaxValueValidator(200)],
        help_text="Label height in millimeters",
    )
    elements = models.JSONField(
        default=list, help_text="List of label elements with positioning and styling"
    )

    def __str__(self) -> str:
        return self.name
