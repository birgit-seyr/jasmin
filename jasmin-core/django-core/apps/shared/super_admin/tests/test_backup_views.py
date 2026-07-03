"""Tests for ``views/backup_views.py`` — super-admin backup list / trigger.

The view module reads ``BACKUP_DIR`` and ``BACKUP_SCRIPT`` from the environment
at import time into module-level ``Path`` attributes, so we monkeypatch those
attributes rather than the env vars — e.g. pointing ``BACKUP_SCRIPT`` at a
known-missing path to hit the ``500`` branch without touching the filesystem.

Direct view-function dispatch via ``APIRequestFactory + force_authenticate``,
same as the other super-admin tests.
"""

from __future__ import annotations

import pytest
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.commissioning.tests.conftest import make_step_up_token
from apps.shared.super_admin.models import SuperAdmin
from apps.shared.super_admin.views import backup_views as backup_module
from apps.shared.super_admin.views.backup_views import (
    _human_size,
    super_admin_list_backups_view,
    super_admin_trigger_backup_view,
)


@pytest.fixture
def super_admin(_tenant_schema):
    with schema_context("public"):
        admin, _ = SuperAdmin.objects.get_or_create(
            email="backup-tests@example.com",
            defaults={"first_name": "Backup", "last_name": "Tester"},
        )
    admin.is_super_admin = True
    admin.user_role = "super_admin"
    return admin


@pytest.fixture
def factory():
    return APIRequestFactory()


# ---------------------------------------------------------------------------
# List backups
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListBackups:
    def test_returns_empty_when_directory_missing(
        self, factory, super_admin, monkeypatch, tmp_path
    ):
        """Non-existent BACKUP_DIR → empty list, not 500."""
        monkeypatch.setattr(backup_module, "BACKUP_DIR", tmp_path / "does-not-exist")

        request = factory.get("/backups/")
        force_authenticate(request, user=super_admin)
        response = super_admin_list_backups_view(request)

        assert response.status_code == 200
        assert response.data == {"backups": []}

    def test_returns_files_sorted_newest_first(
        self, factory, super_admin, monkeypatch, tmp_path
    ):
        """Only ``*.sql.gz.gpg`` files are listed; sorted reverse (newest first).

        ``sorted(..., reverse=True)`` on Path objects sorts by filename, so
        timestamps are written into the filenames themselves to make the
        order deterministic without touching ``mtime``.
        """
        # Files that should appear, in expected sort order (newest first).
        (tmp_path / "jasmin-2026-05-25.sql.gz.gpg").write_bytes(b"x" * 100)
        (tmp_path / "jasmin-2026-05-24.sql.gz.gpg").write_bytes(b"y" * 2048)
        # Unrelated files in the same dir must NOT appear.
        (tmp_path / "README.txt").write_text("ignore me")
        (tmp_path / "jasmin-2026-05-24.sql.gz").write_bytes(b"unencrypted, skip")

        monkeypatch.setattr(backup_module, "BACKUP_DIR", tmp_path)

        request = factory.get("/backups/")
        force_authenticate(request, user=super_admin)
        response = super_admin_list_backups_view(request)

        assert response.status_code == 200
        names = [b["filename"] for b in response.data["backups"]]
        assert names == [
            "jasmin-2026-05-25.sql.gz.gpg",
            "jasmin-2026-05-24.sql.gz.gpg",
        ]
        # Size formatting goes through ``_human_size``; spot-check the 2KB file.
        sizes = {b["filename"]: b["size_human"] for b in response.data["backups"]}
        assert sizes["jasmin-2026-05-24.sql.gz.gpg"] == "2.0 KB"

    def test_anonymous_request_is_rejected(self, factory, _tenant_schema):
        request = factory.get("/backups/")
        response = super_admin_list_backups_view(request)
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Trigger backup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTriggerBackup:
    def test_returns_500_when_script_missing(self, factory, super_admin, monkeypatch):
        """Missing backup script → 500 with a clear operator message."""
        from pathlib import Path

        # Point the view at a guaranteed-missing path so the test doesn't
        # depend on whether the backup script is mounted into this container.
        monkeypatch.setattr(
            backup_module, "BACKUP_SCRIPT", Path("/nonexistent/backup.sh")
        )

        # Triggering a backup is step-up gated; give the super-admin a
        # fresh step-up claim so the request reaches the view body.
        request = factory.post("/backups/trigger/")
        force_authenticate(
            request, user=super_admin, token=make_step_up_token(super_admin)
        )
        response = super_admin_trigger_backup_view(request)

        assert response.status_code == 500
        assert "Backup script not found" in response.data["message"]

    def test_anonymous_request_is_rejected(self, factory, _tenant_schema):
        request = factory.post("/backups/trigger/")
        response = super_admin_trigger_backup_view(request)
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Size formatter (pure helper, no fixtures needed)
# ---------------------------------------------------------------------------


class TestHumanSize:
    @pytest.mark.parametrize(
        "size_bytes, expected",
        [
            (0, "0.0 B"),
            (512, "512.0 B"),
            (1024, "1.0 KB"),
            (1024 * 1024, "1.0 MB"),
            (1024 * 1024 * 1024, "1.0 GB"),
            (1024 * 1024 * 1024 * 1024, "1.0 TB"),
        ],
    )
    def test_formats_human_readable_sizes(self, size_bytes, expected):
        assert _human_size(size_bytes) == expected
