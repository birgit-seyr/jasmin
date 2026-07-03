"""Tests for DateDocumentMixin and ArchivableMixin."""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.errors import DocumentDateRequired
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    ShareContentFactory,
)


# ---------------------------------------------------------------------------
# DateDocumentMixin   (DeliveryNoteReseller / InvoiceReseller)
#
# Used to silently auto-set ``date = today`` on save. That was a GoBD
# audit hazard for legal documents, so the model now raises
# ``DocumentDateRequired`` instead. The factory provides a stable
# default so existing tests don't need to be threaded with ``date=``.
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDateDocumentMixin:
    def test_raises_when_date_is_none(self, tenant):
        with pytest.raises(DocumentDateRequired):
            DeliveryNoteResellerFactory(date=None)

    def test_preserves_explicit_date(self, tenant):
        explicit = datetime.date(2025, 1, 1)
        dn = DeliveryNoteResellerFactory(date=explicit)
        assert dn.date == explicit

    @time_machine.travel("2026-04-15")
    def test_does_not_overwrite_on_update(self, tenant):
        explicit = datetime.date(2025, 6, 15)
        dn = DeliveryNoteResellerFactory(date=explicit)
        dn.save()  # second save should NOT overwrite
        dn.refresh_from_db()
        assert dn.date == explicit


# ---------------------------------------------------------------------------
# ArchivableMixin   (get_archive_cutoff_date, is_archived)
# Concrete model: ShareContent  (shares.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestArchivableMixin:
    @time_machine.travel("2026-06-15 12:00:00+00:00")
    def test_get_archive_cutoff_date_default(self, tenant):
        from apps.commissioning.models import ShareContent

        cutoff = ShareContent.get_archive_cutoff_date()
        expected = datetime.datetime(2026, 4, 16, 12, 0, tzinfo=datetime.UTC)
        assert cutoff == expected

    @time_machine.travel("2026-06-15 12:00:00+00:00")
    def test_get_archive_cutoff_date_custom_months(self, tenant):
        from apps.commissioning.models import ShareContent

        cutoff = ShareContent.get_archive_cutoff_date(months_back=6)
        expected = datetime.datetime(2025, 12, 17, 12, 0, tzinfo=datetime.UTC)
        assert cutoff == expected

    def test_is_archived_true_for_old_record(self, tenant):
        sc = ShareContentFactory(
            created_at=timezone.now() - datetime.timedelta(days=90),
        )
        assert sc.is_archived() is True

    def test_is_archived_false_for_recent_record(self, tenant):
        sc = ShareContentFactory(
            created_at=timezone.now() - datetime.timedelta(days=10),
        )
        assert sc.is_archived() is False

    def test_is_archived_custom_months(self, tenant):
        sc = ShareContentFactory(
            created_at=timezone.now() - datetime.timedelta(days=200),
        )
        assert sc.is_archived(months_back=6) is True
        assert sc.is_archived(months_back=12) is False
