"""Tests for apps.commissioning.models.base — JasminModel."""

from __future__ import annotations

import pytest

from apps.commissioning.constants import ID_LENGTH, JASMIN_ID_ALPHABET
from apps.commissioning.models.base import generate_jasmin_id


# ---------------------------------------------------------------------------
# generate_jasmin_id  (pure — no DB)
# ---------------------------------------------------------------------------
class TestGenerateJasminId:
    def test_returns_correct_length(self):
        assert len(generate_jasmin_id()) == ID_LENGTH

    def test_uses_only_allowed_characters(self):
        for _ in range(50):
            tid = generate_jasmin_id()
            for ch in tid:
                assert ch in JASMIN_ID_ALPHABET, f"Unexpected char '{ch}' in {tid}"

    def test_generates_unique_ids(self):
        ids = {generate_jasmin_id() for _ in range(200)}
        assert len(ids) == 200


# ---------------------------------------------------------------------------
# JasminModel.get_display_id  (needs DB to create an instance)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJasminModelGetDisplayId:
    def test_formats_as_uppercase_dashed(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        obj = StorageFactory()
        display = obj.get_display_id()
        assert display == "-".join(
            obj.id.upper()[i : i + 3] for i in range(0, len(obj.id), 3)
        )

    def test_empty_id_returns_empty_string(self):
        from apps.commissioning.models.base import JasminModel

        class FakeModel:
            id = ""
            get_display_id = JasminModel.get_display_id

        assert FakeModel().get_display_id() == ""
