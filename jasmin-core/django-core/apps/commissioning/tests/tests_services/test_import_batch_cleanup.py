"""The ``cleanup_stale_import_batches`` Huey periodic task.

Abandoned upload/preview rows are swept once they pass the retention
window. ``APPLIED`` rows never are, at any age: they record which
membership changes actually happened, so they are the audit trail.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.models import ShareImportBatch
from apps.commissioning.tasks import cleanup_stale_import_batches
from apps.shared.retention import IMPORT_BATCH_RETENTION_DAYS

# The sweep measures its cutoff against the real clock, so the fixtures are
# positioned relative to it rather than at a fixed date.
_STALE = IMPORT_BATCH_RETENTION_DAYS + 1
_FRESH = IMPORT_BATCH_RETENTION_DAYS - 1


def _batch(status: str, *, checksum: str, age_days: int) -> ShareImportBatch:
    return ShareImportBatch.objects.create(
        year=timezone.now().year,
        delivery_week=15,
        file_checksum=checksum * 64,
        original_filename=f"{checksum}.csv",
        status=status,
        created_at=timezone.now() - datetime.timedelta(days=age_days),
    )


@pytest.mark.django_db
class TestCleanupStaleImportBatches:
    def test_only_abandoned_rows_past_the_window_are_pruned(self, tenant):
        _batch(ShareImportBatch.STATUS_FAILED, checksum="a", age_days=_STALE)
        _batch(ShareImportBatch.STATUS_PREVIEW_READY, checksum="b", age_days=_STALE)
        _batch(ShareImportBatch.STATUS_FAILED, checksum="c", age_days=_FRESH)
        _batch(ShareImportBatch.STATUS_APPLIED, checksum="d", age_days=_STALE)

        cleanup_stale_import_batches.call_local()

        survivors = set(
            ShareImportBatch.objects.values_list("file_checksum", flat=True)
        )
        assert survivors == {"c" * 64, "d" * 64}

    def test_an_applied_batch_survives_however_old(self, tenant):
        _batch(
            ShareImportBatch.STATUS_APPLIED,
            checksum="e",
            age_days=IMPORT_BATCH_RETENTION_DAYS * 10,
        )

        cleanup_stale_import_batches.call_local()

        assert ShareImportBatch.objects.filter(
            status=ShareImportBatch.STATUS_APPLIED
        ).exists()

    @pytest.mark.parametrize(
        "kept_status",
        [
            ShareImportBatch.STATUS_UPLOADED,
            ShareImportBatch.STATUS_VALIDATED,
            ShareImportBatch.STATUS_SUPERSEDED,
        ],
    )
    def test_a_status_outside_the_deletable_set_survives(self, tenant, kept_status):
        _batch(kept_status, checksum="f", age_days=_STALE)

        cleanup_stale_import_batches.call_local()

        assert ShareImportBatch.objects.filter(status=kept_status).exists()
