"""Module-level GDPR deletion-email senders.

Best-effort dispatchers for the two-step deletion flow. They live at
module level (not on ``GDPRService``) so views can import and call them
directly — see each function's docstring for the exact contract.
"""

from __future__ import annotations

import logging

from apps.accounts.models import JasminUser

from ..models import DeletionRequest

logger = logging.getLogger("gdpr")


def send_deletion_confirmation_email(
    user: JasminUser, deletion_request: DeletionRequest
) -> None:
    """Render and dispatch the GDPR deletion-confirmation email.

    Best-effort, same contract as ``_send_password_reset_email``: a
    failed send does NOT roll back the ``DeletionRequest`` row. If
    the user never gets the email they can re-request, which
    supersedes the previous row.

    Lives at module level (not on ``GDPRService``) so views can
    import + call it directly, and so the unit tests for
    ``request_deletion`` can stay free of email-side-effect mocks.
    """
    from apps.shared.deferred_email import send_email_best_effort
    from apps.shared.tenant_urls import frontend_base_url, tenant_name

    base_url = frontend_base_url()
    confirm_url = f"{base_url}/gdpr/confirm-deletion/{deletion_request.token}"

    # Flatten to plain scalars — never hand a live ORM instance to the
    # tenant-editable email renderer (see template_renderer._resolve).
    context = {
        "tenant_name": tenant_name(),
        "user": {"first_name": user.first_name},
        "confirm_url": confirm_url,
        "requires_admin_approval": deletion_request.requires_admin_approval,
    }
    send_email_best_effort(
        slug="gdpr.deletion_confirm",
        to_emails=[user.email],
        context=context,
        related_object_type="gdpr.deletion_request",
        related_object_id=str(deletion_request.pk),
        priority="high",
        # EML-1: render in the recipient's own language (explicit >
        # tenant-default > DEFAULT_LANGUAGE). None preserves today's default.
        language=getattr(user, "user_language", None) or None,
        logger=logger,
        log_error_event="gdpr.deletion_email_failed",
        log_not_sent_event="gdpr.deletion_email_not_sent",
        log_ref=f"user={user.email} request_id={deletion_request.pk}",
        # A missed confirmation mail is non-actionable (the user can simply
        # re-request), so keep this at WARNING rather than the helper's default
        # ERROR.
        log_level="warning",
    )


def send_deletion_approved_email(deletion_request: DeletionRequest) -> None:
    """Dispatch the "your deletion is complete" email after admin approve.

    Reads ``requested_email`` off the row (captured at request time,
    plaintext) instead of ``user.email`` — by the time we send, the
    anonymisation has already scrubbed the live email column to
    ``deleted_<pk>@deleted.invalid``.

    Best-effort: a failed send does NOT roll back the executed deletion.
    The audit log + the user's local copy of their request confirmation
    are enough of a paper trail; if the success mail bounces the office
    can resend manually.
    """
    from apps.shared.deferred_email import send_email_best_effort
    from apps.shared.tenant_urls import tenant_name

    user = deletion_request.user
    context = {
        # Use the captured email's first-name guess: post-anonymisation
        # user.first_name is "Gelöscht". The deletion-request row keeps
        # the original email, but not the first name. Fall back to
        # template's |default:"…" handling.
        "user": {"first_name": ""},
        "tenant_name": tenant_name(),
    }
    send_email_best_effort(
        slug="gdpr.deletion_approved",
        to_emails=[deletion_request.requested_email],
        context=context,
        related_object_type="gdpr.deletion_request",
        related_object_id=str(deletion_request.pk),
        priority="high",
        # EML-1: the recipient's language preference is NOT in the JasminUser
        # FIELD_CLASSIFICATION, so it survives the anonymisation that ran
        # before this send — the cached ``user`` still carries it.
        language=getattr(user, "user_language", None) or None,
        logger=logger,
        log_error_event="gdpr.deletion_approved_email_failed",
        log_not_sent_event="gdpr.deletion_approved_email_not_sent",
        log_ref=f"request_id={deletion_request.pk} user={deletion_request.requested_email}",
    )


