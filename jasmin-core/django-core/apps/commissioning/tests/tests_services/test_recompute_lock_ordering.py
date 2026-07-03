"""MOV-1: the recompute ``SELECT ... FOR UPDATE`` locks rows in deterministic
(id) order so two overlapping recomputes serialise instead of AB/BA-deadlocking.

We assert on the ACTUAL executed SQL (the row-lock query fires before the
no-content early-return), guarding that nobody drops the ``.order_by("id")``.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.commissioning.services.order_content_service import OrderContentService
from apps.commissioning.services.share_content_service import ShareContentService
from apps.commissioning.tests.factories import OrderContentFactory, ShareFactory


def _lock_sqls(captured: CaptureQueriesContext) -> list[str]:
    return [
        q["sql"] for q in captured.captured_queries if "FOR UPDATE" in q["sql"].upper()
    ]


@pytest.mark.django_db
class TestRecomputeLockOrdering:
    def test_share_recompute_locks_in_id_order(self, tenant):
        share = ShareFactory()
        with CaptureQueriesContext(connection) as ctx:
            ShareContentService().recompute_for_shares([share])
        locks = _lock_sqls(ctx)
        assert locks, "expected a SELECT ... FOR UPDATE on Share"
        assert any(
            "ORDER BY" in sql.upper() for sql in locks
        ), "the recompute lock must ORDER BY id for deterministic acquisition"

    def test_order_content_recompute_locks_in_id_order(self, tenant):
        order_content = OrderContentFactory()
        with CaptureQueriesContext(connection) as ctx:
            OrderContentService().recompute_for_order_contents([order_content])
        locks = _lock_sqls(ctx)
        assert locks, "expected a SELECT ... FOR UPDATE on OrderContent"
        assert any(
            "ORDER BY" in sql.upper() for sql in locks
        ), "the recompute lock must ORDER BY id for deterministic acquisition"
