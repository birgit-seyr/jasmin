"""Domain errors raised by the GDPR app.

Translated to HTTP responses by ``core.exception_handler`` — views do
not need to catch them. Use the closest existing class; add new ones
freely when a new failure mode is introduced (e.g. Step 5's
``PreviewUnavailable``).
"""

from __future__ import annotations

from typing import Any

from core.errors import BadRequestError, ConflictError, NotFoundError


class GDPRError(ConflictError):
    """Base for GDPR-flow errors. Defaults to 409 Conflict — most GDPR
    refusals are state conflicts (retention active, request already
    confirmed, etc.), not bad input."""

    code = "gdpr.error"


class RetentionPeriodActive(GDPRError):
    """Anonymization refused because the data subject still has
    statutory retention obligations (active CoopShare, open invoice,
    active subscription).

    Article 17(3)(b) of the GDPR exempts "compliance with a legal
    obligation that requires processing" from the right to erasure.
    The German laws that apply here:

    - **GenG §5 / §15** — cooperative member registry must persist
      while shares are held + 10 years after exit.
    - **HGB §257** — commercial documents (invoices, ledgers,
      correspondence) — 10 years.
    - **UStG §14b** — issued invoices — 10 years.

    The error's ``details`` carry per-reason explanations the
    frontend can render as a list (e.g. "Cannot delete: 2 unpaid
    invoices, 3 active CoopShares, active subscription until …").
    """

    code = "gdpr.retention_active"

    def __init__(self, reasons: list[str], **details: Any) -> None:
        message = (
            "Cannot anonymize: data subject has open retention obligations. "
            "Reasons: " + "; ".join(reasons)
        )
        super().__init__(message, details={"reasons": reasons, **details})


class DeletionTokenInvalid(NotFoundError):
    """The confirmation token from a deletion email is unknown,
    consumed, or for a request in a state where confirmation no
    longer applies.

    404 (rather than 400) so the response is indistinguishable
    between "never existed" and "already used" — small mitigation
    against an attacker probing for valid tokens with a guess.
    """

    code = "gdpr.deletion_token_invalid"


class DeletionTokenExpired(GDPRError):
    """The confirmation token was valid but the 24h window has
    passed. The frontend tells the user to request deletion again."""

    code = "gdpr.deletion_token_expired"


class DeletionRequestNotPending(GDPRError):
    """Admin tried to approve / reject a request that isn't currently
    in ``PENDING_ADMIN`` state (already executed / rejected /
    expired / still awaiting email confirmation). The request's
    current state is included in ``details`` for the admin UI."""

    code = "gdpr.deletion_not_pending_admin"

    def __init__(self, current_state: str) -> None:
        super().__init__(
            (
                "This deletion request is not awaiting admin approval "
                f"(current state: {current_state})."
            ),
            details={"current_state": current_state},
        )


class MissingRejectionReason(BadRequestError):
    """Admin tried to reject a deletion request without supplying the
    required ``reason``. 400 (bad input), distinct from the 409 state
    errors the GDPR service raises."""

    code = "gdpr.missing_rejection_reason"


__all__ = [
    "GDPRError",
    "RetentionPeriodActive",
    "DeletionTokenInvalid",
    "DeletionTokenExpired",
    "DeletionRequestNotPending",
    "MissingRejectionReason",
]
