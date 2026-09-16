"""Tests for apps.commissioning.utils.validation_utils.

The helpers raise JasminError subclasses (handled by core.exception_handler)
instead of returning error Responses — tests assert on the raised error's
type, ``http_status``, ``field`` and message.
"""

from __future__ import annotations

import datetime

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.commissioning.errors import (
    BulkFinalizeIdsInvalid,
    BulkIdsInvalid,
    CommissioningError,
    InvalidQueryParam,
    RequiredFieldMissing,
)
from apps.commissioning.utils.validation_utils import (
    parse_bulk_ids,
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
        request = _make_get_request({"year": "1899"})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["year"])
        assert excinfo.value.field == "year"
        assert "1900" in excinfo.value.message

    def test_year_range_matches_the_query_catalogue(self):
        """Body and query share one range, so a year cannot be legal in a query
        string and refused in a body."""
        request = _make_get_request({"year": "1900"})
        assert validate_and_parse_int_params(request, ["year"]) == [1900]

    @pytest.mark.parametrize("raw", ["20_26", "2026.0", "2e3", "٢٠٢٦"])
    def test_exotic_int_spellings_are_refused(self, raw):
        """The same parser as a catalogued query param: ``int()`` reads these,
        the API does not."""
        request = _make_get_request({"year": raw})
        with pytest.raises(InvalidQueryParam) as excinfo:
            validate_and_parse_int_params(request, ["year"])
        assert excinfo.value.field == "year"

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
        # Parsed, not passed through as a string: the document services take a
        # real date so a malformed one can't reach them.
        assert params["date"] == datetime.date(2026, 4, 10)

    def test_malformed_date_raises(self):
        """A typo'd date must not fall through to ``coerce_document_date``,
        which would silently date the document to the order's ISO week."""
        request = _make_post_request(
            {"ids": ["id1"], "model": "invoice", "date": "10.04.2026"}
        )
        with pytest.raises(CommissioningError) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.field == "date"
        assert excinfo.value.code == "bulk_documents.date_format"

    def test_non_date_typed_date_raises(self):
        request = _make_post_request(
            {"ids": ["id1"], "model": "invoice", "date": {"year": 2026}}
        )
        with pytest.raises(CommissioningError) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.field == "date"

    def test_empty_date_still_means_derive_it(self):
        """Empty / absent is the office UI's "derive the date from the order"
        signal — it must stay a pass-through, not become a 400."""
        for raw in ("", None):
            request = _make_post_request(
                {"ids": ["id1"], "model": "invoice", "date": raw}
            )
            assert validate_bulk_document_request(request)["date"] is None

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

    def test_non_string_id_raises(self):
        request = _make_post_request({"ids": ["id1", 123], "model": "invoice"})
        with pytest.raises(BulkIdsInvalid) as excinfo:
            validate_bulk_document_request(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.field == "ids"


# ---------------------------------------------------------------------------
# parse_bulk_ids
# ---------------------------------------------------------------------------
class TestParseBulkIds:
    def test_returns_string_ids(self):
        request = _make_post_request({"ids": ["id1", "2026_15_abc_KG_M"]})
        assert parse_bulk_ids(request) == ["id1", "2026_15_abc_KG_M"]

    @pytest.mark.parametrize(
        "bad_id", [123, 1.5, True, None, "", "   ", ["id1"], {"id": "id1"}]
    )
    def test_non_string_or_blank_id_raises(self, bad_id):
        request = _make_post_request({"ids": ["id1", bad_id]})
        with pytest.raises(BulkIdsInvalid) as excinfo:
            parse_bulk_ids(request)
        assert excinfo.value.http_status == status.HTTP_400_BAD_REQUEST
        assert excinfo.value.code == "bulk.ids_invalid"
        assert excinfo.value.field == "ids"

    def test_empty_list_still_raises_required_field_missing(self):
        request = _make_post_request({"ids": []})
        with pytest.raises(RequiredFieldMissing):
            parse_bulk_ids(request)

    def test_caller_can_keep_its_own_item_error(self):
        request = _make_post_request({"ids": [123]})
        with pytest.raises(BulkFinalizeIdsInvalid) as excinfo:
            parse_bulk_ids(request, invalid_item_error=BulkFinalizeIdsInvalid)
        assert excinfo.value.code == "finalize.ids_invalid"
        assert excinfo.value.field == "ids"
