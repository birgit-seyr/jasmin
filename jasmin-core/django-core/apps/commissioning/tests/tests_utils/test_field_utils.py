"""Tests for apps.commissioning.utils.field_utils."""

from __future__ import annotations

import pytest

from apps.commissioning.utils.field_utils import (
    build_storage_fields,
    clean_storage_fields,
    extract_selected_storage_id,
    extract_storage_fields_from_data,
)


# ---------------------------------------------------------------------------
# extract_selected_storage_id  (pure — no DB)
# ---------------------------------------------------------------------------
class TestExtractSelectedStorageId:
    def test_returns_selected_id(self):
        data = {"storage_abc123": True, "storage_xyz789": False}
        assert extract_selected_storage_id(data) == "abc123"

    def test_returns_none_when_no_storage_selected(self):
        data = {"storage_abc": False, "storage_xyz": False}
        assert extract_selected_storage_id(data) is None

    def test_returns_none_for_empty_dict(self):
        assert extract_selected_storage_id({}) is None

    def test_ignores_bare_prefix(self):
        data = {"storage_": True, "storage_abc": False}
        assert extract_selected_storage_id(data) is None

    def test_only_matches_exact_true(self):
        """Only value `True` (not truthy strings/ints) should match."""
        data = {"storage_abc": 1, "storage_xyz": "yes"}
        assert extract_selected_storage_id(data) is None

    def test_returns_first_true_storage(self):
        data = {"storage_first": True, "storage_second": True}
        result = extract_selected_storage_id(data)
        assert result in ("first", "second")

    def test_ignores_non_storage_keys(self):
        data = {"name": "Test", "amount": 10, "storage_abc": True}
        assert extract_selected_storage_id(data) == "abc"


# ---------------------------------------------------------------------------
# clean_storage_fields  (pure — no DB)
# ---------------------------------------------------------------------------
class TestCleanStorageFields:
    def test_removes_all_storage_keys(self):
        data = {"name": "Test", "storage_abc": True, "storage_xyz": False}
        clean_storage_fields(data)
        assert data == {"name": "Test"}

    def test_leaves_non_storage_keys(self):
        data = {"name": "Test", "amount": 42}
        clean_storage_fields(data)
        assert data == {"name": "Test", "amount": 42}

    def test_handles_empty_dict(self):
        data = {}
        clean_storage_fields(data)
        assert data == {}

    def test_handles_no_storage_keys(self):
        data = {"foo": 1, "bar": 2}
        clean_storage_fields(data)
        assert data == {"foo": 1, "bar": 2}

    def test_removes_all_when_only_storage_keys(self):
        data = {"storage_a": True, "storage_b": False}
        clean_storage_fields(data)
        assert data == {}


# ---------------------------------------------------------------------------
# build_storage_fields  (needs DB — queries Storage model)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBuildStorageFields:
    @pytest.fixture(autouse=True)
    def _clear_seeded_storages(self, tenant):
        # commissioning/migrations/0004 seeds "Kurz" + "Lang" into every
        # tenant schema. These tests assert exact contents, so wipe the
        # seed before each case (rolled back with the test transaction).
        from apps.commissioning.models import Storage

        Storage.objects.all().delete()

    def test_builds_fields_for_active_storages(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        s1 = StorageFactory(is_active=True)
        s2 = StorageFactory(is_active=True)
        StorageFactory(is_active=False)  # inactive — should be excluded

        result = build_storage_fields()
        assert f"storage_{s1.id}" in result
        assert f"storage_{s2.id}" in result
        assert all(v is False for v in result.values())

    def test_entry_with_storage_sets_true(self, tenant):
        from types import SimpleNamespace

        from apps.commissioning.tests.factories import StorageFactory

        s1 = StorageFactory(is_active=True)
        s2 = StorageFactory(is_active=True)

        entry = SimpleNamespace(storage_id=s1.id)
        result = build_storage_fields(entry)
        assert result[f"storage_{s1.id}"] is True
        assert result[f"storage_{s2.id}"] is False

    def test_entry_none_all_false(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        StorageFactory(is_active=True)
        result = build_storage_fields(None)
        assert all(v is False for v in result.values())

    def test_no_active_storages_returns_empty(self, tenant):
        result = build_storage_fields()
        assert result == {}


# ---------------------------------------------------------------------------
# extract_storage_fields_from_data  (needs DB — queries Storage model)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExtractStorageFieldsFromData:
    def test_extracts_matching_storage_fields(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        s1 = StorageFactory(is_active=True)
        s2 = StorageFactory(is_active=True)

        data = {
            "name": "Test",
            f"storage_{s1.id}": True,
            f"storage_{s2.id}": False,
            "storage_nonexistent": True,
        }
        result = extract_storage_fields_from_data(data)
        assert result == {f"storage_{s1.id}": True, f"storage_{s2.id}": False}

    def test_ignores_non_storage_fields(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        StorageFactory(is_active=True)
        data = {"name": "Test", "amount": 10}
        result = extract_storage_fields_from_data(data)
        assert result == {}

    def test_ignores_inactive_storage_ids(self, tenant):
        from apps.commissioning.tests.factories import StorageFactory

        inactive = StorageFactory(is_active=False)
        data = {f"storage_{inactive.id}": True}
        result = extract_storage_fields_from_data(data)
        assert result == {}
