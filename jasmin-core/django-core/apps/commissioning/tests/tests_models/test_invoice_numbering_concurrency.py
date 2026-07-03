"""Concurrent-creation tests for invoice / delivery-note numbering.

Why this exists
---------------
GoBD §147 (DE) and BAO §132 (AT) require commercial documents to carry a
gap-free, non-duplicate sequence number. The numbering implementation in
``FinalizableDocumentMixin.save_with_number_retry`` uses ``Max(number) +
1`` and relies on the unique ``(prefix, number)`` DB constraint + a
retry loop to handle races.

These tests exercise that retry path under genuine concurrency to prove:

  * No two invoices ever end up with the same ``number``.
  * After N parallel creations the assigned numbers form ``{1..N}`` with
    no gaps (so a tax auditor can grep the sequence).

We spin up real threads (not ``unittest.mock``) because the bug surface
is the interleaving of two transactions on the database — a mocked
``Max`` query wouldn't reproduce it.

Test-DB transaction model
-------------------------
``@pytest.mark.django_db(transaction=True)`` makes pytest commit between
tests (instead of wrapping each test in a single rolled-back
transaction). This is required because:

  1. Worker threads each open their own DB connection — they can't see
     uncommitted writes from the main test transaction.
  2. The retry loop reacts to ``IntegrityError`` from a real commit, so
     the constraint must actually fire at the DB layer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pytest
from django.db import connection, connections

from apps.commissioning.models import InvoiceReseller
from apps.commissioning.tests.factories import ResellerFactory


def _create_one_invoice(reseller_id: str, schema_name: str) -> int:
    """Worker body: open a fresh DB connection in the right tenant schema,
    create one finalized-bound invoice, return its assigned ``number``.

    A fresh connection is needed because Django's per-thread connection
    pool gives each thread its own connection — but we still have to
    re-set the schema on that connection (the tenant context is per-
    connection, not per-thread). Closes the thread-local connection in
    a finally block so pytest-django's post-test flush isn't blocked.
    """
    from django_tenants.utils import schema_context

    # Close any thread-local connection inherited from the test fixture so
    # we get a fresh one inside the schema_context block.
    connection.close()
    try:
        with schema_context(schema_name):
            invoice = InvoiceReseller(
                reseller_id=reseller_id,
                date=date(2026, 1, 15),
            )
            invoice.save()  # triggers save_with_number_retry → numbering
            return invoice.number
    finally:
        # Without this, the thread's connection lingers and the
        # subsequent pytest flush fails with "Database test_jasmin
        # couldn't be flushed" because the thread still holds locks.
        for conn in connections.all():
            conn.close()


@pytest.mark.django_db(transaction=True)
class TestInvoiceNumberingConcurrency:
    """Spin up N parallel invoice creations and verify the sequence.

    The ``test_pytest`` schema is shared across pytest invocations, so
    each test starts by truncating ``InvoiceReseller``. Without this, a
    prior run's invoices would shift the expected ``[1..N]`` sequence.
    Bulk delete is safe here because none of these test invoices ever
    finalize (``FinalizedProtectedQuerySet`` only blocks when finalized
    rows are in the queryset).
    """

    @pytest.fixture(autouse=True)
    def _hermetic_invoice_table(self, tenant):
        InvoiceReseller.objects.all().delete()

    def test_no_duplicates_no_gaps_under_concurrent_create(self, tenant):
        reseller = ResellerFactory()
        schema_name = connection.schema_name

        n_workers = 25
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [
                pool.submit(_create_one_invoice, str(reseller.id), schema_name)
                for _ in range(n_workers)
            ]
            numbers = sorted(f.result() for f in as_completed(futures))

        # No duplicates: every assigned number is unique.
        assert (
            len(set(numbers)) == n_workers
        ), f"Duplicate invoice numbers under concurrency: {numbers}"
        # No gaps: the sequence is exactly {1, 2, ..., N}.
        assert numbers == list(
            range(1, n_workers + 1)
        ), f"Gap in invoice number sequence: {numbers}"

    def test_serial_baseline_still_works(self, tenant):
        """Sanity check: the same numbering path also works without
        threads. Catches regressions where a concurrency fix accidentally
        broke the single-writer case."""
        reseller = ResellerFactory()
        numbers: list[int] = []
        for _ in range(5):
            invoice = InvoiceReseller(reseller=reseller, date=date(2026, 1, 15))
            invoice.save()
            numbers.append(invoice.number)
        assert numbers == [1, 2, 3, 4, 5]
