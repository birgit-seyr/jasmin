"""Notifications-app domain errors.

All subclasses of :class:`core.errors.JasminError`, so the global
exception handler renders them as the canonical
``{code, message, field?, details?}`` body with the right HTTP status —
views raise, they don't build ``Response`` objects by hand.
"""

from __future__ import annotations

from core.errors import BadRequestError, JasminError, NotFoundError


class EmailTemplateNotFound(NotFoundError):
    """No email template registered for the requested slug."""

    code = "email_template.not_found"


class UndeclaredPlaceholders(BadRequestError):
    """A tenant-edited subject/body references one or more ``{{ placeholder }}``
    paths that are not declared in the template's registry spec (and are not a
    trusted raw key). Such placeholders would render empty with no warning, so
    we reject them at edit time. The offending paths are returned in
    ``details["placeholders"]``."""

    code = "email_template.undeclared_placeholders"


class TestSendNoRecipient(BadRequestError):
    """Test send requested but neither a custom recipient nor the
    requesting user's email is available."""

    code = "email_template.test_send_no_recipient"


class EmailDispatchFailed(JasminError):
    """The upstream email provider/SMTP relay rejected or failed the send."""

    code = "email_template.dispatch_failed"
    http_status = 502


__all__ = [
    "EmailTemplateNotFound",
    "UndeclaredPlaceholders",
    "TestSendNoRecipient",
    "EmailDispatchFailed",
]
