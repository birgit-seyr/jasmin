from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .base import JasminModel
from .basics import ShareArticle
from .choices import DayNumberOptions
from .fields import delivery_week_field, size_vegetable_field, unit_field
from .mixin import ArchivableMixin, CreatedMixin, FinalizableMixin


def documentation_daily_unique(name: str) -> models.UniqueConstraint:
    """The per-(year, week, DAY, article, unit, size) uniqueness shared by the
    five plain documentation daily tables (Waste, WashAmount, CleanAmount and
    the additional-theoretical wash/clean variants). Only enforced when
    ``day_number`` is set. Callers pass their own ``name`` so each constraint
    keeps its existing DB identity — byte-identical, no migration.
    """
    return models.UniqueConstraint(
        fields=[
            "year",
            "delivery_week",
            "day_number",
            "share_article",
            "unit",
            "size",
        ],
        condition=models.Q(day_number__isnull=False),
        name=name,
    )


def documentation_year_week_indexes() -> list[models.Index]:
    """The ``(year, delivery_week)`` + ``(year, delivery_week, day_number)``
    index pair every daily documentation table declares.

    Returns FRESH ``Index`` instances per call so each concrete model auto-names
    them off its own table — keeping the generated index names (and therefore
    the schema) identical to the previous inline declarations.
    """
    return [
        models.Index(fields=["year", "delivery_week"]),
        models.Index(fields=["year", "delivery_week", "day_number"]),
    ]


