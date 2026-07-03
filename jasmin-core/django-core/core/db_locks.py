"""Tenant-local Postgres advisory locks.

``pg_advisory_xact_lock`` is CLUSTER-wide, not schema-scoped. A raw key shared
across tenants — a member-number sequence, a document-number prefix, a
crate-totals scope — would make two tenants block on each other's lock despite
living in separate Postgres schemas. We prefix every key with the current
``connection.schema_name`` so locks stay tenant-local.

This was never a correctness bug (every follow-up query is schema-scoped, so
the numbers stay right); it is about isolation and contention under
multi-tenant concurrency. Route ALL advisory locks through this helper so a new
lock site can't forget the prefix.
"""

from __future__ import annotations

from django.db import connection


def acquire_advisory_xact_lock(key: str) -> None:
    """Take a transaction-scoped, tenant-local Postgres advisory lock.

    MUST be called inside a transaction (``transaction.atomic``); Postgres
    releases the lock automatically at transaction end — closing the cursor
    does NOT release it, so the short-lived cursor opened here is fine. The
    logical ``key`` is namespaced with the tenant schema and hashed to the
    bigint ``pg_advisory_xact_lock`` expects via ``hashtext``.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"{connection.schema_name}:{key}"],
        )
