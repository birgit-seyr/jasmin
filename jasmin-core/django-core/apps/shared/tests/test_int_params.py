"""Tests for the ``int`` query-param kind, its bounds, and the ISO-week rule.

One parser reads every integer the API takes — query string and POST body
alike — so the accepted spellings and the 400 shape cannot differ by call site.
The bounds it enforces are the ones the OpenAPI schema publishes, and the year
range is shared by every app's catalogue rather than re-picked per app.

Week 53 is the one rule a single spec cannot hold: it exists only in a 53-week
year, so the pair is checked once both halves are parsed.
"""

from __future__ import annotations

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.shared.openapi_params import catalogue_parameter, param_schema
from apps.shared.query_params import (
    ISO_WEEK_PARAM,
    YEAR_PARAM,
    ParamSpec,
    coerce_param,
    validate_query_params,
    weeks_in_iso_year,
)
from core.errors import InvalidQueryParam

CATALOGUE = {
    "year": YEAR_PARAM,
    "delivery_week": ISO_WEEK_PARAM,
    "day_number": ParamSpec("int", min_value=0, max_value=6),
    "tour": ParamSpec("int", min_value=0),
    "source": ParamSpec("choice", choices=("WASTE", "HARVEST")),
}


def _validate(query: str, **named):
    request = Request(APIRequestFactory().get(f"/rows/{query}"))
    return validate_query_params(request, CATALOGUE, **named)


class TestIntSpellings:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2026", 2026), (" 2026 ", 2026), ("+2026", 2026)],
    )
    def test_accepted_spellings(self, raw, expected):
        """Whitespace and a leading sign already parsed before the catalogue
        took over the reading; they still do."""
        assert coerce_param(raw, "year", YEAR_PARAM) == expected

    @pytest.mark.parametrize("raw", ["20_26", "٢٠٢٦", "2026.0", "2e3", "abc", "- 5"])
    def test_refused_spellings(self, raw):
        """``int()`` reads all of these; none is a year anyone means, and each
        renders differently the moment it is echoed back as a string."""
        with pytest.raises(InvalidQueryParam) as exc_info:
            coerce_param(raw, "year", YEAR_PARAM)

        error = exc_info.value
        assert error.http_status == 400
        assert error.code == "query.invalid_param"
        assert error.field == "year"
        assert error.details == {"year": raw}

    def test_a_str_param_keeps_its_surrounding_whitespace(self):
        """Ids are matched byte for byte, so ``str`` is the one kind that is
        not trimmed."""
        assert coerce_param(" abc ", "member", ParamSpec("str")) == " abc "

    def test_a_date_is_trimmed_like_the_other_kinds(self):
        assert coerce_param(" 2026-01-05 ", "date_from", ParamSpec("date")).isoformat()

    def test_a_choice_is_trimmed_like_the_other_kinds(self):
        assert _validate("?source=%20HARVEST%20", optional=["source"]) == {
            "source": "HARVEST"
        }


class TestIntBounds:
    @pytest.mark.parametrize("raw", ["1900", "2100"])
    def test_the_range_edges_are_inside(self, raw):
        assert _validate(f"?year={raw}", optional=["year"])["year"] == int(raw)

    @pytest.mark.parametrize(
        ("query", "field"),
        [
            ("?year=1899", "year"),
            ("?year=2101", "year"),
            ("?day_number=7", "day_number"),
        ],
    )
    def test_a_value_past_the_range_is_refused(self, query, field):
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(query, optional=["year", "day_number"])
        assert exc_info.value.field == field

    def test_every_app_catalogue_shares_one_year_range(self):
        """One shared spec, so the same year cannot be legal in one app and
        refused in another."""
        from apps.commissioning.utils.query_params import (
            PARAM_CATALOGUE as commissioning,
        )
        from apps.payments.viewsets import PARAM_CATALOGUE as payments
        from apps.staff.query_params import STAFF_PARAM_CATALOGUE as staff

        assert commissioning["year"] is YEAR_PARAM
        assert payments["year"] is YEAR_PARAM
        assert staff["year"] is YEAR_PARAM


class TestIsoWeekPair:
    def test_weeks_in_iso_year(self):
        assert weeks_in_iso_year(2026) == 53
        assert weeks_in_iso_year(2027) == 52

    def test_week_53_is_served_by_a_53_week_year(self):
        parsed = _validate(
            "?year=2026&delivery_week=53", optional=["year", "delivery_week"]
        )
        assert parsed == {"year": 2026, "delivery_week": 53}

    def test_week_53_is_refused_by_a_52_week_year(self):
        """``isoweek.Week(2027, 53)`` silently means 2028-W01, so without this
        the endpoint answers for a week the caller never asked about."""
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate("?year=2027&delivery_week=53", optional=["year", "delivery_week"])

        error = exc_info.value
        assert error.code == "query.invalid_param"
        assert error.field == "delivery_week"
        assert "52" in error.message

    def test_the_last_week_of_a_52_week_year_is_fine(self):
        parsed = _validate(
            "?year=2027&delivery_week=52", optional=["year", "delivery_week"]
        )
        assert parsed["delivery_week"] == 52

    def test_a_week_without_a_year_in_the_same_call_is_not_pair_checked(self):
        """The rule needs both halves; an endpoint that reads only the week has
        no year to judge it against."""
        assert _validate("?delivery_week=53", optional=["delivery_week"]) == {
            "delivery_week": 53
        }

    def test_an_absent_year_does_not_refuse_the_week(self):
        parsed = _validate("?delivery_week=53", optional=["year", "delivery_week"])
        assert parsed == {"year": None, "delivery_week": 53}


class TestSchemaBounds:
    def test_param_schema_carries_the_enforced_range(self):
        assert param_schema(YEAR_PARAM) == {
            "type": "integer",
            "minimum": 1900,
            "maximum": 2100,
        }

    def test_catalogue_parameter_publishes_the_bounds(self):
        """The bridge publishes the range the validator enforces, not the type
        alone."""
        assert catalogue_parameter("year", CATALOGUE).type == {
            "type": "integer",
            "minimum": 1900,
            "maximum": 2100,
        }
        assert catalogue_parameter("delivery_week", CATALOGUE).type == {
            "type": "integer",
            "minimum": 1,
            "maximum": 53,
        }

    def test_a_one_sided_range_publishes_only_that_side(self):
        assert catalogue_parameter("tour", CATALOGUE).type == {
            "type": "integer",
            "minimum": 0,
        }

    def test_a_spec_without_bounds_publishes_none(self):
        parameter = catalogue_parameter("free", {"free": ParamSpec("int")})
        assert parameter.type == {"type": "integer"}

    def test_a_choice_still_declares_its_enum(self):
        """``enum`` stays a parameter keyword so drf-spectacular keeps sorting
        the emitted values as it always has."""
        parameter = catalogue_parameter("source", CATALOGUE)
        assert parameter.enum == ["WASTE", "HARVEST"]
        assert parameter.type["type"] == "string"
