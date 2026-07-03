"""Tiny request-scoped helpers shared across apps.

Currently exposes :func:`client_ip`, which extracts the originating client
IP from a DRF / Django ``HttpRequest``. Six copies of this helper used to
live in views / signals / permissions — they were identical except for a
``None`` guard in one place, which is preserved here.
"""

from __future__ import annotations

from django.conf import settings


def client_ip(request) -> str:
    """Return the originating client IP, honoring ``X-Forwarded-For``.

    The gateway nginx appends the real client IP to any client-supplied
    ``X-Forwarded-For`` (``$proxy_add_x_forwarded_for``), so the trusted
    value is the entry ``TRUSTED_PROXY_COUNT`` positions FROM THE RIGHT —
    NOT the leftmost entry, which the client fully controls. Reading the
    leftmost entry let an attacker forge the IP recorded in the
    security / consent / GDPR audit trails. This mirrors DRF's
    ``NUM_PROXIES`` and axes' ``AXES_IPWARE_PROXY_COUNT`` (all driven by
    ``TRUSTED_PROXY_COUNT``) so the recorded forensic IP matches the value
    used for throttle / lockout keying.

    Falls back to ``REMOTE_ADDR`` and finally to an empty string if the
    request is missing (e.g. when an auditlog signal fires outside an HTTP
    cycle).
    """
    if request is None:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        parts = [part.strip() for part in xff.split(",") if part.strip()]
        if parts:
            proxy_count = getattr(settings, "TRUSTED_PROXY_COUNT", 1) or 1
            return parts[-min(proxy_count, len(parts))]
    return request.META.get("REMOTE_ADDR", "")
