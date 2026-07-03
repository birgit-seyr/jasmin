"""Tests for ``apps.commissioning.services.invoice_reminder``.

The function was extracted out of
``BulkSendInvoiceRemindersViaEmailView.post`` so the Huey task can
call it without going through HTTP. The view-level test now only
checks the 202+job contract; the consolidation + SMTP-mocking
assertions live here, where they belong.

Two contracts pinned down:
  1. ONE consolidated email per reseller, regardless of how many
     ticked invoices belong to that reseller (the whole point of
     the grouped-by-reseller reshape).
  2. ``related_object_type="reseller"`` on the EmailLog row, since
     the single email covers multiple invoices and singling one
     out would be misleading.
"""

from __future__ import annotations

from unittest import mock

import pytest

from apps.commissioning.services.invoice_reminder import (
    bulk_send_invoice_reminders,
)
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OrderFactory,
    ResellerFactory,
)


@pytest.mark.django_db
class TestBulkSendInvoiceReminders:
    def test_one_reseller_one_invoice_sends_one_email(self, tenant):
        """Baseline: one ticked order, one finalized invoice, one
        reseller with an email → one consolidated send. Confirms the
        ``EmailService.send_email`` call uses ``autospec=True``-safe
        instance-method binding (P0-1 regression).
        """
        reseller = ResellerFactory(invoice_email="reseller@example.org")
        order = OrderFactory(reseller=reseller)
        DeliveryNoteResellerFactory(order=order)
        invoice = InvoiceResellerFactory(reseller=reseller, is_finalized=True)

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.get_invoices_for_delivery_notes",
                side_effect=lambda dn_ids: {dn_id: invoice for dn_id in dn_ids},
            ),
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                autospec=True,
                return_value=True,
            ) as send_email,
        ):
            result = bulk_send_invoice_reminders(
                order_ids=[str(order.id)],
                email_ctx={
                    "tenant_name": "Test Coop",
                    "tenant_language": "de",
                    "bank_details": "DE12 3456 / GENODEF1XXX",
                    "frontend_base_url": "https://test.example.org",
                },
            )

        assert result["successful"] == 1
        assert result["failed"] == 0
        assert send_email.call_count == 1

        from apps.shared.tenants.email_service import EmailService

        bound_self = send_email.call_args.args[0]
        assert isinstance(bound_self, EmailService)
        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "commissioning.invoice_reminder"
        assert kwargs["to_emails"] == ["reseller@example.org"]
        assert kwargs["related_object_type"] == "reseller"
        # The captured tenant context is threaded into the render context +
        # language (the worker's FakeTenant can't supply these), and the
        # template gets dicts in the exact shape it references — NOT raw
        # model instances.
        assert kwargs["language"] == "de"
        ctx = kwargs["context"]
        assert ctx["tenant_name"] == "Test Coop"
        assert ctx["tenant"]["bank_details"] == "DE12 3456 / GENODEF1XXX"
        assert isinstance(ctx["reseller"], dict) and "name" in ctx["reseller"]
        # EML-1: invoices are pre-flattened to substitution-only HTML/text blobs
        # (no Django {% for %} loop, which the safe Mustache renderer can't do).
        assert invoice.full_number in ctx["invoices_table"]
        assert invoice.full_number in ctx["invoices_text"]

    def test_multiple_invoices_for_same_reseller_send_one_email(self, tenant):
        """The consolidation guarantee: three overdue invoices for
        the SAME reseller produce ONE email listing all three — not
        three separate reminders.
        """
        reseller = ResellerFactory(invoice_email="reseller@example.org")
        # Distinct delivery weeks: one Order per reseller per slot
        # (order_unique_reseller_slot). Consolidation is keyed by reseller, so
        # different weeks don't change the "3 invoices → 1 email" expectation.
        order_a = OrderFactory(reseller=reseller, delivery_week=15)
        order_b = OrderFactory(reseller=reseller, delivery_week=16)
        order_c = OrderFactory(reseller=reseller, delivery_week=17)
        DeliveryNoteResellerFactory(order=order_a)
        DeliveryNoteResellerFactory(order=order_b)
        DeliveryNoteResellerFactory(order=order_c)
        invoice_a = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        invoice_b = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        invoice_c = InvoiceResellerFactory(reseller=reseller, is_finalized=True)

        by_dn_id = {
            order_a.delivery_note.pk: invoice_a,
            order_b.delivery_note.pk: invoice_b,
            order_c.delivery_note.pk: invoice_c,
        }

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.get_invoices_for_delivery_notes",
                return_value=by_dn_id,
            ),
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                autospec=True,
                return_value=True,
            ) as send_email,
        ):
            result = bulk_send_invoice_reminders(
                order_ids=[str(order_a.id), str(order_b.id), str(order_c.id)],
            )

        assert result["successful"] == 3
        assert result["failed"] == 0
        # ONE outgoing email for three invoices — the consolidation
        # promise.
        assert send_email.call_count == 1
        # ONE email whose pre-flattened table lists all three invoice rows.
        invoices_table = send_email.call_args.kwargs["context"]["invoices_table"]
        for inv in (invoice_a, invoice_b, invoice_c):
            assert inv.full_number in invoices_table

    def test_progress_callback_receives_one_snapshot_per_reseller_bucket(self, tenant):
        """The Huey wrapper relies on ``progress_cb`` firing once per
        per-reseller iteration so the polling drawer's progress bar
        moves in real time. Two resellers → two snapshots, monotonic
        ``processed`` count, final snapshot has ``processed=total``.
        """
        reseller_a = ResellerFactory(invoice_email="a@example.org")
        reseller_b = ResellerFactory(invoice_email="b@example.org")
        order_a = OrderFactory(reseller=reseller_a)
        order_b = OrderFactory(reseller=reseller_b)
        DeliveryNoteResellerFactory(order=order_a)
        DeliveryNoteResellerFactory(order=order_b)
        invoice_a = InvoiceResellerFactory(reseller=reseller_a, is_finalized=True)
        invoice_b = InvoiceResellerFactory(reseller=reseller_b, is_finalized=True)
        by_dn_id = {
            order_a.delivery_note.pk: invoice_a,
            order_b.delivery_note.pk: invoice_b,
        }

        snapshots: list[dict] = []

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.get_invoices_for_delivery_notes",
                return_value=by_dn_id,
            ),
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                autospec=True,
                return_value=True,
            ),
        ):
            bulk_send_invoice_reminders(
                order_ids=[str(order_a.id), str(order_b.id)],
                progress_cb=lambda p: snapshots.append(p),
            )

        assert len(snapshots) == 2
        assert [s["processed"] for s in snapshots] == [1, 2]
        assert snapshots[-1]["total"] == 2
        assert snapshots[-1]["successful"] == 2

    def test_progress_is_bucket_consistent_with_multiple_invoices(self, tenant):
        """A reseller with multiple invoices is ONE bucket → one email → one
        progress increment. ``successful`` / ``failed`` must count BUCKETS, not
        per-invoice result rows — the old code emitted
        ``{processed:1, successful:3, failed:-2, total:1}`` (successful > total,
        negative failed) for this exact shape (COR-21)."""
        reseller = ResellerFactory(invoice_email="reseller@example.org")
        order_a = OrderFactory(reseller=reseller, delivery_week=15)
        order_b = OrderFactory(reseller=reseller, delivery_week=16)
        order_c = OrderFactory(reseller=reseller, delivery_week=17)
        DeliveryNoteResellerFactory(order=order_a)
        DeliveryNoteResellerFactory(order=order_b)
        DeliveryNoteResellerFactory(order=order_c)
        invoice_a = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        invoice_b = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        invoice_c = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        by_dn_id = {
            order_a.delivery_note.pk: invoice_a,
            order_b.delivery_note.pk: invoice_b,
            order_c.delivery_note.pk: invoice_c,
        }

        snapshots: list[dict] = []

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.get_invoices_for_delivery_notes",
                return_value=by_dn_id,
            ),
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                autospec=True,
                return_value=True,
            ),
        ):
            bulk_send_invoice_reminders(
                order_ids=[str(order_a.id), str(order_b.id), str(order_c.id)],
                progress_cb=lambda p: snapshots.append(p),
            )

        # One reseller bucket → one snapshot, all counters bucket-granular.
        assert len(snapshots) == 1
        assert snapshots[0] == {
            "processed": 1,
            "successful": 1,
            "failed": 0,
            "total": 1,
        }
        # Guard the specific corruption directly.
        assert snapshots[0]["successful"] <= snapshots[0]["total"]
        assert snapshots[0]["failed"] >= 0

    def test_dedups_same_reseller_same_day(self, tenant):
        """EML-3: a retry / re-click of the bulk reminder on the same day must
        NOT re-send dunning to a reseller already reminded — the (reseller,
        sent_on) ReminderSending record makes the second run skip it."""
        from apps.commissioning.models import ReminderSending

        reseller = ResellerFactory(invoice_email="reseller@example.org")
        order = OrderFactory(reseller=reseller)
        DeliveryNoteResellerFactory(order=order)
        invoice = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        ctx = {
            "tenant_name": "Test Coop",
            "tenant_language": "de",
            "bank_details": "DE12 / GENODEF1XXX",
            "frontend_base_url": "https://test.example.org",
        }

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.get_invoices_for_delivery_notes",
                side_effect=lambda dn_ids: {dn_id: invoice for dn_id in dn_ids},
            ),
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                autospec=True,
                return_value=True,
            ) as send_email,
        ):
            first = bulk_send_invoice_reminders(
                order_ids=[str(order.id)], email_ctx=ctx
            )
            second = bulk_send_invoice_reminders(
                order_ids=[str(order.id)], email_ctx=ctx
            )

        # First run sent exactly once; the second run skipped the already-served
        # reseller — no duplicate dunning — yet still reports it as handled.
        assert send_email.call_count == 1
        assert first["successful"] == 1
        assert second["successful"] == 1
        assert second["failed"] == 0
        # Exactly one dedup record for that reseller+day.
        assert ReminderSending.objects.filter(reseller=reseller).count() == 1
