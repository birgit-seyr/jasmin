from __future__ import annotations

from django.db import models

from .base import JasminModel
from .fields import size_vegetable_field, unit_field


class StockSnapshot(JasminModel):
    """
    Materialized snapshot of the running stock balance at a point in time.

    To compute the current balance for a (share_article, unit, size, storage)
    group: find the most recent snapshot, take its ``balance``, then add
    ``SUM(amount)`` of all MovementShareArticle rows with ``date >``
    the snapshot's ``snapshot_date``.

    Snapshots can be created on every INVENTORY count or via a periodic task.
    """

    snapshot_date = models.DateTimeField(
        db_index=True,
        help_text="Point in time this snapshot captures the balance for.",
    )
    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    unit = unit_field()
    size = size_vegetable_field()
    storage = models.ForeignKey(
        "Storage", on_delete=models.PROTECT, blank=True, null=True
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Running balance (sum of all movements) at snapshot_date.",
    )

    class Meta:
        indexes = [
            models.Index(fields=["snapshot_date"]),
            # The composite index below covers any prefix lookup on
            # (share_article, unit, size, storage), so a separate 4-field
            # index would be redundant.
            models.Index(
                fields=[
                    "share_article",
                    "unit",
                    "size",
                    "storage",
                    "-snapshot_date",
                ]
            ),
        ]

    def __str__(self) -> str:
        label = self.share_article.name if self.share_article_id else "?"
        return f"Snapshot {label} {self.balance} @ {self.snapshot_date:%Y-%m-%d}"


class CurrentStockBalance(JasminModel):
    """Maintained running balance per (share_article, unit, size, storage) entity.

    The DocumentationCurrentStock page reads from this table directly instead
    of summing MovementShareArticle rows on every request. Updated
    transactionally by ``CurrentBalanceService`` whenever movements change.
    For point-in-time historical queries, fall back to ``StockSnapshot`` +
    movements — this table is "now" only.
    """

    share_article = models.ForeignKey("ShareArticle", on_delete=models.PROTECT)
    unit = unit_field()
    size = size_vegetable_field()
    storage = models.ForeignKey(
        "Storage", on_delete=models.PROTECT, blank=True, null=True
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Current running balance (sum of all movements to date).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # nulls_distinct=False (PG15+, Django 5.0+) treats two NULL storages
            # as equal — without it, multiple rows with storage=NULL for the
            # same article/unit/size would all be allowed.
            models.UniqueConstraint(
                fields=["share_article", "unit", "size", "storage"],
                name="current_stock_balance_unique_entity",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=["storage"]),
        ]

    def __str__(self) -> str:
        label = self.share_article.name if self.share_article_id else "?"
        return f"CurrentBalance {label} {self.balance} ({self.unit}/{self.size})"
