"""Query-count lock for StorageFieldsMixin.

The mixin adds a dynamic ``storage_<id>`` boolean per active storage to each
serialized row. It must fetch the active-storage set ONCE per response, not
once per row — the previous ``build_storage_fields`` → ``_get_active_storages``
call fired a Storage query for every row in ``to_representation``.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.serializers.documentation_serializer import HarvestSerializer
from apps.commissioning.tests.factories import HarvestFactory, StorageFactory


@pytest.mark.django_db
class TestStorageFieldsQueryCount:
    def _storage_selects(self, ctx) -> int:
        return sum(
            1
            for q in ctx.captured_queries
            if '"commissioning_storage"' in q["sql"].lower()
            and q["sql"].lstrip().lower().startswith("select")
        )

    def test_active_storage_fetched_once_per_response(self, tenant):
        # A couple of active storages so the dynamic field set is non-trivial.
        StorageFactory(is_active=True)
        StorageFactory(is_active=True)

        few = HarvestFactory.create_batch(2)
        with CaptureQueriesContext(connection) as ctx_small:
            _ = HarvestSerializer(few, many=True).data
        small = self._storage_selects(ctx_small)

        many = HarvestFactory.create_batch(6)
        with CaptureQueriesContext(connection) as ctx_large:
            _ = HarvestSerializer(many, many=True).data
        large = self._storage_selects(ctx_large)

        assert large - small <= 1, (
            "active Storage re-queried per row (PERF-9 regression): "
            f"2 rows -> {small} SELECTs, 6 rows -> {large} SELECTs"
        )
        assert large <= 2, f"expected active Storage fetched ~once, got {large}"
