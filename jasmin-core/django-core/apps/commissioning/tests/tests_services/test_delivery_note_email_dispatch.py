"""Tests for ``DeliveryNoteService.send_to_reseller`` — the P0-3
wiring documented in ``docs/code/email-overview.md``.

Contract (mirrors InvoiceService.send_to_reseller — see
test_invoice_email_dispatch.py — but with one structural
difference: DN send is MANUAL only, triggered by the office user
via the ``send_to_reseller`` viewset action. There's no
``upload_pdf``-style auto-trigger to test.):

  * Best-effort: a transient SMTP failure must NOT raise. The DN
    was already legally finalized in a prior transaction (HGB §257
    / one-way finalize); a downstream email error must not roll
    that back.
  * On success the tracker pair is flipped:
        has_been_sent_to_reseller -> True
        has_been_sent_to_reseller_at -> now()
  * Both fields live in
    ``DeliveryNoteReseller.ALLOWED_FINALIZED_UPDATES`` so the
    flag-flip works post-finalize.
  * Short-circuit cases that MUST return False without sending:
      - No ``reseller.invoice_email`` configured
      - ``dn.file`` empty (PDF not uploaded yet)

We patch ``EmailService.send_email`` with ``autospec=True`` so the
mock keeps the same ``self`` binding as the real method — same
class-vs-instance protection as the P0-1 regression test
(``test_reseller_views.py``).
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.tests.factories import (
    DeliveryNoteResellerFactory,
    OrderFactory,
    ResellerFactory,
)
from apps.shared.tenants.email_service import EmailService

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _attach_pdf(
    dn, name: str = "lieferschein.pdf", body: bytes = b"%PDF-1.4 test"
) -> None:
    """Attach a stub PDF to ``dn.file``. The bytes aren't a valid
    PDF — the helpers only ``.read()`` them."""
    dn.file = SimpleUploadedFile(name, body, content_type="application/pdf")
    dn.save(update_fields=["file"])


@pytest.fixture
def reseller_with_email():
    return ResellerFactory(invoice_email="reseller@example.org")


@pytest.fixture
def finalized_dn_with_pdf(reseller_with_email):
    order = OrderFactory(reseller=reseller_with_email)
    dn = DeliveryNoteResellerFactory(
        order=order,
        is_finalized=True,
        date=datetime.date(2026, 6, 12),
    )
    _attach_pdf(dn)
    return dn


# ---------------------------------------------------------------------------
# send_to_reseller — contract tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendToReseller:
    def test_short_circuits_when_reseller_has_no_invoice_email(self, tenant):
        reseller = ResellerFactory(invoice_email=None)
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        _attach_pdf(dn)

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert DeliveryNoteService.send_to_reseller(dn) is False
        assert not send_email.called

        dn.refresh_from_db()
        assert dn.has_been_sent_to_reseller is False
        assert dn.has_been_sent_to_reseller_at is None

    def test_short_circuits_when_pdf_not_uploaded(self, tenant, reseller_with_email):
        order = OrderFactory(reseller=reseller_with_email)
        dn = DeliveryNoteResellerFactory(order=order, is_finalized=True)
        # No ``_attach_pdf`` here on purpose.

        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert DeliveryNoteService.send_to_reseller(dn) is False
        assert not send_email.called

    def test_happy_path_flips_tracker_flags(self, tenant, finalized_dn_with_pdf):
        with mock.patch.object(
            EmailService, "send_email", autospec=True, return_value=True
        ) as send_email:
            assert DeliveryNoteService.send_to_reseller(finalized_dn_with_pdf) is True

        # ``autospec=True`` keeps ``self`` as the first positional
        # arg → asserts the helper hit the method via an instance,
        # not the class. Same protection pattern as the P0-1
        # regression.
        assert send_email.called
        bound_self = send_email.call_args.args[0]
        assert isinstance(bound_self, EmailService)
        kwargs = send_email.call_args.kwargs
        assert kwargs["slug"] == "commissioning.delivery_note"
        assert kwargs["to_emails"] == ["reseller@example.org"]
        assert kwargs["purpose"] == "delivery_note:reseller"
        assert kwargs["related_object_type"] == "delivery_note"
        # No XML attachment — ZUGFeRD is invoice-only.
        assert len(kwargs["attachments"]) == 1
        filename, body, mimetype = kwargs["attachments"][0]
        assert filename.endswith(".pdf")
        assert mimetype == "application/pdf"
        assert body == b"%PDF-1.4 test"

        finalized_dn_with_pdf.refresh_from_db()
        assert finalized_dn_with_pdf.has_been_sent_to_reseller is True
        assert finalized_dn_with_pdf.has_been_sent_to_reseller_at is not None

    def test_does_not_raise_on_smtp_error(self, tenant, finalized_dn_with_pdf):
        """The DN is already legally finalized (HGB §257 one-way).
        A transient SMTP error must NOT bubble up — it would mislead
        the viewset caller into thinking the action itself failed."""
        import smtplib

        with mock.patch.object(
            EmailService,
            "send_email",
            autospec=True,
            side_effect=smtplib.SMTPException("simulated SMTP outage"),
        ):
            # Must not raise.
            assert DeliveryNoteService.send_to_reseller(finalized_dn_with_pdf) is False

        finalized_dn_with_pdf.refresh_from_db()
        assert finalized_dn_with_pdf.has_been_sent_to_reseller is False
        assert finalized_dn_with_pdf.has_been_sent_to_reseller_at is None
