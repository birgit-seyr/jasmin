"""Crate line ids: how a line is named, parsed and found among its type's rows."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.commissioning.errors import CompositeIdInvalid
from apps.commissioning.services.crate_lines import (
    CrateLineId,
    crate_line_id,
    crate_line_key,
    crate_line_rows,
    parse_crate_line_id,
    resolve_crate_line,
)
from apps.commissioning.services.crate_summary import summarize_crate_items
from core.errors import ConflictError


def _row(pk, price="2.50", rabatt=None, tax="19.00", amount=1, **extra):
    fields = {"note": None, **extra}
    return SimpleNamespace(
        pk=pk,
        crate_type_id="crate1",
        crate_type=SimpleNamespace(name="Euro crate"),
        price_per_unit=Decimal(price),
        rabatt=rabatt,
        tax_rate=Decimal(tax),
        amount=amount,
        line_netto=Decimal(price) * amount,
        **fields,
    )


class TestCrateLineNames:
    def test_a_line_is_named_by_its_lowest_row_pk(self):
        rows = [_row("rowB"), _row("rowA"), _row("rowC")]

        assert crate_line_id(rows) == "crate1_rowA"

    def test_a_null_rabatt_and_a_zero_rabatt_are_one_line(self):
        assert crate_line_key(_row("a", rabatt=None)) == crate_line_key(
            _row("b", rabatt=0)
        )
        assert crate_line_key(_row("a", rabatt=10)) != crate_line_key(
            _row("b", rabatt=0)
        )

    def test_summary_rows_carry_their_lines_ids(self):
        rows = [
            _row("rowB", price="2.00", amount=5),
            _row("rowA", price="2.50", amount=3),
            _row("rowC", price="2.00", amount=2),
        ]

        summary = summarize_crate_items(rows)

        assert [(line["id"], line["amount"]) for line in summary] == [
            ("crate1_rowB", 7),
            ("crate1_rowA", 3),
        ]
        assert {line["crate_type"] for line in summary} == {"crate1"}


class TestCrateLineNotes:
    """A summary row carries its line's note: the distinct notes of the line's
    rows in row order, so no row's note is hidden behind another's."""

    @pytest.mark.parametrize(
        ("notes", "expected"),
        [
            ((None, None), None),
            (("", None), None),
            (("Pallet", "Pallet"), "Pallet"),
            ((None, "Pallet"), "Pallet"),
            (("Bring back", "Pallet", "Bring back"), "Bring back; Pallet"),
        ],
    )
    def test_a_line_shows_the_distinct_notes_of_its_rows(self, notes, expected):
        rows = [_row(f"row{index}", note=note) for index, note in enumerate(notes)]

        (line,) = summarize_crate_items(rows)

        assert line["note"] == expected

    def test_the_notes_follow_the_rows_pk_order(self):
        rows = [_row("rowB", note="Second"), _row("rowA", note="First")]

        (line,) = summarize_crate_items(rows)

        assert line["note"] == "First; Second"

    def test_each_line_keeps_its_own_note(self):
        rows = [
            _row("rowA", price="2.00", note="Old price"),
            _row("rowB", price="2.50", note="New price"),
        ]

        summary = summarize_crate_items(rows)

        assert {line["price_per_unit"]: line["note"] for line in summary} == {
            "2.00": "Old price",
            "2.50": "New price",
        }


class TestParseCrateLineId:
    def test_a_line_id_names_a_crate_type_and_a_row(self):
        assert parse_crate_line_id("crate1_rowA") == CrateLineId("crate1", "rowA")

    def test_a_bare_crate_type_id_names_every_line_of_the_type(self):
        assert parse_crate_line_id("crate1") == CrateLineId("crate1", None)

    @pytest.mark.parametrize("raw", ["", "crate1_", "_rowA", "crate1_rowA_x"])
    def test_a_malformed_id_is_refused(self, raw):
        with pytest.raises(CompositeIdInvalid) as error:
            parse_crate_line_id(raw)

        assert error.value.code == "crate_line.invalid_id"


class TestFindingALine:
    ROWS = [
        _row("rowA", price="2.00"),
        _row("rowB", price="2.50"),
        _row("rowC", price="2.50"),
    ]

    def test_a_row_resolves_to_every_row_of_its_line(self):
        line = resolve_crate_line(self.ROWS, "rowC")

        assert [row.pk for row in line or []] == ["rowB", "rowC"]

    def test_a_row_outside_the_rows_resolves_to_nothing(self):
        assert resolve_crate_line(self.ROWS, "rowZ") is None

    def test_a_bare_crate_type_id_covers_every_row(self):
        rows = crate_line_rows(self.ROWS, CrateLineId("crate1", None))

        assert [row.pk for row in rows] == ["rowA", "rowB", "rowC"]

    def test_a_gone_row_covers_nothing_once_the_type_has_no_rows(self):
        assert crate_line_rows([], CrateLineId("crate1", "rowZ")) == []

    def test_a_gone_row_is_refused_while_other_lines_remain(self):
        with pytest.raises(ConflictError) as error:
            crate_line_rows(self.ROWS, CrateLineId("crate1", "rowZ"))

        assert error.value.code == "crate_line.changed"
        assert error.value.http_status == 409
