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

from django.db import connection
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

    # German is the primary locale and the default; the English labels /
    # filename tokens are served when the tenant ``csv_format`` selects the
    # ``en`` CSV dialect, mirroring the de/en switch :mod:`csv_format` already
    # applies to the machine formatting. fr/it are deferred and degrade to de.
    _SUPPORTED_LANGUAGES: tuple[str, ...] = ("de", "en")

    _CONFIG: dict[str, dict[str, Any]] = {
        "harvest": {
            "model": Harvest,
            "select_related": ("share_article", "storage"),
            "labels": {
                "de": {
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
                "en": {
                    "filename_prefix": "harvest",
                    "headers": [
                        "Date",
                        "CW",
                        "Day",
                        "Article",
                        "Unit",
                        "Size",
                        "Amount",
                        "Storage",
                        "Note",
                    ],
                },
            },
        },
        "purchase": {
            "model": Purchase,
            "select_related": ("share_article", "storage", "seller", "seller__contact"),
            "labels": {
                "de": {
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
                        "Bio-Status",
                        "Preis/Einheit",
                        "Lager",
                        "Notiz",
                    ],
                },
                "en": {
                    "filename_prefix": "purchase",
                    "headers": [
                        "Date",
                        "CW",
                        "Day",
                        "Article",
                        "Unit",
                        "Size",
                        "Amount",
                        "Seller",
                        "Organic status",
                        "Price/Unit",
                        "Storage",
                        "Note",
                    ],
                },
            },
        },
    }

    # Summed-sheet columns (article / unit / size / amount) + the filename
    # suffix, localized alongside the detail headers above.
    _SUMMED_LABELS: dict[str, dict[str, Any]] = {
        "de": {
            "headers": ["Artikel", "Einheit", "Größe", "Menge"],
            "suffix": "summiert",
        },
        "en": {
            "headers": ["Article", "Unit", "Size", "Amount"],
            "suffix": "summed",
        },
    }

    # Human labels for the unit / size CODES and the ISO weekday, per CSV
    # language — mirrors the frontend ``getUnitLabel`` / ``getVegetableSizeLabel``
    # (``commissioning.units.*`` / ``commissioning.small|medium|large``) so the
    # export reads the same as the on-screen grid. Unknown codes fall back to
    # the raw value.
    _UNIT_LABELS: dict[str, dict[str, str]] = {
        "de": {"KG": "kg", "PCS": "Stk", "BUNCH": "Bund", "L": "l", "G": "g"},
        "en": {"KG": "kg", "PCS": "pcs", "BUNCH": "bunch", "L": "l", "G": "g"},
    }
    _SIZE_LABELS: dict[str, dict[str, str]] = {
        "de": {"S": "klein", "M": "mittel", "L": "groß"},
        "en": {"S": "small", "M": "medium", "L": "large"},
    }
    # Purchase-only organic status → localized label (mirrors the frontend
    # OrganicStatus choices: Bio / Umstellung / Konventionell).
    _ORGANIC_STATUS_LABELS: dict[str, dict[str, str]] = {
        "de": {
            "organic": "Bio",
            "in_conversion": "Umstellung",
            "conventional": "Konventionell",
        },
        "en": {
            "organic": "Organic",
            "in_conversion": "In conversion",
            "conventional": "Conventional",
        },
    }
    _DAY_LABELS: dict[str, list[str]] = {
        "de": [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ],
        "en": [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ],
    }

    @classmethod
    def _unit_label(cls, unit: str | None, language: str) -> str:
        return cls._UNIT_LABELS.get(language, {}).get(unit, unit) if unit else ""

    @classmethod
    def _size_label(cls, size: str | None, language: str) -> str:
        return cls._SIZE_LABELS.get(language, {}).get(size, size) if size else ""

    @classmethod
    def _organic_status_label(cls, status: str | None, language: str) -> str:
        if not status:
            return ""
        return cls._ORGANIC_STATUS_LABELS.get(language, {}).get(status, status)

    @classmethod
    def _day_label(cls, day_number: int | None, language: str) -> str:
        if day_number is None:
            return ""
        days = cls._DAY_LABELS.get(language, cls._DAY_LABELS["de"])
        return days[day_number] if 0 <= day_number < len(days) else ""

    @classmethod
    def _resolve_csv_language(cls, tenant: Any | None = None) -> str:
        """Pick the CSV label language from the tenant ``csv_format`` — the same
        source :func:`get_csv_dialect` reads for its preset, so the headers and
        the machine formatting never diverge. Unknown values degrade to German."""
        if tenant is None:
            tenant = getattr(connection, "tenant", None)
        key = str(getattr(tenant, "csv_format", None) or "de").lower()
        return key if key in cls._SUPPORTED_LANGUAGES else "de"

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
        language = cls._resolve_csv_language()
        labels = config["labels"][language]
        queryset = cls._get_queryset(config, start, end)
        # Materialized list (relations are select_related on the queryset), so
        # the streaming generator below touches no DB after the view returns.
        filtered = cls._filter_by_date_range(queryset, start, end, model)

        dialect = get_csv_dialect()
        writer = csv.writer(CsvEchoBuffer(), delimiter=dialect.delimiter)

        def rows() -> Iterator[str]:
            yield "\ufeff"  # BOM first so Excel opens UTF-8 correctly.
            if summed:
                yield from cls._iter_summed_rows(writer, filtered, dialect, language)
            else:
                yield writer.writerow(escape_csv_row(labels["headers"]))
                for instance, instance_date in filtered:
                    yield writer.writerow(
                        escape_csv_row(
                            cls._format_detail_row(
                                model, instance, instance_date, dialect, language
                            )
                        )
                    )

        filename = f"{labels['filename_prefix']}_{date_from}_{date_to}"
        if summed:
            filename += f"_{cls._SUMMED_LABELS[language]['suffix']}"

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
        queryset: QuerySet, start: dt_date, end: dt_date, model: str
    ) -> list[tuple[Any, dt_date]]:
        result: list[tuple[Any, dt_date]] = []
        for instance in queryset:
            try:
                if model == "purchase":
                    # Purchases are week-scoped (no delivery day; day_number is
                    # NULL or the PURCHASE_DAY sentinel). Keep them when the
                    # delivery WEEK overlaps the range — anchoring on a single
                    # day would drop them whenever the range doesn't contain that
                    # exact day (the empty-export bug). Stamp the week's Monday
                    # as the Date cell.
                    week_start = week_day_to_date(
                        instance.year, instance.delivery_week, 0
                    )
                    week_end = week_day_to_date(
                        instance.year, instance.delivery_week, 6
                    )
                    if week_start <= end and week_end >= start:
                        result.append((instance, week_start))
                else:
                    instance_date = week_day_to_date(
                        instance.year,
                        instance.delivery_week,
                        instance.day_number if instance.day_number is not None else 0,
                    )
                    if start <= instance_date <= end:
                        result.append((instance, instance_date))
            except (ValueError, TypeError):
                continue
        return result

    @classmethod
    def _iter_summed_rows(
        cls,
        writer: Any,
        filtered: list[tuple[Any, dt_date]],
        dialect: Any,
        language: str,
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

        yield writer.writerow(escape_csv_row(cls._SUMMED_LABELS[language]["headers"]))
        for row in sorted(sums.values(), key=lambda r: r["share_article"]):
            yield writer.writerow(
                escape_csv_row(
                    [
                        row["share_article"],
                        cls._unit_label(row["unit"], language),
                        cls._size_label(row["size"], language),
                        dialect.format(row["amount"]),
                    ]
                )
            )

    @classmethod
    def _format_detail_row(
        cls,
        model: str,
        instance: Any,
        instance_date: dt_date,
        dialect: Any,
        language: str,
    ) -> list[Any]:
        amount_cell = (
            dialect.format(Decimal(str(instance.amount)))
            if instance.amount is not None
            else ""
        )
        common_prefix = [
            dialect.format(instance_date),
            instance.delivery_week,
            cls._day_label(instance.day_number, language),
            instance.share_article.name if instance.share_article else "",
            cls._unit_label(instance.unit, language),
            cls._size_label(instance.size, language),
            amount_cell,
        ]
        if model == "purchase":
            return common_prefix + [
                # Reseller has no ``name`` of its own — the display name lives on
                # the linked ContactEntity (mirrors the summary service).
                instance.seller.contact.name if instance.seller else "",
                cls._organic_status_label(instance.organic_status, language),
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
