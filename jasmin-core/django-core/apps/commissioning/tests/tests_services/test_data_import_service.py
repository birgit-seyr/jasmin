"""Tests for the CSV → model import service.

The service is pure logic — no HTTP. Most of its bulk is small helpers
(``_normalize_cell``, ``_parse_bool_cell``, ``_decode_csv``, ...) that
together drive a single orchestrator (``import_rows_from_csv``). The
orchestrator's most important property is **per-row isolation**: one bad
row never aborts the import.

Coverage targets the gaps from the §1 test-coverage-priorities audit
(34% → raise). Crate is the simplest registered model (just ``name`` +
``number`` required) so it's used for the round-trip happy paths.
"""

from __future__ import annotations

import pytest

from apps.commissioning.errors import DataImportInvalid
from apps.commissioning.models import Crate
from apps.commissioning.serializers import CrateSerializer, ShareArticleSerializer
from apps.commissioning.services.data_import import (
    DataImportResult,
    _collect_bool_fields,
    _decode_csv,
    _flatten_drf_errors,
    _normalize_cell,
    _parse_bool_cell,
    _row_to_payload,
    _split_template_rows,
    get_serializer_for_model,
    import_rows_from_csv,
)

# ---------------------------------------------------------------------------
# Pure helpers — no DB, no fixtures needed
# ---------------------------------------------------------------------------


class TestNormalizeCell:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("none", None),
            ("NULL", None),
            ("NaN", None),
            ("hello", "hello"),
            ("  trimmed  ", "trimmed"),
            ("0", "0"),  # zero is NOT empty
            ("false", "false"),  # bool sentinel stays — handled separately
        ],
    )
    def test_empty_sentinels_become_none(self, value, expected):
        assert _normalize_cell(value) == expected


class TestParseBoolCell:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("ja", True),
            ("wahr", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("nein", False),
            ("falsch", False),
        ],
    )
    def test_canonical_values_coerce(self, value, expected):
        assert _parse_bool_cell(value) is expected

    def test_unknown_values_pass_through(self):
        """Service hands non-canonical strings to DRF, which rejects them
        per-row instead of crashing the whole import."""
        assert _parse_bool_cell("maybe") == "maybe"
        assert _parse_bool_cell("2") == "2"


class TestRowToPayload:
    def test_builds_payload_from_headers_and_cells(self):
        payload = _row_to_payload(
            headers=["name", "number"],
            cells=["EuroBox", "42"],
            bool_fields=set(),
        )
        assert payload == {"name": "EuroBox", "number": "42"}

    def test_empty_header_columns_are_skipped(self):
        """Trailing/blank headers in the template (often left over from
        spreadsheets) must not pollute the payload with empty keys."""
        payload = _row_to_payload(
            headers=["name", "", "number"],
            cells=["EuroBox", "ignored", "42"],
            bool_fields=set(),
        )
        assert payload == {"name": "EuroBox", "number": "42"}

    def test_empty_cell_sentinels_dropped(self):
        payload = _row_to_payload(
            headers=["name", "short_name"],
            cells=["EuroBox", "  null  "],
            bool_fields=set(),
        )
        assert payload == {"name": "EuroBox"}

    def test_bool_fields_get_coerced(self):
        payload = _row_to_payload(
            headers=["name", "is_active"],
            cells=["X", "ja"],
            bool_fields={"is_active"},
        )
        assert payload == {"name": "X", "is_active": True}

    def test_non_bool_fields_stay_strings(self):
        payload = _row_to_payload(
            headers=["name", "tag"],
            cells=["X", "true"],
            bool_fields=set(),
        )
        assert payload == {"name": "X", "tag": "true"}


class TestCollectBoolFields:
    def test_returns_boolean_field_names(self):
        """``CrateSerializer.Meta = {fields: __all__}`` exposes
        ``is_active`` (Crate model has it as ``BooleanField``)."""
        names = _collect_bool_fields(CrateSerializer)
        assert "is_active" in names
        assert "name" not in names

    def test_other_serializers_have_their_own_bool_set(self):
        """Sanity-check: ShareArticleSerializer carries its own bool fields,
        not Crate's. Avoids accidental cross-contamination of the
        bool-field cache during refactors."""
        sa_bools = _collect_bool_fields(ShareArticleSerializer)
        # ShareArticle has is_active, is_purchased, is_sold_to_resellers,
        # for_markets — at least one must be present.
        assert sa_bools  # non-empty
        assert "name" not in sa_bools


