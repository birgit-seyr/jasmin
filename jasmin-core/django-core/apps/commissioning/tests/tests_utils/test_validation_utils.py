"""Tests for apps.commissioning.utils.validation_utils.

The helpers raise JasminError subclasses (handled by core.exception_handler)
instead of returning error Responses — tests assert on the raised error's
type, ``http_status``, ``field`` and message.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.commissioning.errors import (
    CommissioningError,
    InvalidQueryParam,
    RequiredFieldMissing,
)
from apps.commissioning.utils.validation_utils import (
    validate_and_parse_int_params,
    validate_bulk_document_request,
)

factory = APIRequestFactory()


def _make_get_request(params: dict | None = None):
    """Helper: build a DRF Request from a GET with query params."""
    from rest_framework.request import Request

    django_request = factory.get("/fake/", params or {})
    return Request(django_request)


def _make_post_request(data: dict | None = None):
    """Helper: build a DRF Request from a POST with JSON body."""
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request

    django_request = factory.post("/fake/", data or {}, format="json")
    return Request(django_request, parsers=[JSONParser()])


# ---------------------------------------------------------------------------
# validate_and_parse_int_params
# ---------------------------------------------------------------------------
class TestValidateAndParseIntParams:
    def test_valid_params(self):
        request = _make_get_request({"year": "2026", "delivery_week": "10"})
        values = validate_and_parse_int_params(request, ["year", "delivery_week"])
        assert values == [2026, 10]

    def test_missing_param_raises(self):
        request = _make_get_request({"year": "2026"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["year", "delivery_week"])
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.field == "delivery_week"
        assert "delivery_week" in excinfo.value.message

    def test_non_integer_raises(self):
        request = _make_get_request({"year": "abc"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["year"])
        assert excinfo.value.field == "year"
        assert "integer" in excinfo.value.message

    def test_year_out_of_range(self):
        request = _make_get_request({"year": "1900"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["year"])
        assert excinfo.value.field == "year"
        assert "2000" in excinfo.value.message

    def test_week_out_of_range_high(self):
        request = _make_get_request({"delivery_week": "54"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["delivery_week"])
        assert "53" in excinfo.value.message

    def test_week_out_of_range_low(self):
        request = _make_get_request({"delivery_week": "0"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["delivery_week"])
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST

    def test_week_alias_also_validated(self):
        request = _make_get_request({"week": "0"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["week"])
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST

    def test_custom_range_overrides_default(self):
        request = _make_get_request({"year": "1950"})
        values = validate_and_parse_int_params(
            request, ["year"], ranges={"year": (1900, 2200)}
        )
        assert values == [1950]

    def test_source_data_reads_from_post_body(self):
        request = _make_post_request({"year": 2026, "delivery_week": 5})
        values = validate_and_parse_int_params(
            request, ["year", "delivery_week"], source="data"
        )
        assert values == [2026, 5]

    def test_param_without_range_passes_any_int(self):
        request = _make_get_request({"custom_param": "999999"})
        values = validate_and_parse_int_params(request, ["custom_param"])
        assert values == [999999]

    def test_boundary_values_accepted(self):
        request = _make_get_request({"year": "2000", "delivery_week": "1"})
        values = validate_and_parse_int_params(request, ["year", "delivery_week"])
        assert values == [2000, 1]

        request = _make_get_request({"year": "2100", "delivery_week": "53"})
        values = validate_and_parse_int_params(request, ["year", "delivery_week"])
        assert values == [2100, 53]


# ---------------------------------------------------------------------------
# validate_bulk_document_request
# ---------------------------------------------------------------------------
class TestValidateBulkDocumentRequest:
    def test_valid_delivery_note(self):
        request = _make_post_request({"ids": ["id1", "id2"], "model": "delivery_note"})
        params = validate_bulk_document_request(request)
        assert params["order_ids"] == ["id1", "id2"]
        assert params["model"] == "delivery_note"
        assert params["date"] is None

    def test_valid_invoice_with_date(self):
        request = _make_post_request(
            {"ids": ["id1"], "model": "invoice", "date": "2026-04-10"}
        )
        params = validate_bulk_document_request(request)
        assert params["model"] == "invoice"
        assert params["date"] == "2026-04-10"

    def test_empty_ids_raises(self):
        request = _make_post_request({"ids": [], "model": "delivery_note"})
        with pytest.raises(RequiredFieldMissing) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.field == "ids"

    def test_ids_not_list_raises(self):
        request = _make_post_request({"ids": "not_a_list", "model": "invoice"})
        with pytest.raises(RequiredFieldMissing) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST

    def test_invalid_model_raises(self):
        request = _make_post_request({"ids": ["id1"], "model": "order"})
        with pytest.raises(CommissioningError) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.field == "model"
        assert excinfo.value.code == "bulk_documents.model_invalid"

    def test_missing_ids_raises(self):
        request = _make_post_request({"model": "invoice"})
        with pytest.raises(RequiredFieldMissing) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
