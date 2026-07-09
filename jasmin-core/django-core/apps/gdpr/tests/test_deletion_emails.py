"""Tests for the deletion-confirmation / -approved / -rejected email
helpers.

Contract on all three helpers (``send_deletion_confirmation_email``,
``send_deletion_approved_email``, ``send_deletion_rejected_email``):

  - Best-effort: a failed send does NOT propagate the exception to
    the caller. The view layer dispatches the email AFTER the
    service's atomic transaction has committed, so a mail failure
    must not roll back the deletion state.
  - The approved + rejected helpers read ``requested_email`` off the
    ``DeletionRequest`` row (NOT ``user.email``). For approved that's
    a hard requirement: by the time the helper is called, the
    anonymisation has scrubbed ``user.email`` to
    ``deleted_<pk>@deleted.invalid``.

These tests use ``mock.patch`` against the EmailService class to
simulate the send-failure modes; nothing here actually hits SMTP.
"""

from __future__ import annotations

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import JasminUser
from apps.commissioning.tests.factories import JasminUserFactory
from apps.gdpr.models import (
    DeletionRequest,
    DeletionRequestState,
)
from apps.gdpr.services import (
    GDPRService,
    send_deletion_approved_email,
    send_deletion_confirmation_email,
    send_deletion_pending_admin_office_email,
    send_deletion_rejected_email,
)


def _make_pending_admin_request(user: JasminUser) -> DeletionRequest:
    """Lift a ``request_deletion`` + ``confirm_deletion_token`` pair
    so the test's act-phase starts from the realistic PENDING_ADMIN
    state without re-stating the prelude in every test."""
    req = GDPRService.request_deletion(user)
    return GDPRService.confirm_deletion_token(str(req.token))