class TestFlattenDrfErrors:
    def test_string(self):
        assert _flatten_drf_errors("simple") == "simple"

    def test_list_of_strings(self):
        assert _flatten_drf_errors(["a", "b"]) == "a, b"

    def test_dict_of_lists(self):
        out = _flatten_drf_errors({"name": ["required"], "number": ["int"]})
        # Order isn't guaranteed in older Pythons but dicts preserve
        # insertion order since 3.7 — assert both segments present.
        assert "name: required" in out
        assert "number: int" in out

    def test_nested_dict(self):
        out = _flatten_drf_errors({"nested": {"key": ["bad"]}})
        assert "key: bad" in out


class TestDecodeCsv:
    def test_utf8(self):
        assert _decode_csv(b"hello") == "hello"

    def test_utf8_with_bom(self):
        """Excel exports often start with a UTF-8 BOM. The ``utf-8-sig``
        codec consumes it so the first column header doesn't end up with
        a leading ``\\ufeff``."""
        bom = b"\xef\xbb\xbf"
        decoded = _decode_csv(bom + b"name,number")
        assert decoded == "name,number"

    def test_latin1_fallback(self):
        """Older Excel exports default to Latin-1. The fallback lets us
        accept those without forcing the user to re-export."""
        # \xe4 is "ä" in Latin-1, invalid as standalone UTF-8 byte.
        decoded = _decode_csv(b"M\xe4rchen")
        assert decoded == "Märchen"


class TestSplitTemplateRows:
    def test_three_row_template_uses_row1_as_headers(self):
        """The downloadable template is title / dataIndex / type-hint, then
        data rows. ``_split_template_rows`` must pick row 1 (the dataIndex
        row) as the schema and skip the type-hint row at index 2."""
        all_rows = [
            ["Name", "Number"],  # row 0: human title
            ["name", "number"],  # row 1: dataIndex (the schema)
            ["text", "int"],  # row 2: type hint
            ["EuroBox", "42"],  # data row
        ]
        headers, data_rows, first_data_row_number = _split_template_rows(all_rows)
        assert headers == ["name", "number"]
        assert data_rows == [["EuroBox", "42"]]
        assert first_data_row_number == 4

    def test_two_row_hand_rolled_csv_uses_row0_as_headers(self):
        all_rows = [
            ["name", "number"],
            ["EuroBox", "42"],
        ]
        headers, data_rows, first_data_row_number = _split_template_rows(all_rows)
        assert headers == ["name", "number"]
        assert data_rows == [["EuroBox", "42"]]
        assert first_data_row_number == 2


class TestGetSerializerForModel:
    def test_known_model(self):
        assert get_serializer_for_model("crate") is CrateSerializer

    def test_unknown_model_raises(self):
        with pytest.raises(DataImportInvalid) as exc_info:
            get_serializer_for_model("not-a-model")
        assert "not-a-model" in str(exc_info.value)
        assert "Allowed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DataImportResult — small dataclass, easy locks
# ---------------------------------------------------------------------------


class TestDataImportResult:
    def test_counts_default_to_zero(self):
        r = DataImportResult(model_name="crate")
        assert r.successful == 0
        assert r.failed == 0
        assert r.total_rows == 0

    def test_to_dict_shape(self):
        r = DataImportResult(model_name="crate")
        r.results.append({"row": 2, "id": "abc"})
        r.errors.append({"row": 3, "error": "boom", "data": {}})
        out = r.to_dict()
        assert out == {
            "model_name": "crate",
            "total_rows": 2,
            "successful": 1,
            "failed": 1,
            "results": [{"row": 2, "id": "abc"}],
            "errors": [{"row": 3, "error": "boom", "data": {}}],
        }


