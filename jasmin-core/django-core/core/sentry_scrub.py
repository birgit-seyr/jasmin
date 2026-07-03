"""PII scrubbing for the Sentry/GlitchTip error-monitoring pipeline.

``send_default_pii=False`` stops Sentry auto-attaching ``user.email`` / IP, but
NOT PII the application itself put into a log message. INFO/WARNING log lines
become breadcrumbs on the next ERROR event (and the event's own message), which
land in the monitoring store beyond the reach of the GDPR erasure pipeline.
These hooks scrub email- and IPv4-shaped substrings from breadcrumb + event
messages — defence-in-depth on top of logging stable PKs (not emails) at the
call sites (GDPR-MIN-2/3).
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def scrub_pii(text):
    """Replace email- and IPv4-shaped substrings with placeholders. Non-strings
    pass through unchanged."""
    if not isinstance(text, str):
        return text
    return _IPV4_RE.sub("<ip>", _EMAIL_RE.sub("<email>", text))


def before_breadcrumb(crumb, _hint):
    """Sentry ``before_breadcrumb`` hook — scrub the breadcrumb message."""
    if crumb.get("message"):
        crumb["message"] = scrub_pii(crumb["message"])
    return crumb


def before_send(event, _hint):
    """Sentry ``before_send`` hook — scrub the event's own message and any
    breadcrumbs already attached to it."""
    logentry = event.get("logentry")
    if logentry and logentry.get("message"):
        logentry["message"] = scrub_pii(logentry["message"])
    breadcrumbs = event.get("breadcrumbs")
    values = (
        breadcrumbs.get("values", [])
        if isinstance(breadcrumbs, dict)
        else breadcrumbs or []
    )
    for crumb in values:
        if isinstance(crumb, dict) and crumb.get("message"):
            crumb["message"] = scrub_pii(crumb["message"])
    return event
