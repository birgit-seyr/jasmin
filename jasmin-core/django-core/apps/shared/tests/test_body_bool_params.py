"""Tests for :func:`apps.shared.query_params.parse_body_bool`.

The shared body-flag parser every endpoint uses instead of
``bool(body(request).get(...))`` — which reads the string ``"false"`` as True
and switches a feature ON for a caller who asked for it OFF.
"""

from __future__ import annotations

import pytest

from apps.shared.query_params import parse_body_bool
from core.errors import InvalidQueryParam


@pytest.mark.parametrize(
    "value",
    ["false", "False", "FALSE", " false ", "0", "no", "off", False, 0],
)
def test_false_values_parse_as_false(value):
    assert parse_body_bool({"flag": value}, "flag", default=True) is False


@pytest.mark.parametrize(
    "value",
    ["true", "True", "TRUE", " true ", "1", "yes", "on", True, 1],
)
def test_true_values_parse_as_true(value):
    assert parse_body_bool({"flag": value}, "flag") is True


@pytest.mark.parametrize("data", [{}, {"flag": None}, {"flag": ""}])
def test_absent_empty_or_null_yields_the_default(data):
    assert parse_body_bool(data, "flag") is False
    assert parse_body_bool(data, "flag", default=True) is True


@pytest.mark.parametrize("value", ["maybe", "ture", "2", 7, [], {"a": 1}])
def test_unparseable_values_raise_a_400_naming_the_field(value):
    with pytest.raises(InvalidQueryParam) as exc_info:
        parse_body_bool({"flag": value}, "flag")

    error = exc_info.value
    assert error.http_status == 400
    assert error.code == "query.invalid_param"
    assert error.field == "flag"


def test_other_fields_are_not_read():
    assert parse_body_bool({"other": "true"}, "flag") is False