# ---------------------------------------------------------------------------
# import_rows_from_csv — the orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportRowsFromCsv:
    def test_two_row_csv_creates_rows(self, tenant):
        """Happy path: hand-rolled 2-row CSV → one Crate created."""
        csv_bytes = b"name,number\nEuroBox,42\n"
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.successful == 1
        assert result.failed == 0
        assert Crate.objects.filter(name="EuroBox").exists()
        # Row number for the data row should be 2 in the 2-row variant
        # (header row + 1).
        assert result.results[0]["row"] == 2

    def test_three_row_template_skips_type_hint_row(self, tenant):
        """The downloadable template's type-hint row (row 2) is NOT a
        data row — the import must skip it, not try to create a crate
        named ``text``."""
        csv_bytes = (
            b"Name,Number\n"  # row 0: titles
            b"name,number\n"  # row 1: dataIndex
            b"text,int\n"  # row 2: type hints
            b"EuroBox,42\n"  # row 3: first data row → row_number 4
        )
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.successful == 1
        assert result.failed == 0
        assert result.results[0]["row"] == 4
        # Did NOT create a crate named "text" from the type-hint row.
        assert not Crate.objects.filter(name="text").exists()

    def test_per_row_isolation_one_bad_row_does_not_abort(self, tenant):
        """One row failing validation must not block the others — the
        whole point of the per-row try/except in the orchestrator.

        Uses the **template format** (3 preamble rows + data) because
        any CSV with ``len(all_rows) >= 3`` is interpreted that way —
        otherwise a 4-row hand-rolled file would parse row 1 as the
        dataIndex schema and the test would assert against garbage.
        """
        csv_bytes = (
            b"Name,Number\n"  # row 0: human title
            b"name,number\n"  # row 1: dataIndex (schema)
            b"text,int\n"  # row 2: type hint
            b"GoodOne,1\n"  # row 3 → row_number 4 (OK)
            b",2\n"  # row 4 → row_number 5 (missing ``name`` → error)
            b"GoodTwo,3\n"  # row 5 → row_number 6 (OK)
        )
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.successful == 2
        assert result.failed == 1
        assert Crate.objects.filter(name__in=["GoodOne", "GoodTwo"]).count() == 2
        # The bad row's payload + row number is reported back so the
        # frontend can show it in an error table. Bad row is at template
        # position 4 (0-indexed) → 1-indexed row_number 5.
        assert result.errors[0]["row"] == 5
        assert "data" in result.errors[0]

    def test_empty_payload_rows_silently_skipped(self, tenant):
        """A data row whose cells all normalize to ``None`` (Excel "none" /
        "null" placeholders) yields an empty payload → the orchestrator's
        ``if not payload: continue`` branch. Must NOT become an error row.

        Note: truly-blank lines (``" , "``) get filtered out earlier by
        the ``any(cell.strip()...)`` guard before splitting — they never
        reach the data-row loop. This test exercises the loop's own skip.
        """
        csv_bytes = (
            b"Name,Number\n"  # row 0: title
            b"name,number\n"  # row 1: dataIndex
            b"text,int\n"  # row 2: type hint
            b"GoodOne,1\n"  # row 3: OK
            b"none,null\n"  # row 4: both sentinels → empty payload → skip
            b"GoodTwo,2\n"  # row 5: OK
        )
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.failed == 0
        assert result.successful == 2
        assert Crate.objects.filter(name__in=["GoodOne", "GoodTwo"]).count() == 2

    def test_empty_file_raises_data_import_error(self, tenant):
        """No data row at all → DataImportInvalid (400 via the global
        handler)."""
        with pytest.raises(DataImportInvalid) as exc_info:
            import_rows_from_csv("crate", b"name,number\n")
        assert "at least a header row and one data row" in str(exc_info.value)

    def test_unknown_model_raises(self, tenant):
        with pytest.raises(DataImportInvalid):
            import_rows_from_csv("not-a-real-model", b"name\nx\n")

    def test_bool_field_coerced_from_german_truthy(self, tenant):
        """Crate.is_active is a BooleanField. The German ``ja`` must
        coerce to True instead of failing serializer validation."""
        csv_bytes = b"name,number,is_active\nActiveCrate,7,ja\n"
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.failed == 0
        crate = Crate.objects.get(name="ActiveCrate")
        assert crate.is_active is True

    def test_latin1_csv_decodes(self, tenant):
        """Excel-default Latin-1 exports must round-trip — German tenants
        upload these regularly."""
        # "Märchenkiste" in Latin-1.
        csv_bytes = b"name,number\nM\xe4rchenkiste,5\n"
        result = import_rows_from_csv("crate", csv_bytes)

        assert result.successful == 1
        assert Crate.objects.filter(name="Märchenkiste").exists()
