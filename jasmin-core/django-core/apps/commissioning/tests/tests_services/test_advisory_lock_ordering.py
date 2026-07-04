"""TXN-1: advisory locks for multi-entity stock operations must be acquired in
one canonical (sorted) order.

The ``current_balance:*`` lock is transaction-scoped and held to the outer
commit, so two concurrent operations over an overlapping entity set deadlock
(AB/BA) unless every acquirer takes the shared locks in the same order. These
tests pin that ordering at the two chokepoints:

* ``CurrentBalanceService.acquire_locks_for_entities`` — the up-front pre-acquire
  used by the bulk stock views.
* ``SnapshotService.cascade_for_movements`` — the backstop for every list-cascade
  caller (recompute, documentation, ...).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.commissioning.services.current_balance_service import CurrentBalanceService
from apps.commissioning.services.snapshot_service import SnapshotService
from apps.commissioning.services.theoretical_objects import (
    recalculate_actual_corrections,
)


def test_acquire_locks_for_entities_sorted_and_deduped():
    entity_keys = [
        ("art2", "KG", "M", "s1"),
        ("art1", "KG", "M", "s1"),
        ("art1", None, None, None),
        ("art2", "KG", "M", "s1"),  # duplicate — must collapse
        ("art1", "KG", "L", None),
    ]

    with patch("core.db_locks.acquire_advisory_xact_lock") as mock_lock:
        CurrentBalanceService.acquire_locks_for_entities(entity_keys)

    acquired = [call.args[0] for call in mock_lock.call_args_list]
    assert acquired == [
        "current_balance:art1:::",
        "current_balance:art1:KG:L:",
        "current_balance:art1:KG:M:s1",
        "current_balance:art2:KG:M:s1",
    ]


def _movement(share_article_id, unit, size, storage_id):
    return SimpleNamespace(
        share_article_id=share_article_id,
        unit=unit,
        size=size,
        storage_id=storage_id,
        date=datetime.datetime(2026, 4, 6, 12, tzinfo=datetime.UTC),
    )


def test_cascade_for_movements_processes_entities_sorted():
    # Deliberately unsorted, with a None-bearing entity and a duplicate.
    movements = [
        _movement("art2", "KG", "M", "s1"),
        _movement("art1", "KG", "M", "s1"),
        _movement("art1", None, None, None),
        _movement("art2", "KG", "M", "s1"),  # same entity as first
    ]

    seen: list[tuple] = []

    def _record(*, share_article_id, unit, size, storage_id, after_date):
        seen.append((share_article_id, unit, size, storage_id))
        return 0

    with patch.object(
        SnapshotService, "cascade_future_inventories", side_effect=_record
    ):
        SnapshotService.cascade_for_movements(movements)

    # One cascade per unique entity, in canonical (None-coerced) sorted order.
    assert seen == [
        ("art1", None, None, None),
        ("art1", "KG", "M", "s1"),
        ("art2", "KG", "M", "s1"),
    ]


def _correction_ref(share_article_id, unit, size, storage_id, movement_type):
    return SimpleNamespace(
        share_article_id=share_article_id,
        unit=unit,
        size=size,
        storage_id=storage_id,
        movement_type=movement_type,
    )


@pytest.mark.django_db
def test_recalculate_actual_corrections_locks_theoretical_sum_sorted(tenant):
    """goods-flow audit #6: ``recalculate_actual_corrections`` must serialize with
    the count-entry path by taking the SAME ``theoretical_sum:*`` xact lock, once
    per dimension, in canonical (None-coerced) sorted order — so a recompute and a
    count entry can't net against different theoretical sets (write-skew), and two
    recomputes can't deadlock (AB/BA). The lock key is byte-for-byte the one
    ``GenericDocumentationService._sum_theoretical`` builds."""
    # Deliberately unsorted, with a None-bearing dimension and a duplicate.
    refs = [
        _correction_ref("art2", "KG", "M", "s1", "HARVEST"),
        _correction_ref("art1", "KG", "M", "s1", "HARVEST"),
        _correction_ref("art1", None, None, None, "HARVEST"),
        _correction_ref("art2", "KG", "M", "s1", "HARVEST"),  # duplicate — collapses
    ]

    with patch("core.db_locks.acquire_advisory_xact_lock") as mock_lock:
        recalculate_actual_corrections(refs)

    acquired = [call.args[0] for call in mock_lock.call_args_list]
    assert acquired == [
        "theoretical_sum:art1::::HARVEST",
        "theoretical_sum:art1:KG:M:s1:HARVEST",
        "theoretical_sum:art2:KG:M:s1:HARVEST",
    ]
