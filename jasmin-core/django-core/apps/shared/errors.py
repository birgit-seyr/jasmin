"""Errors raised by the shared modules directly under ``apps/shared/``.

Subclasses of :class:`core.errors.JasminError`, so the DRF exception handler
renders them as the canonical ``{code, message, field?, details?}`` body with
the right HTTP status. The shared sub-apps (``tenants``, ``super_admin``,
``support``) keep their own ``errors.py``.
"""

from __future__ import annotations

from core.errors import ForbiddenError


class CrossOriginRequestRefused(ForbiddenError):
    """A browser request from another origin reached an endpoint that sets,
    reads or rotates a refresh cookie (see ``apps.shared.same_origin``).

    403, not 401: the frontend answers a 401 with a silent refresh, which would
    hide the refusal behind a "session expired" message.
    """

    code = "auth.cross_origin_refused"


__all__ = ["CrossOriginRequestRefused"]
