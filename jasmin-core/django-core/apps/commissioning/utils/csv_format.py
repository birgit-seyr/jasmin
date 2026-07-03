"""Tenant-aware CSV dialect (delimiter, decimal separator, date format).

Selected by ``Tenant.csv_format``:

* ``"de"`` (default) — Excel-DE: ``;``, ``,``, ``dd.mm.yyyy``
* ``"en"``           — Excel-US/UK: ``,``, ``.``, ``yyyy-mm-dd``

Headers are intentionally NOT translated here — keep the German labels the
endpoints already use; this helper only affects machine-readable formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import connection


@dataclass(frozen=True)
class CsvDialect:
    delimiter: str
    decimal_separator: str
    date_format: str  # strftime format

    def format(self, value: Any) -> Any:
        """Format a value for CSV output (date/decimal localization)."""
        if value is None or value == "":
            return ""
        if isinstance(value, (date, datetime)):
            return value.strftime(self.date_format)
        if isinstance(value, Decimal):
            text = format(value, "f")
            return (
                text.replace(".", self.decimal_separator)
                if self.decimal_separator != "."
                else text
            )
        if isinstance(value, float):
            text = repr(value)
            return (
                text.replace(".", self.decimal_separator)
                if self.decimal_separator != "."
                else text
            )
        return value


_PRESETS: dict[str, CsvDialect] = {
    "de": CsvDialect(delimiter=";", decimal_separator=",", date_format="%d.%m.%Y"),
    "en": CsvDialect(delimiter=",", decimal_separator=".", date_format="%Y-%m-%d"),
}


def get_csv_dialect(tenant: Any | None = None) -> CsvDialect:
    if tenant is None:
        tenant = getattr(connection, "tenant", None)
    preset_key = str(getattr(tenant, "csv_format", None) or "de").lower()
    return _PRESETS.get(preset_key, _PRESETS["de"])
