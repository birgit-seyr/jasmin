"""Contract: a documented ``required`` query parameter is one the server needs.

Each row below pairs an operation's OpenAPI declaration with what the server
actually does on a bare call. Two lies are possible and both are caught here:

* documented required, served anyway — the client is told to send something the
  endpoint ignores, and generated clients make it mandatory for nothing;
* documented optional, refused at runtime — the generated client type says the
  call is legal and the server 400s.

The schema is the one drf-spectacular emits, so these assertions fail if an
``@extend_schema`` and its ``validate_query_params`` call drift apart.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import pytest
from django.urls import reverse
from rest_framework import status


@cache
def _schema() -> dict[str, Any]:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def _query_parameters(path: str) -> dict[str, dict[str, Any]]:
    """The GET operation's query parameters at ``path``, keyed by name."""
    operation = _schema()["paths"][path]["get"]
    return {
        parameter["name"]: parameter
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }


def _required_names(path: str) -> set[str]:
    return {
        name
        for name, parameter in _query_parameters(path).items()
        if parameter.get("required")
    }


# (path, URL name, the params the endpoint cannot answer without)
_REQUIRED_SCOPES = [
    ("/api/commissioning/orders_overview/", "orders_overview", {"year"}),
    (
        "/api/commissioning/default_share_contents/bulk_list/",
        "default_share_contents-bulk-list",
        {"year", "share_option"},
    ),
    (
        "/api/commissioning/harvest/export_csv/",
        "harvest-export-csv",
        {"date_from", "date_to"},
    ),
    (
        "/api/commissioning/purchase/export_csv/",
        "purchase-export-csv",
        {"date_from", "date_to"},
    ),
    (
        "/api/commissioning/members/export_csv/",
        "member-export-csv",
        {"date_from", "date_to"},
    ),
    (
        "/api/commissioning/shares/export_csv/",
        "share-export-csv",
        {"date_from", "date_to"},
    ),
]

# (path, URL name, filters the endpoint narrows by when they are sent)
_OPTIONAL_FILTERS = [
    (
        "/api/commissioning/waste/",
        "waste-list",
        {"year", "delivery_week", "day_number"},
    ),
    ("/api/commissioning/coop_shares/", "coop_shares-list", {"member", "year"}),
    (
        "/api/commissioning/order_contents/",
        "order_contents-list",
        {"reseller", "year", "delivery_week", "day_number"},
    ),
    (
        "/api/commissioning/external_share_demand/",
        "external_share_demand-list",
        {"year", "delivery_week"},
    ),
]

_EXPORT_DATE_RANGE_PATHS = [path for path, _url_name, _params in _REQUIRED_SCOPES[2:]]


@pytest.mark.django_db
class TestDocumentedQueryParamContract:
    @pytest.mark.parametrize(
        ("path", "url_name", "scope"),
        _REQUIRED_SCOPES,
        ids=[url_name for _path, url_name, _scope in _REQUIRED_SCOPES],
    )
    def test_required_params_are_documented_and_enforced(
        self, api_client, tenant, path, url_name, scope
    ):
        assert scope <= _required_names(path)

        resp = api_client.get(reverse(url_name))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert resp.data["field"] in scope

    @pytest.mark.parametrize(
        ("path", "url_name", "filters"),
        _OPTIONAL_FILTERS,
        ids=[url_name for _path, url_name, _filters in _OPTIONAL_FILTERS],
    )
    def test_optional_filters_are_documented_optional_and_served(
        self, api_client, tenant, path, url_name, filters
    ):
        assert filters & _required_names(path) == set()

        resp = api_client.get(reverse(url_name))
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize(
        ("path", "name", "schema"),
        [
            (
                "/api/commissioning/orders_overview/",
                "year",
                {"type": "integer", "minimum": 1900, "maximum": 2100},
            ),
            (
                "/api/commissioning/waste/",
                "delivery_week",
                {"type": "integer", "minimum": 1, "maximum": 53},
            ),
            (
                "/api/commissioning/waste/",
                "day_number",
                {"type": "integer", "minimum": 0, "maximum": 6},
            ),
        ],
    )
    def test_int_params_publish_the_range_the_validator_enforces(
        self, path, name, schema
    ):
        """The published ``minimum``/``maximum`` are the ones ``coerce_param``
        enforces, so a generated client can tell 2026 from 20260."""
        assert _query_parameters(path)[name]["schema"] == schema

    @pytest.mark.parametrize("path", _EXPORT_DATE_RANGE_PATHS)
    def test_export_date_range_is_documented_as_a_date(self, path):
        """The exports validate the pair through the catalogue's ``date`` kind,
        so the schema has to say ``format: date`` rather than a free string."""
        parameters = _query_parameters(path)
        for name in ("date_from", "date_to"):
            assert parameters[name]["schema"] == {"type": "string", "format": "date"}