class DocumentationMixin(models.Model):
    year = models.PositiveSmallIntegerField()
    delivery_week = delivery_week_field()
    day_number = models.PositiveSmallIntegerField(
        choices=DayNumberOptions.choices, blank=True, null=True
    )
    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )  # this is in kg/pcs/bunch

    # ``max_length=20`` preserves this column's historical width — every other
    # unit column is 10; normalising it would require a migration (out of scope).
    unit = unit_field(max_length=20)
    size = size_vegetable_field()
    storage = models.ForeignKey("Storage", on_delete=models.CASCADE)

    note = models.TextField(blank=True, null=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        label = self.share_article.name if self.share_article_id else "?"
        return f"{label} W{self.delivery_week}/{self.year}"


class RequiresShortTermStorageMixin(models.Model):
    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        if not self.storage_id:
            raise ValidationError({"storage": "Storage is required."})
        if not self.storage.is_short_term_harvest_storage:
            raise ValidationError(
                {"storage": "Storage must be the short-term harvest storage."}
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class RequiresHarvestStorageMixin(models.Model):
    """Storage must be a harvest storage — short-term OR long-term.

    Harvest and purchase theoreticals follow ``Storage.select_harvest``: a line
    that ``comes_from_long_term_storage`` is DEPOSITED in long-term storage at
    harvest (the WASH/CLEAN transfer pair later relocates it to short-term). So —
    unlike the wash/clean theoreticals, which always land short-term via
    ``_processing_storage`` and keep ``RequiresShortTermStorageMixin`` — a harvest
    (or purchase) row must accept EITHER harvest storage. Requiring short-term
    here made every long-term-line ``TheoreticalHarvest`` violate its own
    invariant (latent because ``bulk_create`` bypasses ``full_clean``; a later
    PATCH via the viewset would raise a 500). See goods-flow audit finding #9.
    """

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        if not self.storage_id:
            raise ValidationError({"storage": "Storage is required."})
        if not (
            self.storage.is_short_term_harvest_storage
            or self.storage.is_long_term_harvest_storage
        ):
            raise ValidationError(
                {
                    "storage": (
                        "Storage must be a harvest storage (short- or long-term)."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class Forecast(
    JasminModel, DocumentationMixin, FinalizableMixin, CreatedMixin, ArchivableMixin
):
    # override: storage is optional on Forecast
    storage = models.ForeignKey(
        "Storage", on_delete=models.CASCADE, blank=True, null=True
    )

    for_all_harvest_shares = models.BooleanField(default=True)  # for all
    for_all_harvest_shares_fruit = models.BooleanField(default=False)  # for all
    for_all_resellers = models.BooleanField(default=False)  # for all
    for_all_markets = models.BooleanField(default=False)  # for all
    bed_number = models.IntegerField(blank=True, null=True)
    plot = models.ForeignKey("Plot", on_delete=models.CASCADE, blank=True, null=True)

    sort_order = models.IntegerField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["year", "delivery_week", "share_article", "unit", "size"],
                name="forecast_unique_year_week_article_unit_size",
            ),
        ]
        indexes = [
            models.Index(fields=["year", "delivery_week"]),
            models.Index(fields=["year", "delivery_week", "share_article"]),
        ]

    def __str__(self) -> str:
        label = self.share_article.name if self.share_article_id else "?"
        return f"{label} W{self.delivery_week}/{self.year}"


class Plot(JasminModel):
    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class ForecastShareTypeVariation(JasminModel):
    forecast = models.ForeignKey("Forecast", on_delete=models.CASCADE)
    share_type_variation = models.ForeignKey(
        "ShareTypeVariation", on_delete=models.CASCADE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "share_type_variation"],
                name="forecastsharetypevariation_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.forecast} - {self.share_type_variation}"


class ForecastOfferGroup(JasminModel):
    forecast = models.ForeignKey("Forecast", on_delete=models.CASCADE)
    offer_group = models.ForeignKey("OfferGroup", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "offer_group"],
                name="forecastoffergroup_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.forecast} - {self.offer_group}"


class TheoreticalHarvest(
    JasminModel,
    DocumentationMixin,
    RequiresHarvestStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    share_content = models.ForeignKey(
        "ShareContent", on_delete=models.CASCADE, blank=True, null=True
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )
    forecast = models.ForeignKey(
        "Forecast", on_delete=models.CASCADE, blank=True, null=True
    )

    class Meta:
        indexes = documentation_year_week_indexes()


class AdditionalTheoreticalHarvest(
    JasminModel,
    DocumentationMixin,
    RequiresHarvestStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    for_share_content = models.BooleanField(default=False)
    for_order_content = models.BooleanField(default=False)

    class Meta:
        # ``day_number`` is nullable; only enforce uniqueness when day_number is set.
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "day_number",
                    "share_article",
                    "unit",
                    "size",
                    "for_share_content",
                    "for_order_content",
                ],
                condition=models.Q(day_number__isnull=False),
                name="addtheoreticalharvest_unique_full",
            ),
        ]
        indexes = documentation_year_week_indexes()


class Harvest(
    JasminModel, DocumentationMixin, FinalizableMixin, CreatedMixin, ArchivableMixin
):
    harvesting_crate = models.ForeignKey(
        "Crate", on_delete=models.SET_NULL, blank=True, null=True
    )
    amount_per_pu = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    # the following fields show whether the harvested stuff needs to be washed (some salads?) or cleaned (?)
    # the info comes from the harvest share planning or can also be given directly in the harvesting list
    washing = models.BooleanField(default=False)
    cleaning = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "day_number",
                    "share_article",
                    "unit",
                    "size",
                    "storage",
                ],
                condition=models.Q(day_number__isnull=False),
                name="harvest_unique_year_week_day_article_unit_size_storage",
            ),
        ]
        indexes = documentation_year_week_indexes()


class Waste(JasminModel, DocumentationMixin, CreatedMixin, ArchivableMixin):
    class Meta:
        constraints = [
            documentation_daily_unique("waste_unique_year_week_day_article_unit_size"),
        ]
        indexes = documentation_year_week_indexes()


class TheoreticalPurchase(
    JasminModel,
    DocumentationMixin,
    RequiresHarvestStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    share_content = models.ForeignKey(
        "ShareContent", on_delete=models.CASCADE, blank=True, null=True
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )
    seller = models.ForeignKey(
        "Reseller", on_delete=models.SET_NULL, blank=True, null=True
    )

    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    class Meta:
        indexes = documentation_year_week_indexes()


class AdditionalTheoreticalPurchase(
    JasminModel,
    DocumentationMixin,
    RequiresHarvestStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    seller = models.ForeignKey(
        "Reseller", on_delete=models.SET_NULL, blank=True, null=True
    )
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "day_number",
                    "share_article",
                    "unit",
                    "size",
                    "seller",
                ],
                condition=models.Q(day_number__isnull=False, seller__isnull=False),
                name="addtheoreticalpurchase_unique_full",
            ),
        ]
        indexes = documentation_year_week_indexes()


