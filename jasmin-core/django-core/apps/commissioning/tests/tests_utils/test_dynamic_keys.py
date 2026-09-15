"""Tests for apps.commissioning.utils.dynamic_keys."""

from __future__ import annotations

from apps.commissioning.utils.dynamic_keys import extract_amounts_from_keys


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
