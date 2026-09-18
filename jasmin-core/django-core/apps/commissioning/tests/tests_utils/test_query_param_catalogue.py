"""Tests for the commissioning query-param catalogue and what is derived from it.

The catalogue is the single source of truth for what a query parameter is: the
validator enforces it and the OpenAPI helpers publish it. Four properties keep
that claim honest — it declares only params the API really accepts, the values
it hands back are the ones downstream signatures take, a param filtering an
integer column is bounded by that column's range, and the published description
agrees with the published enum.
"""

from __future__ import annotations

import ast
import re
import typing
from pathlib import Path

import pytest
from django.db import connection
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.commissioning import schemas as commissioning_schemas
from apps.commissioning.models.choices import ShareOptions
from apps.commissioning.models.days import DeliveryStationDay
from apps.commissioning.models.shares import ShareContent
from apps.commissioning.services.packing_list_boxes_matrix_service import (
    PackingListBoxesMatrixService,
)
from apps.commissioning.services.packing_list_service import PackingListService
from apps.commissioning.utils.delivery_utils import tour_station_ids
from apps.commissioning.utils.query_params import (
    MAX_PACKING_STATION,
    MAX_TOUR_NUMBER,
    PARAM_CATALOGUE,
    validate_query_params,
)
from core.errors import InvalidQueryParam


def _validate(query: str, **named):
    request = Request(APIRequestFactory().get(f"/rows/{query}"))
    return validate_query_params(request, **named)


class TestCatalogueDeclaresOnlyLiveParams:
    """A spec no endpoint reads is not a contract — it documents a parameter
    the API does not take and invites a caller to send it."""

    def test_a_parameter_no_endpoint_reads_is_not_catalogued(self):
        assert "manual" not in PARAM_CATALOGUE


class TestShareOptionCasing:
    """The POST/PATCH body upper-cases ``share_option`` before validating it,
    so the query filter over the same enum takes the same spellings."""

    @pytest.mark.parametrize(
        "sent", ["HARVEST_SHARE", "harvest_share", "Harvest_Share"]
    )
    def test_any_casing_yields_the_catalogue_spelling(self, sent):
        parsed = _validate(f"?share_option={sent}", optional=["share_option"])
        assert parsed["share_option"] == "HARVEST_SHARE"

    def test_a_value_outside_the_enum_is_still_refused(self):
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate("?share_option=gemuese", optional=["share_option"])

        error = exc_info.value
        assert error.http_status == 400
        assert error.code == "query.invalid_param"
        assert error.field == "share_option"


class TestTourIsAnInt:
    """``tour`` and ``packing_station`` are parsed to ``int`` by the catalogue
    and passed straight through, so the consumers annotate the int they get."""

    def test_the_catalogue_parses_them_as_ints(self):
        assert _validate("?tour=3", optional=["tour"])["tour"] == 3
        assert PARAM_CATALOGUE["packing_station"].kind == "int"

    @pytest.mark.parametrize(
        ("function", "expected"),
        [
            (PackingListService.get_packing_list, int | None),
            (PackingListService.get_member_amounts_matrix, int | None),
            (PackingListBoxesMatrixService.get_boxes_matrix, int | None),
            (tour_station_ids, int),
        ],
    )
    def test_consumers_annotate_the_parsed_type(self, function, expected):
        assert typing.get_type_hints(function)["tour"] == expected


# Each bounded param, paired with the model column it filters and the maximum
# the catalogue allows.
_BOUNDED_PARAMS = (
    ("tour", DeliveryStationDay, "tour_number", MAX_TOUR_NUMBER),
    ("packing_station", ShareContent, "packing_station", MAX_PACKING_STATION),
)

_MAXIMA = [(name, maximum) for name, _model, _column, maximum in _BOUNDED_PARAMS]


