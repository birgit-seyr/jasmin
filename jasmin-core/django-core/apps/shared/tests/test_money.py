"""Unit tests for the shared ``Decimal`` money primitives.

``fits_decimal_column`` is the gate two call sites use to turn an unstorable
price into a priced 400 before it reaches the database. It therefore has to
ANSWER for every input it is handed — a predicate that raises instead of
returning ``False`` converts the refusal it exists to produce into a 500.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.shared.money import fits_decimal_column

# The shape of ``Subscription.price_per_delivery`` — the column this predicate
# is used against today.
_COLUMN = {"max_digits": 8, "decimal_places": 2}


class TestFitsDecimalColumn:
    @pytest.mark.parametrize(
        "amount",
        ["0", "0.00", "10.99", "999999.99", "-999999.99"],
    )
    def test_an_amount_the_column_stores_as_written_fits(self, amount):
        assert fits_decimal_column(Decimal(amount), **_COLUMN)

    def test_a_trailing_zero_is_not_extra_precision(self):
        assert fits_decimal_column(Decimal("10.9900"), **_COLUMN)

    @pytest.mark.parametrize(
        "amount",
        [
            "1000000",  # integer part overflows numeric(8, 2)
            "1e6",  # the same magnitude in exponent form
            "-1000000",
            "10.999",  # a third decimal the column would round away
            "0.001",
        ],
    )
    def test_an_amount_the_column_would_change_does_not_fit(self, amount):
        assert not fits_decimal_column(Decimal(amount), **_COLUMN)

    @pytest.mark.parametrize("amount", ["NaN", "-NaN", "Infinity", "-Infinity"])
    def test_a_non_finite_amount_does_not_fit(self, amount):
        assert not fits_decimal_column(Decimal(amount), **_COLUMN)

    @pytest.mark.parametrize("amount", ["1e6000000", "-1e6000000", "1e-6000000"])
    def test_an_extreme_exponent_is_answered_rather_than_raised(self, amount):
        """A context-sensitive ``abs()`` raises ``decimal.Overflow`` on these,
        which would escape the caller as a 500 for a value that should simply
        be refused with a 400."""
        assert not fits_decimal_column(Decimal(amount), **_COLUMN)

    def test_the_bound_follows_the_column_it_is_given(self):
        # What numeric(8, 2) refuses, a wider column accepts.
        assert fits_decimal_column(Decimal("1000000"), max_digits=10, decimal_places=2)
        assert fits_decimal_column(Decimal("0.001"), max_digits=8, decimal_places=3)
