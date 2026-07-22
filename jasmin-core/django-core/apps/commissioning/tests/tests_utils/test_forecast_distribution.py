"""Unit tests for ``split_forecast_amount_by_weight`` (pure Decimal math, no DB).

The office can opt a tenant into ``distribute_forecast_by_weight``: when a
ShareContent is created out of a forecast, the amount is this weighted split
instead of the DefaultShareArticleInShare / DefaultShareContent default — the
forecast total spread across the sizes proportional to ``average_weight`` and
their physical counts, floored to 0.10.
"""

from decimal import Decimal

from apps.commissioning.utils import split_forecast_amount_by_weight


class TestSplitForecastAmountByWeight:
    def test_weighted_split_each_size_scales_with_its_weight(self):
        # S weighs 1kg, M weighs 2kg; 10 S-shares, 5 M-shares; forecast 100.
        # k = 100 / (10*1 + 5*2) = 5 -> each S = 5, each M = 10.
        result = split_forecast_amount_by_weight(
            forecast_amount=Decimal("100"),
            variation_weights={"S": Decimal("1"), "M": Decimal("2")},
            variation_counts={"S": 10, "M": 5},
        )
        assert result == {"S": Decimal("5.0"), "M": Decimal("10.0")}
        assert result["S"] * 2 == result["M"]

    def test_total_handed_out_equals_forecast_when_it_divides_cleanly(self):
        result = split_forecast_amount_by_weight(
            Decimal("100"),
            {"S": Decimal("1"), "M": Decimal("2")},
            {"S": 10, "M": 5},
        )
        assert result["S"] * 10 + result["M"] * 5 == Decimal("100")

    def test_fractional_amount_is_floored_to_two_tenths(self):
        # k = 100 / (10*1 + 10*2) = 3.3333...  -> S floors to 3.3, M to 6.6
        result = split_forecast_amount_by_weight(
            Decimal("100"),
            {"S": Decimal("1"), "M": Decimal("2")},
            {"S": 10, "M": 10},
        )
        assert result == {"S": Decimal("3.3"), "M": Decimal("6.6")}

    def test_floor_never_over_allocates(self):
        result = split_forecast_amount_by_weight(
            Decimal("100"),
            {"S": Decimal("1"), "M": Decimal("2")},
            {"S": 10, "M": 10},
        )
        assert result["S"] * 10 + result["M"] * 10 <= Decimal("100")

    def test_missing_weight_variation_is_skipped(self):
        result = split_forecast_amount_by_weight(
            Decimal("100"),
            {"S": Decimal("1"), "M": Decimal("2"), "NO_WEIGHT": None},
            {"S": 10, "M": 5, "NO_WEIGHT": 3},
        )
        assert "NO_WEIGHT" not in result
        assert result == {"S": Decimal("5.0"), "M": Decimal("10.0")}

    def test_non_positive_weight_is_skipped(self):
        result = split_forecast_amount_by_weight(
            Decimal("100"),
            {"S": Decimal("1"), "ZERO": Decimal("0"), "NEG": Decimal("-2")},
            {"S": 10, "ZERO": 5, "NEG": 5},
        )
        assert set(result) == {"S"}

    def test_zero_counts_give_empty(self):
        assert (
            split_forecast_amount_by_weight(
                Decimal("100"),
                {"S": Decimal("1"), "M": Decimal("2")},
                {"S": 0, "M": 0},
            )
            == {}
        )

    def test_no_forecast_gives_empty(self):
        assert (
            split_forecast_amount_by_weight(None, {"S": Decimal("1")}, {"S": 10}) == {}
        )
        assert (
            split_forecast_amount_by_weight(
                Decimal("0"), {"S": Decimal("1")}, {"S": 10}
            )
            == {}
        )

    def test_missing_count_treated_as_zero(self):
        # M has no count entry -> counts as 0 in the denominator, still gets its
        # weight-proportional per-share amount from the S-driven k.
        result = split_forecast_amount_by_weight(
            Decimal("50"),
            {"S": Decimal("1"), "M": Decimal("2")},
            {"S": 10},
        )
        assert result == {"S": Decimal("5.0"), "M": Decimal("10.0")}

    def test_float_inputs_are_decimal_safe(self):
        # floats route through str, not Decimal(float) -> no binary drift.
        result = split_forecast_amount_by_weight(
            100.0, {"S": 1.1, "M": 2.2}, {"S": 10, "M": 10}
        )
        assert result["S"] == Decimal("3.3")
        assert result["M"] == Decimal("6.6")

    def test_amount_over_99_90_is_capped_to_99_99(self):
        # forecast 200 over 1 share -> 200, which overflows NUMERIC(5,3) -> 99.99.
        result = split_forecast_amount_by_weight(
            Decimal("200"), {"S": Decimal("1")}, {"S": 1}
        )
        assert result["S"] == Decimal("99.99")

    def test_the_reported_133_30_case_is_capped(self):
        # forecast 1333 / 10 shares -> 133.3 -> capped to 99.99.
        result = split_forecast_amount_by_weight(
            Decimal("1333"), {"S": Decimal("1")}, {"S": 10}
        )
        assert result["S"] == Decimal("99.99")

    def test_exactly_99_90_is_not_capped(self):
        result = split_forecast_amount_by_weight(
            Decimal("99.90"), {"S": Decimal("1")}, {"S": 1}
        )
        assert result["S"] == Decimal("99.9")

    def test_only_the_oversized_variation_is_capped(self):
        # k = 200 / (1*1 + 1*100) = 1.98..  -> S=1.9 (kept), M=198.0 -> 99.99.
        result = split_forecast_amount_by_weight(
            Decimal("200"),
            {"S": Decimal("1"), "M": Decimal("100")},
            {"S": 1, "M": 1},
        )
        assert result["M"] == Decimal("99.99")
        assert result["S"] < Decimal("99.90")