# ---------------------------------------------------------------------------
# Helper layer — exception safety
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendDeletionApprovedEmail:
    def test_uses_requested_email_not_live_user_email(self, tenant):
        """The live ``user.email`` is anonymised by the time the
        helper runs (``deleted_<pk>@deleted.invalid``). The helper
        MUST read from ``DeletionRequest.requested_email`` — captured
        at request time — or the email goes to the wrong address."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        deletion_request = _make_pending_admin_request(user)
        admin = JasminUserFactory(roles=["admin"])
        # Run the actual approve, which anonymises user.email.
        deletion_request = GDPRService.admin_approve_deletion(
            deletion_request, admin_user=admin
        )
        user.refresh_from_db()
        assert user.email != "alice@example.com"  # confirms scrub ran

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_approved_email(deletion_request)

        assert send_email.called
        call_kwargs = send_email.call_args.kwargs
        assert call_kwargs["to_emails"] == ["alice@example.com"]
        assert call_kwargs["slug"] == "gdpr.deletion_approved"

    def test_swallows_send_failure(self, tenant):
        """SMTP unreachable, recipient invalid, dispatch crashes —
        helper must catch + log, NOT raise. The view layer's only
        contract is "the deletion already happened; email is
        best-effort". Any uncaught exception here would 500 the view
        AFTER the user is already anonymised."""
        user = JasminUserFactory(roles=["member"])
        deletion_request = _make_pending_admin_request(user)
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.admin_approve_deletion(
            deletion_request, admin_user=admin
        )

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            side_effect=OSError("simulated SMTP outage"),
        ):
            # Must not raise.
            send_deletion_approved_email(deletion_request)

    def test_logs_when_send_returns_falsy(self, tenant):
        """``EmailService.send_email`` returning False (recipient
        rejected, queue full, etc.) is the "soft" failure mode — the
        member's deletion was approved but their confirmation didn't
        send, so the helper logs an alertable ERROR (a Sentry event, not
        just a breadcrumb — ops must follow up) without raising.

        We mock the gdpr-module logger directly rather than using
        pytest's ``caplog`` fixture, which doesn't always see Jasmin's
        named loggers depending on the test config's propagation
        settings.
        """
        from apps.gdpr import services as gdpr_services

        user = JasminUserFactory(roles=["member"])
        deletion_request = _make_pending_admin_request(user)
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.admin_approve_deletion(
            deletion_request, admin_user=admin
        )

        with (
            mock.patch(
                "apps.shared.tenants.email_service.EmailService.send_email",
                return_value=False,
            ),
            mock.patch.object(gdpr_services.logger, "error") as mock_error,
        ):
            send_deletion_approved_email(deletion_request)

        # The event token is passed as a positional arg to a "%s %s"
        # format string (lazy logging), not inlined into it, so match
        # across all args of each error call rather than just args[0].
        emitted = [" ".join(str(a) for a in c.args) for c in mock_error.call_args_list]
        assert any(
            "deletion_approved_email_not_sent" in msg for msg in emitted
        ), f"expected 'not_sent' error; got {emitted!r}"


@pytest.mark.django_db
class TestSendDeletionRejectedEmail:
    def test_includes_reason_in_context(self, tenant):
        """Rejection email is the user's only signal that the office
        said no — the reason text MUST be passed through to the
        template context so the user knows what to fix."""
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_rejected_email(
                deletion_request,
                reason="3 offene Genossenschaftsanteile zuerst kündigen.",
            )

        assert send_email.call_args.kwargs["context"]["reason"] == (
            "3 offene Genossenschaftsanteile zuerst kündigen."
        )
        assert send_email.call_args.kwargs["to_emails"] == ["alice@example.com"]

    def test_swallows_send_failure(self, tenant):
        user = JasminUserFactory(roles=["member"])
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            side_effect=OSError("simulated SMTP outage"),
        ):
            send_deletion_rejected_email(deletion_request, reason="any")


# ---------------------------------------------------------------------------
# Office push notification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSendDeletionPendingAdminOfficeEmail:
    """The office-notification helper has stricter content guarantees
    than the user-facing emails — it MUST NOT include any PII about
    the requesting person because the office mailbox is often a
    shared / auto-forwarded inbox. The tests below pin those
    invariants so a future template change can't accidentally
    surface the requested email or member name."""

    def _set_office_email(self, tenant, address: str | None) -> None:
        from django.db import connection

        live_tenant = getattr(connection, "tenant", None)
        if live_tenant is None:
            return
        live_tenant.email = address
        live_tenant.save(update_fields=["email"])

    def test_sends_to_tenant_email(self, tenant):
        self._set_office_email(tenant, "office@example.org")
        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_pending_admin_office_email(deletion_request)

        assert send_email.called
        call_kwargs = send_email.call_args.kwargs
        assert call_kwargs["to_emails"] == ["office@example.org"]
        assert call_kwargs["slug"] == "gdpr.deletion_pending_admin_office"

    def test_context_contains_no_pii_about_requester(self, tenant):
        """Belt-and-braces: the helper's context dict must not
        include the user, the requested_email, the deletion-request
        id, or anything else that could later show up in the template
        body. Only ``tenant_name`` + ``review_url`` belong here."""
        self._set_office_email(tenant, "office@example.org")
        user = JasminUserFactory(
            roles=["member"],
            email="alice@example.com",
            first_name="Alice",
            last_name="Acres",
        )
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_pending_admin_office_email(deletion_request)

        ctx = send_email.call_args.kwargs["context"]
        # Allowed keys only.
        assert set(ctx.keys()) == {"tenant_name", "review_url"}
        # Spot-check no PII slipped in via stringified context values.
        flat = " ".join(str(v) for v in ctx.values()).lower()
        assert "alice" not in flat
        assert "acres" not in flat
        assert "alice@example.com" not in flat
        # The review URL hits the office config page, not a
        # request-specific id.
        assert ctx["review_url"].endswith("/configuration/gdpr")

    def test_skips_silently_when_office_email_unset(self, tenant):
        """Tenant without an ``email`` configured → no send, no
        crash, log a ``skipped`` info line. The office still sees
        pending rows in ConfigurationGDPR; they just don't get the
        push."""
        self._set_office_email(tenant, None)
        user = JasminUserFactory(roles=["member"])
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_pending_admin_office_email(deletion_request)

        assert not send_email.called

    def test_swallows_send_failure(self, tenant):
        """Best-effort: a failing send must NOT raise. The state
        transition has already committed; the office can fall back
        to ConfigurationGDPR."""
        self._set_office_email(tenant, "office@example.org")
        user = JasminUserFactory(roles=["member"])
        deletion_request = _make_pending_admin_request(user)

        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            side_effect=OSError("simulated SMTP outage"),
        ):
            send_deletion_pending_admin_office_email(deletion_request)


# ---------------------------------------------------------------------------
# View layer — end-to-end resilience
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminViewsRobustToEmailFailure:
    """If the helper inside ``views.gdpr_admin_*`` raises despite our
    best-effort try/except (e.g. an unexpected exception type slips
    past the except clauses), the DB state change must still be
    persisted. Tested by patching the helper to raise an
    ``Exception`` (not in the catch list) and verifying the
    transaction has already committed."""

    def test_approve_view_persists_state_even_if_email_helper_raises(self, tenant):
        from django.urls import reverse

        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = _make_pending_admin_request(user)

        # gdpr-admin-approve-deletion is gated by RequiresStepUp (it
        # irreversibly anonymises a user), so the admin needs a fresh
        # step-up claim to get past the permission to the view body.
        from apps.commissioning.tests.conftest import make_step_up_token

        client = APIClient()
        client.force_authenticate(user=admin, token=make_step_up_token(admin))

        # Patch the helper imported into the view module so it
        # bypasses the swallow-clauses and raises unconditionally.
        # DRF's exception handler turns the unhandled exception into
        # a 500 — we don't care about the response code; we care that
        # the DB state was already committed by the time the helper
        # raised, so the anonymisation isn't lost.
        with mock.patch(
            "apps.gdpr.views.send_deletion_approved_email",
            side_effect=RuntimeError("unexpected"),
        ):
            response = client.post(
                reverse(
                    "gdpr-admin-approve-deletion",
                    kwargs={"request_id": str(deletion_request.pk)},
                )
            )
        # Whatever the response is, the DB state must reflect the
        # committed transaction.
        assert response.status_code in (200, 500)
        deletion_request.refresh_from_db()
        assert deletion_request.state == DeletionRequestState.EXECUTED
        user.refresh_from_db()
        assert user.email == f"deleted_{user.pk}@deleted.invalid"

    def test_reject_view_persists_state_even_if_email_helper_raises(self, tenant):
        from django.urls import reverse

        user = JasminUserFactory(roles=["member"], email="alice@example.com")
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = _make_pending_admin_request(user)

        client = APIClient()
        client.force_authenticate(user=admin)

        with mock.patch(
            "apps.gdpr.views.send_deletion_rejected_email",
            side_effect=RuntimeError("unexpected"),
        ):
            response = client.post(
                reverse(
                    "gdpr-admin-reject-deletion",
                    kwargs={"request_id": str(deletion_request.pk)},
                ),
                data={"reason": "no"},
                format="json",
            )
        assert response.status_code in (200, 500)
        deletion_request.refresh_from_db()
        assert deletion_request.state == DeletionRequestState.REJECTED
        # User row untouched — reject doesn't anonymise.
        user.refresh_from_db()
        assert user.email == "alice@example.com"


@pytest.mark.django_db
class TestDeletionEmailLanguage:
    """EML-1: the three user-facing deletion emails render in the recipient's
    own ``user_language`` (forwarded to EmailService.send_email)."""

    def test_confirmation_email_forwards_user_language(self, tenant):
        user = JasminUserFactory(roles=["member"], email="de@example.com")
        user.user_language = "de"
        user.save(update_fields=["user_language"])
        req = GDPRService.request_deletion(user)
        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_confirmation_email(user, req)
        assert send_email.call_args.kwargs["language"] == "de"

    def test_approved_email_forwards_language_after_anonymisation(self, tenant):
        # user_language is NOT in FIELD_CLASSIFICATION, so it survives the scrub
        # that runs during approve — the cached user still carries it.
        user = JasminUserFactory(roles=["member"], email="de2@example.com")
        user.user_language = "de"
        user.save(update_fields=["user_language"])
        deletion_request = _make_pending_admin_request(user)
        admin = JasminUserFactory(roles=["admin"])
        deletion_request = GDPRService.admin_approve_deletion(
            deletion_request, admin_user=admin
        )
        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_approved_email(deletion_request)
        assert send_email.call_args.kwargs["language"] == "de"

    def test_default_language_when_no_preference(self, tenant):
        # Model default is LanguageChoices.EN — the forwarded value is "en".
        user = JasminUserFactory(roles=["member"], email="def@example.com")
        req = GDPRService.request_deletion(user)
        with mock.patch(
            "apps.shared.tenants.email_service.EmailService.send_email",
            return_value=True,
        ) as send_email:
            send_deletion_confirmation_email(user, req)
        assert send_email.call_args.kwargs["language"] == "en"
