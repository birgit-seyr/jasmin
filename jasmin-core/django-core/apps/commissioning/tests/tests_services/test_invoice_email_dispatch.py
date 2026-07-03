"""Tests for ``InvoiceService.send_to_reseller`` /
``send_to_accounting`` — the P0-2 wiring documented in
``docs/code/email-overview.md``.

Contract:

  * Both helpers are best-effort: a transient SMTP failure must NOT
    raise, because the invoice was already legally finalized in a
    prior transaction (UStG §14 / GoBD: invoices are one-way
    finalized) and a downstream email error must not roll that back.
  * On success the matching ``*_at`` timestamp is stamped:
        send_to_reseller   -> has_been_sent_to_reseller_at
        send_to_accounting -> has_been_sent_to_accounting_at
    ``has_been_sent_to_reseller`` and
    ``has_been_sent_to_accounting`` are derived @properties (True
    iff the matching timestamp is set).
  * The timestamp write uses ``ALLOWED_FINALIZED_UPDATES`` on
    ``InvoiceReseller`` — listed there explicitly, so a regular
    ``invoice.save(update_fields=[...])`` works post-finalize.
  * Short-circuit cases that MUST return False without sending:
      - No ``reseller.invoice_email``  (reseller-side)
      - No ``TenantEmailConfig.accounting_email``  (accounting-side)
      - No ``invoice.file``  (PDF hasn't been uploaded yet — should
        never happen because ``upload_pdf`` is the only auto-trigger,
        but the helper is robust regardless)

We patch ``EmailService.send_email`` with ``autospec=True`` so the
mock keeps the same ``self`` binding as the real method — a plain
``mock.patch`` would have hidden the P0-1-class bug (see
``test_reseller_views.py::TestBulkSendInvoiceRemindersViaEmail``)
and we want the same protection here for these new instance calls.
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    InvoiceResellerFactory,
    ResellerFactory,
)
from apps.shared.tenants.email_service import EmailService
from apps.shared.tenants.models import TenantEmailConfig

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _attach_pdf(
    invoice, name: str = "rechnung.pdf", body: bytes = b"%PDF-1.4 test"
) -> None:
    """Attach a stub PDF to ``invoice.file`` so the email helpers see
    a file to read. The bytes don't have to be a valid PDF — the
    helpers only ``.read()`` them."""
    invoice.file = SimpleUploadedFile(name, body, content_type="application/pdf")
    invoice.save(update_fields=["file"])


@pytest.fixture
def reseller_with_email():
    return ResellerFactory(invoice_email="reseller@example.org")


@pytest.fixture
def finalized_invoice_with_pdf(reseller_with_email):
    # ``number`` is an IntegerField on NumberedModelMixin (and a
    # ``PositiveIntegerField`` with a unique constraint on the legacy
    # variant). Don't pass a string here. ``prefix`` defaults to ``""``,
    # ``number`` is nullable — leaving both unset is fine for the
    # email-context smoke test; the rendered subject line just shows
    # an empty number, which is what we'd see if a real invoice were
    # email-sent before ``assign_final_number`` ran. The email body
    # going out is incidental to what we're testing here.
    invoice = InvoiceResellerFactory(
        reseller=reseller_with_email,
        is_finalized=True,
        date=datetime.date(2026, 6, 1),
    )
    _attach_pdf(invoice)
    return invoice


@pytest.fixture
def accounting_email_config(tenant):
    """TenantEmailConfig with a populated ``accounting_email``. Tests
    that need ``send_to_accounting`` to actually try sending need
    this; tests that need the no-config short-circuit branch should
    NOT request it."""
    cfg = TenantEmailConfig.objects.create(
        tenant=tenant,
        smtp_host="localhost",
        smtp_port=25,
        smtp_use_tls=False,
        from_email="noreply@example.org",
        from_name="Test Tenant",
        accounting_email="datev@coop.de",
        is_active=True,
        is_verified=True,
    )
    return cfg


# ---------------------------------------------------------------------------
# send_to_reseller
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInvoiceEmailContextTotal:
    """Regression: the invoice/reminder email total is the formatted
    ``sum_brutto`` — never blank.

    ``sum_brutto`` is a @property; it was called as ``sum_brutto()``,
    raising a ``TypeError`` that the surrounding ``except`` swallowed to an
    empty string, so every invoice and overdue-reminder email rendered a
    blank ``Gesamtbetrag``.
    """

    def test_total_is_formatted_sum_brutto_not_blank(
        self, tenant, finalized_invoice_with_pdf
    ):
        invoice = finalized_invoice_with_pdf
        ctx = InvoiceService._build_invoice_email_context(invoice)
        assert ctx["invoice"]["total"] == f"{invoice.sum_brutto:.2f}"
        assert ctx["invoice"]["total"] != ""


@pytest.mark.django_db
class TestSendToReseller:
    def test_short_circuits_when_reseller_has_no_invoice_email(self, tenant):
        reseller = ResellerFactory(invoice_email=None)
        invoice = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        _attach_pdf(invoice)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert InvoiceService.send_to_reseller(invoice) is False
        assert not send_email.called

        invoice.refresh_from_db()
        assert invoice.has_been_sent_to_reseller is False
        assert invoice.has_been_sent_to_reseller_at is None

    def test_short_circuits_when_reseller_opted_out_of_email(self, tenant):
        """EML-2: a reseller with a valid invoice_email but invoice_via_email=
        False (paper-only) must NOT be auto-emailed — the gate lives in
        send_to_reseller so every caller (incl. the upload auto-send) honours it."""
        reseller = ResellerFactory(
            invoice_email="reseller@example.org", invoice_via_email=False
        )
        invoice = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        _attach_pdf(invoice)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert InvoiceService.send_to_reseller(invoice) is False
        assert not send_email.called

        invoice.refresh_from_db()
        assert invoice.has_been_sent_to_reseller is False
        assert invoice.has_been_sent_to_reseller_at is None

    def test_short_circuits_when_pdf_not_uploaded(self, tenant, reseller_with_email):
        invoice = InvoiceResellerFactory(
            reseller=reseller_with_email, is_finalized=True
        )
        # No ``_attach_pdf`` here on purpose.

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert InvoiceService.send_to_reseller(invoice) is False
        assert not send_email.called

    def test_happy_path_flips_tracker_flags(self, tenant, finalized_invoice_with_pdf):
        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert InvoiceService.send_to_reseller(finalized_invoice_with_pdf) is True

        # autospec keeps ``self`` as the first positional arg →
        # asserts the helper hit the method via an instance, not the
        # class. Same protection pattern as the P0-1 regression.
        assert send_email.called
        bound_self = send_email.call_args.args[0]
        assert isinstance(bound_self, EmailService)
        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "commissioning.invoice"
        assert kwargs["to_emails"] == ["reseller@example.org"]
        assert kwargs["purpose"] == "invoice:reseller"
        assert kwargs["related_object_type"] == "invoice"
        assert len(kwargs["attachments"]) == 1
        filename, body, mimetype = kwargs["attachments"][0]
        assert filename.endswith(".pdf")
        assert mimetype == "application/pdf"
        assert body == b"%PDF-1.4 test"

        finalized_invoice_with_pdf.refresh_from_db()
        assert finalized_invoice_with_pdf.has_been_sent_to_reseller is True
        assert finalized_invoice_with_pdf.has_been_sent_to_reseller_at is not None

    def test_does_not_raise_on_smtp_error(self, tenant, finalized_invoice_with_pdf):
        """The invoice is already legally finalized in a prior txn.
        A transient SMTP error here must NOT bubble up and cause a
        500 — it would mislead the caller into thinking the upload
        itself failed."""
        import smtplib

        with mock.patch.object(
            EmailService,
            "send_email",
            autospec=True,
            side_effect=smtplib.SMTPException("simulated SMTP outage"),
        ):
            # Must not raise.
            assert InvoiceService.send_to_reseller(finalized_invoice_with_pdf) is False

        finalized_invoice_with_pdf.refresh_from_db()
        assert finalized_invoice_with_pdf.has_been_sent_to_reseller is False


# ---------------------------------------------------------------------------
# send_to_accounting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendToAccounting:
    def test_short_circuits_when_no_tenant_email_config(
        self, tenant, finalized_invoice_with_pdf
    ):
        """No TenantEmailConfig at all → return False, never invoke
        the SMTP layer. The tenant simply hasn't configured outbound
        email yet; that's a valid early-stage state."""
        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert (
                InvoiceService.send_to_accounting(finalized_invoice_with_pdf) is False
            )
        assert not send_email.called

    def test_short_circuits_when_accounting_email_not_set(
        self, tenant, finalized_invoice_with_pdf
    ):
        TenantEmailConfig.objects.create(
            tenant=tenant,
            smtp_host="localhost",
            smtp_port=25,
            from_email="noreply@example.org",
            from_name="Test Tenant",
            accounting_email=None,  # the case under test
            is_active=True,
        )

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert (
                InvoiceService.send_to_accounting(finalized_invoice_with_pdf) is False
            )
        assert not send_email.called

    def test_happy_path_flips_accounting_flags(
        self,
        tenant,
        finalized_invoice_with_pdf,
        accounting_email_config,
    ):
        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert InvoiceService.send_to_accounting(finalized_invoice_with_pdf) is True

        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "commissioning.invoice"
        assert kwargs["to_emails"] == ["datev@coop.de"]
        assert kwargs["purpose"] == "invoice:accounting"

        finalized_invoice_with_pdf.refresh_from_db()
        assert finalized_invoice_with_pdf.has_been_sent_to_accounting is True
        assert finalized_invoice_with_pdf.has_been_sent_to_accounting_at is not None

    def test_attaches_zugferd_xml_when_present(
        self,
        tenant,
        reseller_with_email,
        accounting_email_config,
    ):
        """ZUGFeRD is embedded in the PDF, but tenants who run a DATEV
        ingestion pipeline often want the standalone XML too. When
        ``invoice.xml_file`` is populated, both go out as separate
        attachments."""
        invoice = InvoiceResellerFactory(
            reseller=reseller_with_email,
            is_finalized=True,
            date=datetime.date(2026, 6, 1),
        )
        _attach_pdf(invoice)
        invoice.xml_file = SimpleUploadedFile(
            "rechnung.xml",
            b"<?xml version='1.0'?><Invoice/>",
            content_type="application/xml",
        )
        invoice.save(update_fields=["xml_file"])

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            InvoiceService.send_to_accounting(invoice)

        attachments = send_email.call_args.kwargs["attachments"]
        assert len(attachments) == 2
        mimetypes = {a[2] for a in attachments}
        assert mimetypes == {"application/pdf", "application/xml"}


