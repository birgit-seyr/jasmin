"""Email alerts to the platform operator (``ADMINS``) for events a log line alone
would leave unnoticed.

Container logs are kept in the server's journal, which nobody watches; an event
that needs a person also goes out as an email. An optional throttle keeps an
event that repeats (every lockout of an attack, a nightly sweep that finds the
same problem again) to one email per window; the caller's log line stays the
full record. A domain-free module, safe to import from any app.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.mail import mail_admins
from django.db import transaction

logger = logging.getLogger(__name__)


def alert_operator(
    subject: str,
    message: str,
    *,
    throttle_key: str | None = None,
    throttle_seconds: int = 0,
) -> None:
    """Email ``ADMINS`` once the current transaction commits, best-effort.

    With ``throttle_key``, at most one alert per key goes out within
    ``throttle_seconds``; later ones in the window are dropped. A failed send
    is logged and swallowed, and so is a cache error on the throttle (Redis
    down), in which case the alert goes out unthrottled: an alert never breaks
    the code that raises it.
    """
    if throttle_key is not None:
        try:
            first_in_window = cache.add(
                f"ops-alert:{throttle_key}", True, timeout=throttle_seconds
            )
        except Exception:
            logger.exception("ops_alert.throttle_failed key=%s", throttle_key)
        else:
            if not first_in_window:
                return

    def send() -> None:
        try:
            mail_admins(subject=f"[jasmin] {subject}", message=message)
        except Exception:
            logger.exception("ops_alert.failed subject=%s", subject)

    transaction.on_commit(send)