class Purchase(JasminModel, DocumentationMixin, CreatedMixin, ArchivableMixin):
    seller = models.ForeignKey(
        "Reseller", on_delete=models.SET_NULL, blank=True, null=True
    )
    price_per_unit = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    amount_per_pu = models.DecimalField(
        max_digits=7, decimal_places=3, blank=True, null=True
    )
    # Reuses ShareArticle's organic-status trichotomy. ``organic`` /
    # ``in_conversion`` require the seller to hold an OrganicCertificate valid at
    # this purchase's delivery week — enforced in PurchaseSerializer.validate.
    organic_status = models.CharField(
        max_length=20,
        choices=ShareArticle.OrganicStatus.choices,
        default=ShareArticle.OrganicStatus.CONVENTIONAL,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "day_number",
                    "share_article",
                    "unit",
                    "size",
                    "seller",
                ],
                condition=models.Q(day_number__isnull=False, seller__isnull=False),
                name="purchase_unique_year_week_day_article_unit_size_seller",
            ),
            # No-seller upsert key. bulk_set_purchase_as_expected and
            # _ensure_purchase_placeholder both upsert on this tuple while
            # leaving ``seller`` NULL, but the seller-scoped constraint above
            # only fires when seller IS NOT NULL — so concurrent upserts could
            # double-insert (MultipleObjectsReturned + double-counted stock).
            # Both now stamp ``day_number=PURCHASE_DAY``; ``nulls_distinct=False``
            # (PG15+, Django 5.0+) is kept so any legacy NULL-day rows (never
            # back-filled) still de-dupe under this constraint.
            models.UniqueConstraint(
                fields=[
                    "year",
                    "delivery_week",
                    "day_number",
                    "share_article",
                    "unit",
                    "size",
                    "storage",
                ],
                condition=models.Q(seller__isnull=True),
                name="purchase_unique_no_seller_year_week_day_article_unit_size_storage",
                nulls_distinct=False,
            ),
        ]
        indexes = documentation_year_week_indexes()


class TheoreticalWashAmount(
    JasminModel,
    DocumentationMixin,
    RequiresShortTermStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    share_content = models.ForeignKey(
        "ShareContent", on_delete=models.CASCADE, blank=True, null=True
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )

    class Meta:
        indexes = documentation_year_week_indexes()


class AdditionalTheoreticalWashAmount(
    JasminModel,
    DocumentationMixin,
    RequiresShortTermStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    class Meta:
        constraints = [
            documentation_daily_unique("addtheoreticalwashamount_unique_full"),
        ]
        indexes = documentation_year_week_indexes()


class WashAmount(JasminModel, DocumentationMixin, CreatedMixin, ArchivableMixin):
    class Meta:
        constraints = [
            documentation_daily_unique(
                "washamount_unique_year_week_day_article_unit_size"
            ),
        ]
        indexes = documentation_year_week_indexes()


class TheoreticalCleanAmount(
    JasminModel,
    DocumentationMixin,
    RequiresShortTermStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    share_content = models.ForeignKey(
        "ShareContent", on_delete=models.CASCADE, blank=True, null=True
    )
    order_content = models.ForeignKey(
        "OrderContent", on_delete=models.CASCADE, blank=True, null=True
    )

    class Meta:
        indexes = documentation_year_week_indexes()


class AdditionalTheoreticalCleanAmount(
    JasminModel,
    DocumentationMixin,
    RequiresShortTermStorageMixin,
    CreatedMixin,
    ArchivableMixin,
):
    class Meta:
        constraints = [
            documentation_daily_unique("addtheoreticalcleanamount_unique_full"),
        ]
        indexes = documentation_year_week_indexes()


class CleanAmount(JasminModel, DocumentationMixin, CreatedMixin, ArchivableMixin):
    class Meta:
        constraints = [
            documentation_daily_unique(
                "cleanamount_unique_year_week_day_article_unit_size"
            ),
        ]
        indexes = documentation_year_week_indexes()