def send_deletion_pending_admin_office_email(
    deletion_request: DeletionRequest,
) -> None:
    """Notify the office that a deletion request just landed in
    ``PENDING_ADMIN`` — they need to approve / reject it.

    Triggered from ``_consume_pending_email_request`` after the user
    clicks their confirmation link. Goes to the tenant's general
    office mailbox (``Tenant.email``); falls back to a no-op +
    warning when the tenant hasn't set one (the office can still
    see pending requests in ConfigurationGDPR, just without the
    push).

    **DELIBERATELY MINIMAL PAYLOAD** — the email contains NO PII
    about the requesting user:

      * No name, no email, no member-number, no request id.
      * Just "you have a pending GDPR deletion request — review in
        /configuration/gdpr".

    Reasoning: the office mailbox is typically a shared inbox,
    sometimes auto-forwarded to multiple addresses. Pushing the
    user's identity into that mail chain creates a second
    PII surface to manage (retention, encryption, legal-basis
    documentation) for a notification that only needs to say
    "go check the queue".

    Best-effort: a failed send does NOT roll back the state
    transition. The office can still find the request in
    ConfigurationGDPR — they just don't get the push.
    """
    from django.db import connection

    from apps.shared.deferred_email import send_email_best_effort
    from apps.shared.tenant_urls import frontend_base_url, tenant_name

    tenant = getattr(connection, "tenant", None)
    office_email = getattr(tenant, "email", None)
    if not office_email:
        # No address configured → skip silently. The office still
        # sees pending rows in ConfigurationGDPR; this just means
        # they won't get notified by email. ``logger.info`` (not
        # ``warning``) because a fresh tenant legitimately has no
        # email set and we don't want noise during onboarding.
        logger.info(
            "gdpr.deletion_pending_office_email_skipped "
            "request_id=%s reason=no_office_email",
            deletion_request.pk,
        )
        return

    review_url = f"{frontend_base_url()}/configuration/gdpr"

    # Context carries ONLY tenant-side info + the review link. The
    # ``deletion_request`` is NOT passed in — anyone editing the
    # template later can't accidentally surface its ``requested_email``
    # or ``user.first_name`` because they aren't in the context dict.
    context = {
        "tenant_name": tenant_name(),
        "review_url": review_url,
    }
    send_email_best_effort(
        slug="gdpr.deletion_pending_admin_office",
        to_emails=[office_email],
        context=context,
        # ``related_object_id`` so the audit trail can join the
        # EmailLog row back to which request triggered it — the
        # office can grep for "we sent the notification for THIS
        # request" without the user's identity being in the body.
        related_object_type="gdpr.deletion_request",
        related_object_id=str(deletion_request.pk),
        priority="normal",
        logger=logger,
        log_error_event="gdpr.deletion_pending_office_email_failed",
        log_not_sent_event="gdpr.deletion_pending_office_email_not_sent",
        log_ref=f"request_id={deletion_request.pk}",
        # An unpushed office heads-up is non-actionable (the request is still
        # visible in ConfigurationGDPR), so keep WARNING, not the default ERROR.
        log_level="warning",
    )


def send_deletion_rejected_email(
    deletion_request: DeletionRequest, *, reason: str
) -> None:
    """Dispatch the "your deletion was rejected" email after admin reject.

    Best-effort: a failed send does NOT roll back the REJECTED state —
    the user can re-request once the obligations are settled. Both
    ``user.email`` and ``requested_email`` should still be live (no
    anonymisation on reject), but we prefer ``requested_email`` for
    consistency with the approve path.
    """
    from apps.shared.deferred_email import send_email_best_effort
    from apps.shared.tenant_urls import tenant_name

    user = deletion_request.user
    context = {
        "user": {"first_name": getattr(user, "first_name", "") if user else ""},
        "tenant_name": tenant_name(),
        "reason": reason,
    }
    send_email_best_effort(
        slug="gdpr.deletion_rejected",
        to_emails=[deletion_request.requested_email],
        context=context,
        related_object_type="gdpr.deletion_request",
        related_object_id=str(deletion_request.pk),
        priority="high",
        # EML-1: render in the recipient's language. ``user`` may be None on
        # the reject path (DeletionRequest.user is SET_NULL) — None-safe.
        language=getattr(user, "user_language", None) or None,
        logger=logger,
        log_error_event="gdpr.deletion_rejected_email_failed",
        log_not_sent_event="gdpr.deletion_rejected_email_not_sent",
        log_ref=f"request_id={deletion_request.pk} user={deletion_request.requested_email}",
    )
