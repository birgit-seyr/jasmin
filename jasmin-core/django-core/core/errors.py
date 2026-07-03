"""Jasmin-wide exception hierarchy.

Service-layer code raises one of these to signal a failure to the API caller.
The view layer does NOT need to catch them — the DRF exception handler
(``core.exception_handler.jasmin_exception_handler``) converts them into a
structured JSON response.

Standard response shape produced by ``to_dict()``::

    {
        "code":    "share.past_week",       # stable, machine-readable
        "message": "Cannot edit past weeks.",  # human-readable, translatable
        "field":   "delivery_week",         # optional, for form-field errors
        "details": {"year": 2024, "week": 14}  # optional, structured context
    }

Subclassing
-----------
Apps define their own domain-specific subclasses by inheriting from the
closest semantic match and overriding ``code``::

    from core.errors import NotFoundError

    class ShareNotFound(NotFoundError):
        code = "share.not_found"

This keeps the HTTP status correct automatically and lets callers do broad
catches like ``except NotFoundError`` when they want to handle any 404-shaped
domain error.
"""

from __future__ import annotations

from typing import Any


class JasminError(Exception):
    """Base for every domain error that should reach the API client.

    Subclasses override ``code`` and ``http_status``. Instances may override
    on the fly via the ``code=`` keyword if a single subclass needs to emit
    several stable codes (rare — usually prefer a new subclass).
    """

    code: str = "internal_error"
    http_status: int = 500

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code is not None:
            self.code = code
        self.field = field
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field:
            payload["field"] = self.field
        if self.details:
            payload["details"] = self.details
        return payload


class BadRequestError(JasminError):
    """Domain-level validation failed (invariants, business rules).

    Not the same as serializer/form validation — those raise
    ``rest_framework.exceptions.ValidationError`` or
    ``django.core.exceptions.ValidationError`` and are handled separately.
    Use ``BadRequestError`` for things like "cannot edit a finalized invoice"
    or "delivery_week is in the past".
    """

    code = "bad_request"
    http_status = 400


class InvalidQueryParam(BadRequestError):
    """A request query parameter (or body scalar) is missing, not parseable,
    or out of range. ``field`` names the offending parameter.

    Canonical home for the ``query.invalid_param`` code — apps re-export this
    rather than redefining it, so the stable code stays single-sourced.
    """

    code = "query.invalid_param"


class AuthError(JasminError):
    """Authentication failed: missing/invalid/expired credentials or token."""

    code = "auth_error"
    http_status = 401


class ForbiddenError(JasminError):
    """Caller is authenticated but lacks permission for this action."""

    code = "forbidden"
    http_status = 403


class NotFoundError(JasminError):
    """A requested resource does not exist (or is not visible to the caller)."""

    code = "not_found"
    http_status = 404


class ConflictError(JasminError):
    """Operation conflicts with current state.

    Examples: trying to delete a finalized delivery note, double-creating a
    record that has a unique business key, racing concurrent edits.
    """

    code = "conflict"
    http_status = 409


class RateLimitError(JasminError):
    """Caller exceeded a rate limit."""

    code = "rate_limited"
    http_status = 429


class InternalError(JasminError):
    """A "shouldn't happen" branch we want to surface with a stable code.

    Use this only when you've ruled out user error — i.e. it indicates a bug
    in our code, an external service outage, or a corrupted invariant. The
    exception handler logs these with a full traceback.
    """

    code = "internal_error"
    http_status = 500


__all__ = [
    "JasminError",
    "BadRequestError",
    "AuthError",
    "ForbiddenError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "InternalError",
]
