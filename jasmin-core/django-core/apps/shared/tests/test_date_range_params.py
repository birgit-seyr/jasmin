"""Tests for the inclusive date-range rule: a range must run forwards.

The order of a date pair is one rule for the whole API, checked where the pair
is parsed, so every endpoint that takes a range refuses an inverted one the
same way — one code (``query.invalid_param``), one shape, ``field`` naming the
start parameter.
"""

from __future__ import annotations

import datetime

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.shared.query_params import (
    DATE_RANGE_PAIRS,
    ParamSpec,
    validate_query_params,
)
from core.errors import InvalidQueryParam

CATALOGUE = {
    "start_date": ParamSpec("date"),
    "end_date": ParamSpec("date"),
    "date_from": ParamSpec("date"),
    "date_to": ParamSpec("date"),
    # Two dates that are NOT a range: each answers its own question.
    "active_at_date": ParamSpec("date"),
    "price_date": ParamSpec("date"),
}


def _validate(query: str, catalogue=None, **named):
    request = Request(APIRequestFactory().get(f"/rows/{query}"))
    return validate_query_params(request, catalogue or CATALOGUE, **named)


class TestInvertedRangeIsRefused:
    @pytest.mark.parametrize(("start", "end"), DATE_RANGE_PAIRS)
    def test_every_pair_is_checked(self, start, end):
        """Both spellings the API uses for a range are covered, so an endpoint
        cannot pick the unchecked one."""
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(f"?{start}=2026-05-10&{end}=2026-05-01", required=[start, end])

        error = exc_info.value
        assert error.code == "query.invalid_param"
        assert error.field == start
        assert error.details == {start: "2026-05-10", end: "2026-05-01"}
        assert f"'{start}' must be on or before '{end}'" in error.message

    def test_optional_halves_are_checked_too(self):
        """The stock ledger takes its range as two optional filters; sending
        both inverted is the same mistake as on a required pair."""
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(
                "?start_date=2026-05-10&end_date=2026-05-01",
                optional=["start_date", "end_date"],
            )

        assert exc_info.value.field == "start_date"

    def test_the_error_names_the_wire_name(self):
        """A pair catalogued under a logical key reports the name the client
        sent, so ``field`` stays keyable against the request."""
        catalogue = {
            "date_from": ParamSpec("date", wire_name="from"),
            "date_to": ParamSpec("date", wire_name="to"),
        }
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(
                "?from=2026-05-10&to=2026-05-01",
                catalogue,
                required=["date_from", "date_to"],
            )

        error = exc_info.value
        assert error.field == "from"
        assert error.details == {"from": "2026-05-10", "to": "2026-05-01"}


class TestValidRangesPassThrough:
    def test_ascending_range_parses(self):
        parsed = _validate(
            "?date_from=2026-05-01&date_to=2026-05-10",
            required=["date_from", "date_to"],
        )
        assert parsed == {
            "date_from": datetime.date(2026, 5, 1),
            "date_to": datetime.date(2026, 5, 10),
        }

    def test_a_single_day_range_is_valid(self):
        """Equal ends are one day, inclusive on both sides — the CSV exports
        are asked for exactly that."""
        parsed = _validate(
            "?date_from=2026-05-01&date_to=2026-05-01",
            required=["date_from", "date_to"],
        )
        assert parsed["date_from"] == parsed["date_to"]

    @pytest.mark.parametrize(
        "query", ["?start_date=2026-05-10", "?end_date=2026-05-01"]
    )
    def test_one_half_alone_is_not_a_range(self, query):
        """A start with no end (or the reverse) has nothing to compare against;
        the endpoints that take only one of the two are untouched."""
        assert _validate(query, optional=["start_date", "end_date"])

    def test_two_dates_that_are_not_a_pair_are_left_alone(self):
        """``active_at_date`` and ``price_date`` each answer their own
        question, so their relative order means nothing."""
        parsed = _validate(
            "?active_at_date=2026-05-10&price_date=2026-05-01",
            optional=["active_at_date", "price_date"],
        )
        assert parsed["active_at_date"] > parsed["price_date"]


class TestTheRuleIsTheCataloguesWork:
    @pytest.mark.parametrize(("start", "end"), DATE_RANGE_PAIRS)
    def test_each_pair_is_declared_in_a_real_catalogue(self, start, end):
        """A pair listed here but catalogued nowhere would be dead config; a
        pair catalogued as anything but ``date`` would never be compared."""
        from apps.commissioning.utils.query_params import PARAM_CATALOGUE

        assert PARAM_CATALOGUE[start].kind == "date"
        assert PARAM_CATALOGUE[end].kind == "date"

    def test_the_payments_catalogue_gets_the_same_rule(self):
        """The rule travels with ``validate_query_params``, so an app with its
        own catalogue does not re-implement (or forget) it."""
        from apps.payments.viewsets import PARAM_CATALOGUE as PAYMENTS_CATALOGUE

        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(
                "?date_from=2026-05-10&date_to=2026-05-01",
                PAYMENTS_CATALOGUE,
                required=["date_from", "date_to"],
            )

        assert exc_info.value.code == "query.invalid_param"
        assert exc_info.value.field == "date_from"
