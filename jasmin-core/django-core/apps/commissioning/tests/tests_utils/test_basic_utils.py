"""Tests for apps.commissioning.utils.basic_utils."""

from __future__ import annotations

from django.db.models import IntegerField

from apps.commissioning.models.choices_text import (
    ShareTypeVariationSizeOptions,
    UnitOptions,
    VegetableSizeOptions,
)
from apps.commissioning.utils.basic_utils import (
    create_share_article_sorter,
    extract_amounts_from_keys,
    size_order_annotation,
    sort_share_articles,
)


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


# ---------------------------------------------------------------------------
# size_order_annotation
# ---------------------------------------------------------------------------
class TestSizeOrderAnnotation:
    def test_returns_case_expression(self):
        annotation = size_order_annotation()
        # Should be a Django Case expression with IntegerField output
        assert annotation.output_field.__class__ == IntegerField

    def test_maps_all_size_options(self):
        annotation = size_order_annotation()
        # Should have one When clause per ShareTypeVariationSizeOptions choice
        assert len(annotation.cases) == len(ShareTypeVariationSizeOptions.choices)

    def test_ordering_matches_enum_order(self):
        annotation = size_order_annotation()
        for idx, when_clause in enumerate(annotation.cases):
            # Each When should map to its enum index
            assert when_clause.result.value == idx


# ---------------------------------------------------------------------------
# create_share_article_sorter / sort_share_articles
# ---------------------------------------------------------------------------
class TestCreateShareArticleSorter:
    def test_sorts_by_name_first(self):
        articles = [
            {"share_article_name": "Tomato", "unit": "KG", "size": "M"},
            {"share_article_name": "Apple", "unit": "KG", "size": "M"},
        ]
        result = sort_share_articles(articles)
        assert result[0]["share_article_name"] == "Apple"
        assert result[1]["share_article_name"] == "Tomato"

    def test_sorts_by_unit_within_same_name(self):
        unit_order = [c[0] for c in UnitOptions.choices]
        articles = [
            {"share_article_name": "Carrot", "unit": unit_order[-1], "size": "M"},
            {"share_article_name": "Carrot", "unit": unit_order[0], "size": "M"},
        ]
        result = sort_share_articles(articles)
        assert result[0]["unit"] == unit_order[0]
        assert result[1]["unit"] == unit_order[-1]

    def test_sorts_by_size_within_same_name_and_unit(self):
        size_order = [c[0] for c in VegetableSizeOptions.choices]
        articles = [
            {"share_article_name": "Carrot", "unit": "KG", "size": size_order[-1]},
            {"share_article_name": "Carrot", "unit": "KG", "size": size_order[0]},
        ]
        result = sort_share_articles(articles)
        assert result[0]["size"] == size_order[0]
        assert result[1]["size"] == size_order[-1]

    def test_unknown_unit_sorts_last(self):
        articles = [
            {"share_article_name": "Carrot", "unit": "UNKNOWN_UNIT", "size": "M"},
            {"share_article_name": "Carrot", "unit": "KG", "size": "M"},
        ]
        result = sort_share_articles(articles)
        assert result[0]["unit"] == "KG"
        assert result[1]["unit"] == "UNKNOWN_UNIT"

    def test_missing_fields_default_to_empty_string(self):
        articles = [
            {"share_article_name": "Tomato"},
            {"share_article_name": "Apple", "unit": "KG", "size": "M"},
        ]
        sorter = create_share_article_sorter()
        # Should not raise — missing keys default to empty string
        result = sorted(articles, key=sorter)
        assert result[0]["share_article_name"] == "Apple"

    def test_accepts_custom_choices(self):
        sorter = create_share_article_sorter(
            unit_choices=UnitOptions,
            size_choices=VegetableSizeOptions,
        )
        key = sorter({"share_article_name": "X", "unit": "KG", "size": "M"})
        assert isinstance(key, tuple)
        assert len(key) == 3

    def test_empty_list(self):
        assert sort_share_articles([]) == []