# ---------------------------------------------------------------------------
# Auto-send on upload_pdf
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUploadPdfAutoSend:
    """Cover the wiring in
    ``InvoiceResellerViewSet.upload_pdf`` -> ``transaction.on_commit
    (send_to_reseller / send_to_accounting)``.

    We patch the two service helpers at module path level (where
    ``upload_pdf`` imports them) so the assertion is about the
    trigger, not the send itself — the send is covered above.

    Critical: ``transaction.on_commit`` callbacks do NOT fire under
    pytest-django's default savepoint mode — the surrounding test
    transaction never commits, so the deferred callbacks just leak.
    We wrap the upload call in ``TestCase.captureOnCommitCallbacks
    (execute=True)`` so the on-commit hooks fire synchronously at
    context-exit. Same idiom Django's own contrib tests use."""

    def _upload(self, api_client, invoice, content: bytes = b"%PDF-1.4 test"):
        from django.urls import reverse

        url = reverse("invoices-upload-pdf", kwargs={"pk": invoice.pk})
        upload = SimpleUploadedFile(
            "rechnung.pdf", content, content_type="application/pdf"
        )
        return api_client.post(url, {"file": upload}, format="multipart")

    def test_first_upload_triggers_both_sends(
        self, api_client, tenant, reseller_with_email
    ):
        from django.test import TestCase

        invoice = InvoiceResellerFactory(
            reseller=reseller_with_email, is_finalized=True
        )
        # Neither flag set yet → both sends should fire.
        assert invoice.has_been_sent_to_reseller is False
        assert invoice.has_been_sent_to_accounting is False

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.send_to_reseller",
            ) as send_reseller,
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.send_to_accounting",
            ) as send_accounting,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            resp = self._upload(api_client, invoice)

        from rest_framework import status

        assert resp.status_code == status.HTTP_200_OK
        assert send_reseller.call_count == 1
        assert send_accounting.call_count == 1

    def test_second_upload_does_not_re_trigger_sends(
        self, api_client, tenant, reseller_with_email
    ):
        """Idempotency on the auto-send side. Once
        ``has_been_sent_to_reseller_at`` is set, subsequent
        ``upload_pdf`` calls (e.g. the frontend resubmitting after a
        transient upload error, or an admin replacing the PDF) must
        NOT fire another reseller-email. Same for the accounting
        side. The boolean ``has_been_sent_to_reseller`` is now a
        @property derived from the timestamp — setting the timestamp
        is equivalent to setting the old boolean."""
        from django.test import TestCase

        invoice = InvoiceResellerFactory(
            reseller=reseller_with_email,
            is_finalized=True,
            has_been_sent_to_reseller_at=datetime.datetime(
                2026, 6, 1, tzinfo=datetime.UTC
            ),
            has_been_sent_to_accounting_at=datetime.datetime(
                2026, 6, 1, tzinfo=datetime.UTC
            ),
        )

        with (
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.send_to_reseller",
            ) as send_reseller,
            mock.patch(
                "apps.commissioning.services.invoice_service."
                "InvoiceService.send_to_accounting",
            ) as send_accounting,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            resp = self._upload(api_client, invoice)

        from rest_framework import status

        assert resp.status_code == status.HTTP_200_OK
        assert send_reseller.call_count == 0
        assert send_accounting.call_count == 0
