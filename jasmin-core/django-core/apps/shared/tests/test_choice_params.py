"""Tests for the ``choice`` query-param kind in :mod:`apps.shared.query_params`.

Two behaviours let a catalogue close an enum without breaking a live caller: a
``case_insensitive`` spec takes either casing and hands back the catalogue's
spelling, and a spec with a ``wire_name`` is read from — and reports failures
under — the name the client actually sends, so one app can catalogue two
different enums that share a generic name on the wire.
"""

from __future__ import annotations

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.shared.query_params import ParamSpec, validate_query_params
from core.errors import InvalidQueryParam

CATALOGUE = {
    "source": ParamSpec(
        "choice",
        choices=("HARVEST", "PURCHASE"),
        default="HARVEST",
        case_insensitive=True,
    ),
    "period": ParamSpec("choice", choices=("month", "week"), default="month"),
    "consent_kind": ParamSpec("choice", choices=("privacy", "sepa"), wire_name="kind"),
    "mapping_kind": ParamSpec("choice", choices=("station", "day"), wire_name="kind"),
}


def _validate(query: str, **named):
    request = Request(APIRequestFactory().get(f"/rows/{query}"))
    return validate_query_params(request, CATALOGUE, **named)


@pytest.mark.parametrize("sent", ["HARVEST", "harvest", "Harvest"])
def test_case_insensitive_choice_yields_the_catalogue_spelling(sent):
    assert _validate(f"?source={sent}", optional=["source"])["source"] == "HARVEST"


def test_a_plain_choice_still_refuses_the_wrong_casing():
    with pytest.raises(InvalidQueryParam):
        _validate("?period=Month", optional=["period"])


@pytest.mark.parametrize("query", ["", "?source="])
def test_absent_or_empty_value_yields_the_catalogue_default(query):
    assert _validate(query, optional=["source"])["source"] == "HARVEST"


def test_unknown_value_is_a_400_naming_the_parameter():
    with pytest.raises(InvalidQueryParam) as exc_info:
        _validate("?source=compost", optional=["source"])

    error = exc_info.value
    assert error.http_status == 400
    assert error.code == "query.invalid_param"
    assert error.field == "source"
    assert error.details == {"source": "compost"}


def test_wire_name_reads_the_parameter_the_client_sends():
    assert _validate("?kind=privacy", optional=["consent_kind"]) == {
        "consent_kind": "privacy"
    }


def test_two_specs_may_share_one_wire_name_with_different_enums():
    assert _validate("?kind=station", optional=["mapping_kind"])["mapping_kind"] == (
        "station"
    )
    with pytest.raises(InvalidQueryParam):
        _validate("?kind=station", optional=["consent_kind"])


def test_wire_name_failures_name_the_sent_parameter():
    with pytest.raises(InvalidQueryParam) as invalid:
        _validate("?kind=nonsense", optional=["consent_kind"])
    assert invalid.value.field == "kind"

    with pytest.raises(InvalidQueryParam) as missing:
        _validate("", required=["consent_kind"])
    assert missing.value.field == "kind"
