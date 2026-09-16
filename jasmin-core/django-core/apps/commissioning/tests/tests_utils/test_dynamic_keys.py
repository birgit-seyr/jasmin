"""Tests for apps.commissioning.utils.dynamic_keys."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.commissioning.errors import InvalidAmount
from apps.commissioning.utils.dynamic_keys import (
    extract_amounts_from_keys,
    parse_amount_cell,
)


# ---------------------------------------------------------------------------
# parse_amount_cell
# ---------------------------------------------------------------------------
class TestParseAmountCell:
    """The cells land in ``numeric(5,3)`` columns through ``bulk_create``, so
    this is the only place a value the column cannot hold gets named."""

    def test_returns_the_value_rounded_to_the_column_scale(self):
        assert parse_amount_cell("1.23456", field="cell") == Decimal("1.235")

    def test_accepts_the_largest_value_the_column_holds(self):
        assert parse_amount_cell("99.999", field="cell") == Decimal("99.999")

    def test_rejects_a_value_that_rounds_up_past_the_column(self):
        # Postgres rounds to the scale BEFORE checking the precision, so
        # 99.9995 becomes 100.000 and overflows numeric(5,3) — the raw value
        # being under 100 is not enough.
        with pytest.raises(InvalidAmount) as exc_info:
            parse_amount_cell("99.9995", field="day_1_variation_2")
        assert exc_info.value.field == "day_1_variation_2"

    def test_rejects_a_value_over_the_column(self):
        with pytest.raises(InvalidAmount):
            parse_amount_cell("100", field="cell")

    def test_rejects_a_magnitude_the_decimal_context_cannot_quantize(self):
        with pytest.raises(InvalidAmount):
            parse_amount_cell("1e30", field="cell")

    @pytest.mark.parametrize("bad", ["abc", None, "NaN", "Infinity"])
    def test_rejects_non_numbers(self, bad):
        with pytest.raises(InvalidAmount):
            parse_amount_cell(bad, field="cell")


# ---------------------------------------------------------------------------
# extract_amounts_from_keys
# ---------------------------------------------------------------------------
class TestExtractAmountsFromKeys:
    def test_basic_extraction(self):
        data = {"amount_ABC123": "10.5", "amount_DEF456": "20.0"}
        result = extract_amounts_from_keys(data)
        assert result == {"ABC123": "10.5", "DEF456": "20.0"}

    def test_custom_prefix(self):
        data = {"qty_item1": 5, "qty_item2": 10, "other_key": 99}
        result = extract_amounts_from_keys(data, prefix="qty_")
        assert result == {"item1": 5, "item2": 10}

    def test_ignores_non_matching_keys(self):
        data = {"amount_ABC": "1", "name": "test", "total": 42}
        result = extract_amounts_from_keys(data)
        assert result == {"ABC": "1"}

    def test_ignores_bare_prefix(self):
        data = {"amount_": "nope", "amount_X": "ok"}
        result = extract_amounts_from_keys(data)
        # "amount_" has nothing after prefix so len(key) == prefix_len → skipped
        assert result == {"X": "ok"}

    def test_empty_dict(self):
        assert extract_amounts_from_keys({}) == {}

    def test_nanoid_style_ids(self):
        data = {"amount_V9uWuNNgV0h6": "10.5", "amount_UJVEq_SRG4RY": "20.0"}
        result = extract_amounts_from_keys(data)
        # Note: "UJVEq_SRG4RY" contains underscore — prefix match is greedy on first prefix only
        assert "V9uWuNNgV0h6" in result
        assert "UJVEq_SRG4RY" in result
