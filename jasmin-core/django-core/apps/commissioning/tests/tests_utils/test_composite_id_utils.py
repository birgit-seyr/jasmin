"""Tests for apps.commissioning.utils.composite_id_utils."""

from __future__ import annotations

import pytest

from apps.commissioning.errors import CompositeIdInvalid
from apps.commissioning.utils.composite_id_utils import (
    build_composite_id,
    parse_composite_id,
)


# ---------------------------------------------------------------------------
# parse_composite_id  (pure function — no DB needed)
# ---------------------------------------------------------------------------
class TestParseCompositeId:
    def test_valid_id(self):
        result = parse_composite_id("abc123_KG_M_store1_2024_10_3")
        assert result == {
            "share_article_id": "abc123",
            "unit": "KG",
            "size": "M",
            "storage_id": "store1",
            "year": 2024,
            "delivery_week": 10,
            "day_number": 3,
        }

    def test_none_values_parsed(self):
        result = parse_composite_id("abc123_KG_None_None_2024_10_3")
        assert result["size"] is None
        assert result["storage_id"] is None
        assert result["share_article_id"] == "abc123"

    def test_all_none_optional_fields(self):
        result = parse_composite_id("None_None_None_None_2026_1_0")
        assert result["share_article_id"] is None
        assert result["unit"] is None
        assert result["size"] is None
        assert result["storage_id"] is None
        assert result["year"] == 2026
        assert result["delivery_week"] == 1
        assert result["day_number"] == 0

    def test_too_few_parts_raises_invalid(self):
        with pytest.raises(CompositeIdInvalid, match="expected 7 parts"):
            parse_composite_id("abc_KG_M")

    def test_too_many_parts_raises_invalid(self):
        with pytest.raises(CompositeIdInvalid, match="expected 7 parts"):
            parse_composite_id("a_b_c_d_1_2_3_extra")

    def test_non_integer_year_raises_invalid(self):
        with pytest.raises(CompositeIdInvalid):
            parse_composite_id("abc_KG_M_store_notint_10_3")


# ---------------------------------------------------------------------------
# build_composite_id  (pure function — no DB needed)
# ---------------------------------------------------------------------------
class TestBuildCompositeId:
    def test_basic_build(self):
        result = build_composite_id("abc123", "KG", "M", "store1", 2024, 10, 3)
        assert result == "abc123_KG_M_store1_2024_10_3"

    def test_none_values_become_string_none(self):
        result = build_composite_id("abc", "KG", None, None, 2026, 1, 0)
        assert result == "abc_KG_None_None_2026_1_0"

    def test_roundtrip(self):
        """build → parse should reconstruct the original values."""
        original = {
            "share_article_id": "abc123",
            "unit": "KG",
            "size": "M",
            "storage_id": "store1",
            "year": 2024,
            "delivery_week": 10,
            "day_number": 3,
        }
        composite = build_composite_id(
            original["share_article_id"],
            original["unit"],
            original["size"],
            original["storage_id"],
            original["year"],
            original["delivery_week"],
            original["day_number"],
        )
        parsed = parse_composite_id(composite)
        assert parsed == original

    def test_roundtrip_with_nones(self):
        composite = build_composite_id("x", None, None, None, 2026, 52, 4)
        parsed = parse_composite_id(composite)
        assert parsed["share_article_id"] == "x"
        assert parsed["unit"] is None
        assert parsed["size"] is None
        assert parsed["storage_id"] is None
        assert parsed["year"] == 2026
        assert parsed["delivery_week"] == 52
        assert parsed["day_number"] == 4
