"""PII scrubbing for the Sentry/GlitchTip error-monitoring pipeline.

``send_default_pii=False`` stops Sentry auto-attaching ``user.email`` / IP, but
NOT PII the application itself put into a log message or an exception. INFO/
WARNING log lines become breadcrumbs on the next ERROR event (and the event's
own message), which land in the monitoring store beyond the reach of the GDPR
erasure pipeline. These hooks scrub email-, IPv4- and IBAN-shaped substrings
from breadcrumbs, the event's log entry (the template, the formatted text and
every string argument) and its exception values — defence-in-depth on top of
logging stable PKs (not emails) at the call sites.

Sentry's event shape is not a contract this code controls, so every hook skips
a part whose shape it does not recognise instead of raising: an exception in
``before_send`` would drop the whole event.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# Country code, check digits, then the account part either compact or in the
# printed groups of four. Upper case only: an IBAN is written that way, and the
# mixed-case record IDs must stay readable in the events.
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")


def scrub_pii(text):
    """Replace email-, IPv4- and IBAN-shaped substrings with placeholders.
    Non-strings pass through unchanged."""
    if not isinstance(text, str):
        return text
    text = _EMAIL_RE.sub("<email>", text)
    text = _IBAN_RE.sub("<iban>", text)
    return _IPV4_RE.sub("<ip>", text)


def before_breadcrumb(crumb, _hint):
    """Sentry ``before_breadcrumb`` hook — scrub the breadcrumb message."""
    if crumb.get("message"):
        crumb["message"] = scrub_pii(crumb["message"])
    return crumb


def _scrub_logentry(logentry) -> None:
    if not isinstance(logentry, dict):
        return
    for key in ("message", "formatted"):
        if logentry.get(key):
            logentry[key] = scrub_pii(logentry[key])
    params = logentry.get("params")
    if isinstance(params, list | tuple):
        logentry["params"] = [scrub_pii(param) for param in params]
    elif isinstance(params, dict):
        logentry["params"] = {name: scrub_pii(param) for name, param in params.items()}


def _entries(container) -> list:
    """The ``values`` list of a Sentry interface that may arrive either as
    ``{"values": [...]}`` or as the bare list."""
    entries = container.get("values") if isinstance(container, dict) else container
    return entries if isinstance(entries, list) else []


def before_send(event, _hint):
    """Sentry ``before_send`` hook — scrub the event's log entry, its exception
    values and any breadcrumbs already attached to it."""
    _scrub_logentry(event.get("logentry"))
    for exception in _entries(event.get("exception")):
        if isinstance(exception, dict) and exception.get("value"):
            exception["value"] = scrub_pii(exception["value"])
    for crumb in _entries(event.get("breadcrumbs")):
        if isinstance(crumb, dict) and crumb.get("message"):
            crumb["message"] = scrub_pii(crumb["message"])
    return event
