"""Concurrent-creation tests for ``Member.member_number``.

Why this exists
---------------
``Member.member_number`` is a per-tenant sequential ID that office
staff and the member themselves rely on (it's the public-facing
member reference printed on invoices and visible in the member list).
Like the document numbering covered by
``test_invoice_numbering_concurrency.py``, it MUST be:

  * unique (enforced at the DB layer by ``unique=True``), and
  * gap-free under realistic concurrency (so member #5 isn't followed
    by member #7 because of a wasted retry).

The race-conditions audit pass (see ``docs/code/engineering-audit-playbook.md``,
Pass #7) caught that the previous implementation chained
``select_for_update().aggregate(...)``, which Postgres silently
ignores. The fix replaced it with the canonical
``pg_advisory_xact_lock`` pattern used by
``FinalizableDocumentMixin.save_with_number_retry``. This test
exercises the new path under genuine concurrency.

Test-DB transaction model
-------------------------
``@pytest.mark.django_db(transaction=True)`` makes pytest commit
between tests instead of wrapping each test in a rolled-back
transaction. Required because:

  1. Worker threads each open their own DB connection — they can't
     see uncommitted writes from the main test transaction.
  2. The advisory lock only blocks across transactions when it can
     observe committed state on both sides.

Mirror of ``test_invoice_numbering_concurrency.py`` — keep the two
in sync if the numbering machinery evolves.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from django.db import connection, connections

from apps.commissioning.models import Member


def _create_one_member_and_generate_number(schema_name: str, email: str) -> int:
    """Worker body: open a fresh DB connection in the right tenant schema,
    create a Member without a number, call ``_generate_member_number``,
    return the assigned number.

    A fresh connection is needed because Django's per-thread connection
    pool gives each thread its own connection — but the tenant context
    is per-connection, not per-thread, so we re-set the schema inside
    the worker. Closes the thread-local connection in a finally block
    so pytest-django's post-test flush isn't blocked by lingering locks.
    """
    from django_tenants.utils import schema_context

    # Close any thread-local connection inherited from the test fixture so
    # we get a fresh one inside the schema_context block.
    connection.close()
    try:
        with schema_context(schema_name):
            member = Member.objects.create(
                first_name="Concur",
                last_name=f"Test-{email}",
                email=email,
                is_active=True,
            )
            # Path under test: the advisory-locked numbering primitive.
            member._generate_member_number()
            return member.member_number
    finally:
        for conn in connections.all():
            conn.close()


@pytest.mark.django_db(transaction=True)
class TestMemberNumberingConcurrency:
    """Spin up N parallel Member creations and verify the sequence.

    The ``test_pytest`` schema is shared across pytest invocations, so
    each test starts by deleting Members. Cascades drop any
    Subscription / CoopShare rows attached, which is fine —
    this test never creates any.
    """

    @pytest.fixture(autouse=True)
    def _hermetic_member_table(self, tenant):
        Member.objects.all().delete()

    def test_no_duplicates_no_gaps_under_concurrent_create(self, tenant):
        schema_name = connection.schema_name

        n_workers = 25
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [
                pool.submit(
                    _create_one_member_and_generate_number,
                    schema_name,
                    f"concur-{i}@example.com",
                )
                for i in range(n_workers)
            ]
            numbers = sorted(f.result() for f in as_completed(futures))

        # No duplicates: every assigned number is unique.
        assert (
            len(set(numbers)) == n_workers
        ), f"Duplicate member_numbers under concurrency: {numbers}"
        # No gaps: the sequence is exactly {1, 2, ..., N}.
        assert numbers == list(
            range(1, n_workers + 1)
        ), f"Gap in member_number sequence: {numbers}"

    def test_serial_baseline_still_works(self, tenant):
        """Sanity check: the same numbering path also works without
        threads. Catches regressions where a concurrency fix accidentally
        broke the single-writer case."""
        numbers: list[int] = []
        for i in range(5):
            member = Member.objects.create(
                first_name="Serial",
                last_name=f"Test-{i}",
                email=f"serial-{i}@example.com",
                is_active=True,
            )
            member._generate_member_number()
            numbers.append(member.member_number)
        assert numbers == [1, 2, 3, 4, 5]
