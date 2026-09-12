from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField

from .base import JasminModel
from .choices import (
    ShareOptions,
    UnitOptions,
)
from .mixin import (
    PricingMixin,
    TimeBoundMixin,
    time_bound_valid_range_constraint,
)


class Season(JasminModel, TimeBoundMixin):
    # Empty group = one GLOBAL open season at a time (no grouping field):
    # creating a new season auto-closes the open predecessor.
    overlap_unique_fields = ()

    weeks_without_delivery = ArrayField(
        base_field=models.IntegerField(
            validators=[MinValueValidator(1), MaxValueValidator(53)]
        ),
        default=list,
        blank=True,
    )

    class Meta:
        # NOTE: the "one OPEN season globally" backstop is a partial unique
        # index installed via migration 0015 (RunSQL). The global overlap group
        # (overlap_unique_fields = ()) has no column to scope a Django
        # UniqueConstraint on, so it can't live here in Meta.constraints.
        constraints = [
            time_bound_valid_range_constraint("season_valid_range"),
        ]

    def __str__(self) -> str:
        return f"Season {self.valid_from.year} ({self.valid_from} - {self.valid_until})"


class Storage(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.TextField(
        blank=True, null=True
    )  # Use TextField for longer text
    is_long_term_harvest_storage = models.BooleanField(default=False)
    is_short_term_harvest_storage = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # At most ONE storage may be flagged as the short-term harvest
            # storage (and likewise for long-term). Implemented as a partial
            # unique constraint scoped by the boolean filter — since the
            # field value is True for every row in scope, only one can exist.
            models.UniqueConstraint(
                fields=["is_short_term_harvest_storage"],
                condition=models.Q(is_short_term_harvest_storage=True),
                name="storage_single_short_term_harvest",
            ),
            models.UniqueConstraint(
                fields=["is_long_term_harvest_storage"],
                condition=models.Q(is_long_term_harvest_storage=True),
                name="storage_single_long_term_harvest",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {'Long-term' if self.is_long_term_harvest_storage else 'Short-term' if self.is_short_term_harvest_storage else 'General'}"

    @classmethod
    def short_term_harvest(cls) -> Storage | None:
        """The single short-term harvest storage (a partial-unique singleton —
        see ``Meta.constraints``). ``None`` if the tenant hasn't flagged one."""
        return cls.objects.filter(is_short_term_harvest_storage=True).first()

    @classmethod
    def long_term_harvest(cls) -> Storage | None:
        """The single long-term harvest storage (partial-unique singleton)."""
        return cls.objects.filter(is_long_term_harvest_storage=True).first()

    @staticmethod
    def select_harvest(
        *,
        short_term: Storage | None,
        long_term: Storage | None,
        comes_from_long_term: bool,
    ) -> Storage | None:
        """Pick the harvest storage for one packing line.

        When the line comes from long-term storage the produce IS deposited
        there at harvest. A washed/cleaned line is then moved to short-term by
        the WASH/CLEAN transfer pair (``_create_theoretical_movements``) — which
        debits ``long_term_harvest()`` and credits ``short_term_harvest()``. So
        the harvest storage must NOT depend on washing/cleaning: depositing a
        washed long-term line straight to short-term would double-count it (the
        transfer also credits short-term) and leave a phantom negative on
        long-term that the harvest never offset.

        Operates on already-fetched instances so a caller fetches both once
        (``short_term_harvest()`` / ``long_term_harvest()``) outside its
        per-row loop — no per-row queries."""
        if comes_from_long_term:
            return long_term
        return short_term


# this model contains everything that can go into shares, like vegetable, fruit, mushrooms, eggs
class ShareArticle(JasminModel, PricingMixin):
    # Basic info
    is_active = models.BooleanField(default=True, db_index=True)
    is_extra = models.BooleanField(
        default=False, db_index=True
    )  # for non-article items like gardening courses, machine use
    article_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True, null=True)

    # Classification
    share_option = models.CharField(
        max_length=50,
        choices=ShareOptions.choices,
        blank=True,
        null=True,
    )
    # for the rare case that it is used in two or even three shares types (i.e. in veg share, like apples and only in fruit shares)
    share_option2 = models.CharField(
        max_length=50,
        choices=ShareOptions.choices,
        blank=True,
        null=True,
    )
    share_option3 = models.CharField(
        max_length=50,
        choices=ShareOptions.choices,
        blank=True,
        null=True,
    )
    is_purchased = models.BooleanField(default=False)
    is_sold_to_resellers = models.BooleanField(default=False)
    for_markets = models.BooleanField(default=False)

    class OrganicStatus(models.TextChoices):
        ORGANIC = "organic", "Bio"
        IN_CONVERSION = "in_conversion", "Umstellung"
        CONVENTIONAL = "conventional", "Konventionell"

    organic_status = models.CharField(
        max_length=20,
        choices=OrganicStatus.choices,
        default=OrganicStatus.CONVENTIONAL,
    )

    # Units
    default_movement_unit = models.CharField(max_length=10, choices=UnitOptions.choices)
    default_offer_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )
    default_harvesting_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )
    default_packing_boxes_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )
    default_commissioning_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )
    default_market_unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )

    # Size variations (seasonal)
    kg_per_piece_S = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    kg_per_piece_M = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    kg_per_piece_L = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )

    kg_per_bunch_S = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    kg_per_bunch_M = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    kg_per_bunch_L = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )

    pieces_per_kg_S = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    pieces_per_kg_M = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    pieces_per_kg_L = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )

    pieces_per_bunch_S = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    pieces_per_bunch_M = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )
    pieces_per_bunch_L = models.DecimalField(
        max_digits=5, decimal_places=3, blank=True, null=True
    )

    # PU definitions
    default_kg_per_pu_harvest = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_kg_per_pu_harvest_before_washing = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )

    default_pieces_per_pu_harvest = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_bunches_per_pu_harvest = models.IntegerField(blank=True, null=True)

    default_crate_harvest = models.ForeignKey(
        "Crate",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    default_crate_reseller = models.ForeignKey(
        "Crate",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    default_kg_per_pu_reseller = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_pieces_per_pu_reseller = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_bunches_per_pu_reseller = models.IntegerField(blank=True, null=True)

    default_kg_per_pu_purchase = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_pieces_per_pu_purchase = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    default_bunches_per_pu_purchase = models.IntegerField(blank=True, null=True)

    default_packing_station = models.PositiveSmallIntegerField(blank=True, null=True)
    percentage_added_to_bulk_packing_list = models.PositiveSmallIntegerField(
        blank=True, null=True
    )
    percentage_added_to_commissioning_list_packing = models.PositiveSmallIntegerField(
        default=5
    )  # this because the commissioning list packing needs to provide maybe 5% more salads, because experience shows
    # that 5% are bad

    # Suppliers
    seller_1 = models.ForeignKey(
        "Reseller",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="+",
    )
    seller_2 = models.ForeignKey(
        "Reseller",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="+",
    )

    class Meta:
        constraints = [
            # Extra articles (is_extra=True) may only be priced/managed in
            # pieces — they are non-article line items (e.g. gardening
            # courses, machine use) where weight or bunch units don't apply.
            models.CheckConstraint(
                condition=models.Q(is_extra=False)
                | models.Q(default_movement_unit="PCS"),
                name="sharearticle_is_extra_only_pcs",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.default_movement_unit} - {self.is_purchased}"

    def get_amount_per_pu_for_reseller(self, unit):
        """Return the per-PU amount for reseller offers in ``unit``.

        Returns ``None`` for unknown / missing units. Lookup is
        case-insensitive against ``UnitOptions``.
        """
        if not unit:
            return None
        unit_map = {
            "KG": self.default_kg_per_pu_reseller,
            "PCS": self.default_pieces_per_pu_reseller,
            "BUNCH": self.default_bunches_per_pu_reseller,
        }
        return unit_map.get(unit.upper())


class DefaultShareArticleInShare(JasminModel):
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE
    )
    share_article = models.ForeignKey("ShareArticle", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=7, decimal_places=3)
    unit = models.CharField(
        max_length=10, choices=UnitOptions.choices, blank=True, null=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["share_article", "share_type_variation", "unit"],
                name="default_share_article_in_share_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.share_article} {self.quantity} {self.unit} in {self.share_type_variation}"


class ShareArticleNetPrice(JasminModel, TimeBoundMixin):
    overlap_unique_fields = ("share_article",)

    share_article = models.ForeignKey(
        "ShareArticle",
        on_delete=models.CASCADE,
        related_name="pricing",
    )

    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)  # in %
    # Box prices (for statistical purposes)
    net_price_for_boxes_kg = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_boxes_pieces = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_boxes_bunch = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    # Bulk pricing for resellers
    net_price_for_orders_kg_1 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_kg_2 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_kg_3 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    net_price_for_orders_pieces_1 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_pieces_2 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_pieces_3 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    net_price_for_orders_bunch_1 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_bunch_2 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    net_price_for_orders_bunch_3 = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    class Meta:
        constraints = [
            # One open (valid_until IS NULL) price window per article — the DB
            # backstop the other one-open TimeBound models carry. Closes the
            # open-vs-open race (Python _validate_no_overlap is TOCTOU);
            # get_pricing_on_date is the canonical invoice tax/net read, so the
            # active window must be unambiguous. Closed-range overlap stays
            # Python-only via _validate_no_overlap.
            models.UniqueConstraint(
                fields=["share_article"],
                condition=models.Q(valid_until__isnull=True),
                name="sharearticlenetprice_one_open_per_article",
            ),
            time_bound_valid_range_constraint("sharearticlenetprice_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.share_article} ({self.valid_from})"


class Crate(JasminModel, PricingMixin):
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=200)
    number = models.IntegerField(blank=True, null=True)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    note = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self) -> str:
        return self.short_name or self.name


class CrateNetPrice(JasminModel, TimeBoundMixin):
    overlap_unique_fields = ("crate",)

    crate = models.ForeignKey("Crate", on_delete=models.CASCADE, related_name="pricing")
    price = models.DecimalField(max_digits=5, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        constraints = [
            # One open price window per crate (DB backstop; see
            # ShareArticleNetPrice above).
            models.UniqueConstraint(
                fields=["crate"],
                condition=models.Q(valid_until__isnull=True),
                name="cratenetprice_one_open_per_crate",
            ),
            time_bound_valid_range_constraint("cratenetprice_valid_range"),
        ]

    def __str__(self) -> str:
        return f"{self.crate} ({self.valid_from})"


class ContactEntity(JasminModel):
    """Base model for entities that can be both delivery stations and resellers and sellers"""

    # Contact Information
    company_name = models.CharField(max_length=200, blank=True, null=True)
    first_name = models.CharField(max_length=200, blank=True, null=True)
    last_name = models.CharField(max_length=200, blank=True, null=True)
    acronym = models.CharField(max_length=200, blank=True, null=True)

    user = models.OneToOneField(
        "accounts.JasminUser",
        on_delete=models.SET_NULL,
        related_name="reseller_profile",
        blank=True,
        null=True,
    )

    address = models.CharField(max_length=300)
    zip_code = models.CharField(max_length=5)
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True, null=True)
    coords_lon = models.DecimalField(
        decimal_places=10, max_digits=12, null=True, blank=True
    )
    coords_lat = models.DecimalField(
        decimal_places=10, max_digits=12, null=True, blank=True
    )
    # Contact Details
    email = models.EmailField(max_length=150, blank=True, null=True)
    email_2 = models.CharField(max_length=150, blank=True, null=True)
    email_3 = models.EmailField(max_length=150, blank=True, null=True)
    order_email = models.EmailField(
        max_length=150, blank=True, null=True
    )  # separate email for purchases
    phone = models.CharField(max_length=150, blank=True, null=True)
    phone_2 = models.CharField(max_length=150, blank=True, null=True)
    phone_3 = models.CharField(max_length=150, blank=True, null=True)
    uid = models.CharField(max_length=100, blank=True, null=True)
    # Encrypted: bank-account identifier, never queried by value.
    iban = EncryptedCharField(max_length=34, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["company_name", "last_name"]),
        ]

    def __str__(self) -> str:
        return self.name or self.get_display_id()

    @property
    def name(self) -> str | None:
        """Get display name - company name if available, otherwise first + last name"""
        if self.company_name:
            return self.company_name

        name_parts = []
        if self.first_name:
            name_parts.append(self.first_name)
        if self.last_name:
            name_parts.append(self.last_name)

        return " ".join(name_parts) if name_parts else None
