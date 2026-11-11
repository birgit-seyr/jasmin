from django.core.validators import MinValueValidator
from django.db import models

from .base import JasminModel
from .choices import DayNumberOptions
from .fields import delivery_week_field, size_vegetable_field, unit_field


# also a market on the farm itself is included here:
class Market(JasminModel):
    """Reserved for a future markets feature — intentionally unwired.

    Model (+ factory) only: there is no serializer, viewset, service or read
    path exposing this yet. Kept on purpose until the feature is built or
    deliberately dropped — don't assume it's live.
    """

    is_active = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=300)
    day_number = models.PositiveSmallIntegerField(choices=DayNumberOptions.choices)

    def __str__(self) -> str:
        return self.name


class MarketProductGroup(JasminModel):
    """A group of PLUs (apples, root vegetables, bread …) that the market price
    lists are sorted by. ``number`` is the one the market scales know the
    group by."""

    is_active = models.BooleanField(default=True, db_index=True)
    number = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)

    def __str__(self) -> str:
        return f"{self.number} {self.name}"


class MarketArticle(JasminModel):
    """A PLU: the number the market scales and registers sell an item under,
    in one unit, size and sort. An item sold by the kg and by the bunch, or in
    two sorts, has a PLU for each.

    A PLU of the farm's own produce names its share article, so its sales can
    be counted toward that article; a PLU of bought-in market goods names
    none."""

    is_active = models.BooleanField(default=True, db_index=True)
    plu_number = models.PositiveIntegerField(unique=True)
    share_article = models.ForeignKey(
        "ShareArticle",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="market_articles",
    )
    product_group = models.ForeignKey(
        "MarketProductGroup",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="market_articles",
    )
    scale_tax_code = models.ForeignKey(
        "ScaleTaxCode", on_delete=models.PROTECT, related_name="market_articles"
    )
    unit = unit_field()
    size = size_vegetable_field()
    sort = models.CharField(max_length=200, blank=True, null=True)
    # The name the scale prints and the price list shows.
    name = models.CharField(max_length=100)
    allows_price_override = models.BooleanField(default=True)
    allows_discount_price = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.plu_number} {self.name}"


class MarketPrice(JasminModel):
    """A PLU's price at the markets in one ISO week.

    The price is gross: the scales and the price lists show gross prices, and
    a net price in cents can't hold every gross price (at 7 % VAT, 0.53 € gross
    is 0.50 € net, which comes back as 0.54 €)."""

    year = models.PositiveSmallIntegerField(db_index=True)
    delivery_week = delivery_week_field(db_index=True)
    market_article = models.ForeignKey(
        "MarketArticle", on_delete=models.PROTECT, related_name="prices"
    )
    gross_price = models.DecimalField(
        max_digits=7, decimal_places=2, validators=[MinValueValidator(0)]
    )
    # Changes with the supplier from week to week ("DE", "ES", "own farm").
    origin = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["market_article", "year", "delivery_week"],
                name="marketprice_one_per_week",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.market_article} {self.delivery_week}/{self.year}"


class ScaleTaxCode(JasminModel):
    """The number the market scales know a VAT rate by: each scale keeps its
    own table of rates, and its import names the rate by that number."""

    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, unique=True)
    code = models.PositiveSmallIntegerField(unique=True)

    def __str__(self) -> str:
        return f"{self.tax_rate} % → {self.code}"
