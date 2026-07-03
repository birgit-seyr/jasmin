"""Tests for tenant-local Postgres advisory locks (``core.db_locks``).

``pg_advisory_xact_lock`` is cluster-wide, so the key MUST be prefixed with the
tenant schema or two tenants block on each other. These lock the contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.db import transaction

from core.db_locks import acquire_advisory_xact_lock


def test_advisory_lock_key_is_prefixed_with_schema():
    """The executed key is ``<schema>:<logical key>`` — drop the prefix and
    this fails, which is the whole point of the namespacing fix."""
    mock_conn = MagicMock()
    mock_conn.schema_name = "tenant_xyz"
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value

    with patch("core.db_locks.connection", mock_conn):
        acquire_advisory_xact_lock("member_number:sequence")

    mock_cursor.execute.assert_called_once_with(
        "SELECT pg_advisory_xact_lock(hashtext(%s))",
        ["tenant_xyz:member_number:sequence"],
    )


@pytest.mark.django_db
def test_real_lock_executes_within_transaction(tenant):
    """Smoke test against a real tenant connection: ``connection.schema_name``
    exists and the hashtext SQL is valid (no exception)."""
    with transaction.atomic():
        acquire_advisory_xact_lock("sec_be_6_smoke")
