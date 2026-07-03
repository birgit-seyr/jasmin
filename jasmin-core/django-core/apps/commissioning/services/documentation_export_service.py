"""CSV export for documentation models (harvest, purchase, ...).

Single entry point that streams a localized CSV (``StreamingHttpResponse``)
for a given date range. Shared between :class:`HarvestViewSet` and
:class:`PurchaseViewSet`.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date as dt_date
from decimal import Decimal
from typing import Any, Literal

from django.db.models import QuerySet
from django.http import StreamingHttpResponse

from apps.shared.csv_safety import CsvEchoBuffer, escape_csv_row

from ..errors import InvalidExportDates  # re-exported for back-compat
from ..models import Harvest, Purchase
from ..utils.csv_format import get_csv_dialect
from ..utils.iso_week_utils import week_day_to_date

ExportModel = Literal["harvest", "purchase"]

__all__ = ["DocumentationExportService", "InvalidExportDates"]


class DocumentationExportService:
    """Stream CSV (``StreamingHttpResponse``) exports for documentation models."""

    _CONFIG: dict[str, dict[str, Any]] = {
        "harvest": {
            "model": Harvest,
            "select_related": ("share_article", "storage"),
            "filename_prefix": "ernte",
            "headers": [
                "Datum",
                "KW",
                "Tag",
                "Artikel",
                "Einheit",
                "Größe",
                "Menge",
                "Lager",
                "Notiz",
            ],
        },
        "purchase": {
            "model": Purchase,
            "select_related": ("share_article", "storage", "seller"),
            "filename_prefix": "zukauf",
            "headers": [
                "Datum",
                "KW",
                "Tag",
                "Artikel",
                "Einheit",
                "Größe",
                "Menge",
                "Lieferant",
                "Preis/Einheit",
                "Lager",
                "Notiz",
            ],
        },
    }

    @classmethod
    def export_csv(
        cls,
        *,
        model: ExportModel,
        date_from: str | None,
        date_to: str | None,
        summed: bool,
    ) -> StreamingHttpResponse:
        if not date_from or not date_to:
            raise InvalidExportDates("date_from and date_to are required")

        try:
            start = dt_date.fromisoformat(date_from)
            end = dt_date.fromisoformat(date_to)
        except ValueError as exc:
            raise InvalidExportDates("Invalid date format. Use YYYY-MM-DD.") from exc

        if model not in cls._CONFIG:
            raise InvalidExportDates(f"Unsupported export model: {model!r}")

        config = cls._CONFIG[model]
        queryset = cls._get_queryset(config, start, end)
        # Materialized list (relations are select_related on the queryset), so
        # the streaming generator below touches no DB after the view returns.
        filtered = cls._filter_by_date_range(queryset, start, end)

        dialect = get_csv_dialect()
        writer = csv.writer(CsvEchoBuffer(), delimiter=dialect.delimiter)

        def rows() -> Iterator[str]:
            yield "\ufeff"  # BOM first so Excel opens UTF-8 correctly.
            if summed:
                yield from cls._iter_summed_rows(writer, filtered, dialect)
            else:
                yield writer.writerow(escape_csv_row(config["headers"]))
                for instance, instance_date in filtered:
                    yield writer.writerow(
                        escape_csv_row(
                            cls._format_detail_row(
                                model, instance, instance_date, dialect
                            )
                        )
                    )

        filename = f"{config['filename_prefix']}_{date_from}_{date_to}"
        if summed:
            filename += "_summiert"

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        return response

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _get_queryset(config: dict[str, Any], start: dt_date, end: dt_date) -> QuerySet:
        return (
            config["model"]
            .objects.select_related(*config["select_related"])
            .filter(
                year__gte=start.isocalendar()[0],
                year__lte=end.isocalendar()[0],
            )
            .order_by("year", "delivery_week", "day_number", "share_article__name")
        )

    @staticmethod
    def _filter_by_date_range(
        queryset: QuerySet, start: dt_date, end: dt_date
    ) -> list[tuple[Any, dt_date]]:
        result: list[tuple[Any, dt_date]] = []
        for instance in queryset:
            try:
                instance_date = week_day_to_date(
                    instance.year,
                    instance.delivery_week,
                    instance.day_number if instance.day_number is not None else 0,
                )
            except (ValueError, TypeError):
                continue
            if start <= instance_date <= end:
                result.append((instance, instance_date))
        return result

    @staticmethod
    def _iter_summed_rows(
        writer: Any, filtered: list[tuple[Any, dt_date]], dialect: Any
    ) -> Iterator[str]:
        sums: dict[tuple, dict] = {}
        for instance, _ in filtered:
            key = (
                instance.share_article.name if instance.share_article else "",
                instance.unit or "",
                instance.size or "",
            )
            if key not in sums:
                sums[key] = {
                    "share_article": key[0],
                    "unit": key[1],
                    "size": key[2],
                    "amount": Decimal("0"),
                }
            if instance.amount is not None:
                sums[key]["amount"] += Decimal(str(instance.amount))

        yield writer.writerow(escape_csv_row(["Artikel", "Einheit", "Größe", "Menge"]))
        for row in sorted(sums.values(), key=lambda r: r["share_article"]):
            yield writer.writerow(
                escape_csv_row(
                    [
                        row["share_article"],
                        row["unit"],
                        row["size"],
                        dialect.format(row["amount"]),
                    ]
                )
            )

    @staticmethod
    def _format_detail_row(
        model: str, instance: Any, instance_date: dt_date, dialect: Any
    ) -> list[Any]:
        amount_cell = (
            dialect.format(Decimal(str(instance.amount)))
            if instance.amount is not None
            else ""
        )
        common_prefix = [
            dialect.format(instance_date),
            instance.delivery_week,
            (
                instance.get_day_number_display()
                if instance.day_number is not None
                else ""
            ),
            instance.share_article.name if instance.share_article else "",
            instance.unit or "",
            instance.size or "",
            amount_cell,
        ]
        if model == "purchase":
            return common_prefix + [
                instance.seller.name if instance.seller else "",
                (
                    dialect.format(Decimal(str(instance.price_per_unit)))
                    if instance.price_per_unit is not None
                    else ""
                ),
                instance.storage.name if instance.storage else "",
                instance.note or "",
            ]
        # harvest
        return common_prefix + [
            instance.storage.name if instance.storage else "",
            instance.note or "",
        ]