class TestTourAndPackingStationOperatingMaxima:
    """Both params are queryset filters, so the bound is what the platform
    operates rather than what the column could store: a larger number is a
    typo, and unbounded it answers with an empty grid that reads as "no rows
    here" instead of "no such tour"."""

    @pytest.mark.parametrize(("name", "maximum"), _MAXIMA)
    def test_the_catalogue_bound_is_the_operating_maximum(self, name, maximum):
        assert PARAM_CATALOGUE[name].max_value == maximum

    @pytest.mark.parametrize(("name", "model", "column", "maximum"), _BOUNDED_PARAMS)
    def test_the_maximum_still_fits_the_column_it_filters(
        self, name, model, column, maximum
    ):
        """Raised past its column, a maximum would accept a filter value no
        stored row could ever hold."""
        internal_type = model._meta.get_field(column).get_internal_type()
        _, column_ceiling = connection.ops.integer_field_range(internal_type)

        assert maximum <= column_ceiling

    @pytest.mark.parametrize(("name", "maximum"), _MAXIMA)
    def test_the_maximum_itself_is_accepted(self, name, maximum):
        assert _validate(f"?{name}={maximum}", optional=[name])[name] == maximum

    @pytest.mark.parametrize(("name", "maximum"), _MAXIMA)
    def test_a_value_past_the_maximum_is_refused(self, name, maximum):
        with pytest.raises(InvalidQueryParam) as exc_info:
            _validate(f"?{name}={maximum + 1}", optional=[name])

        error = exc_info.value
        assert error.http_status == 400
        assert error.code == "query.invalid_param"
        assert error.field == name

    @pytest.mark.parametrize(
        ("name", "sent"),
        [("tour", 0), ("tour", 3), ("packing_station", 1), ("packing_station", 4)],
    )
    def test_the_values_endpoints_really_receive_still_parse(self, name, sent):
        assert _validate(f"?{name}={sent}", optional=[name])[name] == sent


APPS_ROOT = Path(commissioning_schemas.__file__).resolve().parents[1]

_EXAMPLE_CLAUSE = re.compile(r"e\.g\.\s*([^).]*)")
_EXAMPLE_TOKEN = re.compile(r"[A-Za-z][A-Za-z_]*")


def _share_option_descriptions() -> list[tuple[str, str]]:
    """Every ``catalogue_param("share_option", ...)`` description written under
    ``apps/``, paired with the ``path:line`` it is written at."""
    descriptions: list[tuple[str, str]] = []
    for path in sorted(APPS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            called = (
                function.attr
                if isinstance(function, ast.Attribute)
                else getattr(function, "id", None)
            )
            if called != "catalogue_param":
                continue
            first_argument = node.args[0] if node.args else None
            if (
                not isinstance(first_argument, ast.Constant)
                or first_argument.value != "share_option"
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(
                    keyword.value, ast.Constant
                ):
                    location = f"{path.relative_to(APPS_ROOT)}:{node.lineno}"
                    descriptions.append((location, keyword.value.value))
    return descriptions


def _documented_examples(description: str) -> set[str]:
    """The values an ``e.g.`` clause in ``description`` offers the reader."""
    return {
        token
        for clause in _EXAMPLE_CLAUSE.findall(description)
        for token in _EXAMPLE_TOKEN.findall(clause)
    }


class TestShareOptionDocumentation:
    """Every endpoint documenting ``share_option`` publishes the ``ShareOptions``
    enum beside its description, so an example outside that enum is one the
    validator answers with a 400 — a dead end for the reader following the docs.
    The catalogue folds casing, so the example may be written in any casing."""

    def test_the_parameter_is_documented_with_an_example(self):
        descriptions = _share_option_descriptions()

        assert descriptions, 'no catalogue_param("share_option", ...) call found'
        assert any(
            _documented_examples(description) for _, description in descriptions
        ), f"no share_option description names an example value: {descriptions}"

    def test_every_documented_example_is_a_value_of_the_published_enum(self):
        values = set(ShareOptions.values)

        outside_the_enum = {}
        for location, description in _share_option_descriptions():
            rejected = sorted(
                example
                for example in _documented_examples(description)
                if example.upper() not in values
            )
            if rejected:
                outside_the_enum[location] = rejected

        assert (
            not outside_the_enum
        ), f"examples the validator would refuse: {outside_the_enum}"
