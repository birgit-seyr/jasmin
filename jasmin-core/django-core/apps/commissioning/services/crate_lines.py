"""Crate lines: the crate rows of a document that print as one line.

The crate summaries fold every crate row of a delivery note, an invoice or an
order that shares a crate type, price, rabatt and tax rate into one line, and
the office edits that line as a whole. A line is named
``{crate type id}_{pk of its member row with the lowest pk}``. Naming a line by
one of its rows keeps the name through an edit of the line's price or rabatt,
and the name never passes to a line without that row, which the editing tables
rely on: they key their rows by this id.

An id without ``_`` is a bare crate type id and names every line of that type,
the way a page that still lists one line per crate type addresses them. Jasmin
ids never contain ``_``, so the two forms can't be confused. The current
crate tables never send one; each write that does is logged
(``crate_line.bare_type_id``), so the form can be refused once the logs have
shown none for a while.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, NamedTuple

from core.errors import ConflictError

from ..utils.composite_id_utils import parse_composite_pk

logger = logging.getLogger(__name__)


class CrateLineId(NamedTuple):
    """A parsed crate line id. ``row_pk`` is None for a bare crate type id."""

    crate_type_id: str
    row_pk: str | None


def crate_line_key(row: Any) -> tuple:
    """What a crate line groups its rows by: crate type, price, rabatt (a NULL
    rabatt counts as 0) and tax rate."""
    return (row.crate_type_id, row.price_per_unit, row.rabatt or 0, row.tax_rate)


def crate_line_id(rows: Iterable[Any]) -> str:
    """The id of the line made of ``rows``, which share one :func:`crate_line_key`.

    The lowest pk is picked in Python: Postgres may order these varchar pks
    differently under its collation, and the id has to come out the same on
    every read.
    """
    members = list(rows)
    return f"{members[0].crate_type_id}_{min(str(row.pk) for row in members)}"


def _id_part(part: str) -> str:
    if not part or "_" in part:
        raise ValueError(part)
    return part


def parse_crate_line_id(raw: str) -> CrateLineId:
    """Parse a crate line id, or a bare crate type id. A malformed one raises
    ``CompositeIdInvalid`` (400, ``crate_line.invalid_id``)."""
    if raw and "_" not in raw:
        logger.info("crate_line.bare_type_id: a crate write named crate type %s", raw)
        return CrateLineId(crate_type_id=raw, row_pk=None)
    parts = parse_composite_pk(
        raw,
        fields=[("crate_type", _id_part), ("row", _id_part)],
        code="crate_line.invalid_id",
    )
    return CrateLineId(crate_type_id=parts["crate_type"], row_pk=parts["row"])


def resolve_crate_line(type_rows: Iterable[Any], row_pk: str) -> list[Any] | None:
    """The rows of the line that holds the row ``row_pk``, taken from
    ``type_rows`` (the rows of one crate type on one document), or None when
    ``type_rows`` has no such row."""
    rows = list(type_rows)
    named = next((row for row in rows if str(row.pk) == row_pk), None)
    if named is None:
        return None
    key = crate_line_key(named)
    return [row for row in rows if crate_line_key(row) == key]


def crate_line_rows(type_rows: Iterable[Any], line_id: CrateLineId) -> list[Any]:
    """The rows a write to ``line_id`` covers among ``type_rows``, the rows of
    one crate type on one document: the named row's line, or every row for a
    bare crate type id.

    A named row that is gone covers nothing while no rows of the type are
    left. While other lines of the type remain it raises ``ConflictError``
    (409, ``crate_line.changed``): another write removed or rebuilt the row,
    the line may live on under another id, and guessing which line was meant
    could change one the office never saw.
    """
    rows = list(type_rows)
    if line_id.row_pk is None:
        return rows
    line = resolve_crate_line(rows, line_id.row_pk)
    if line is None and rows:
        raise ConflictError(
            f"Crate line {line_id.crate_type_id}_{line_id.row_pk} no longer "
            "exists; reload the crate lines.",
            code="crate_line.changed",
        )
    return line or []
