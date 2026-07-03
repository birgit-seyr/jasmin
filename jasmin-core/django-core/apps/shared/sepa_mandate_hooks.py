"""Cross-app SEPA-mandate-revoked hook (commissioning extraction seam).

Commissioning owns consent (``ConsentService.revoke``) but must not import
``apps.payments`` — its isolation is one-way. When a member withdraws their
SEPA-mandate consent (Art. 7(3)), commissioning calls
``notify_sepa_mandate_revoked(member)`` here; ``apps.payments`` registers a
handler in its ``AppConfig.ready()`` that switches the member's
``BillingProfile`` off the SEPA direct-debit path so no future billing run
auto-debits them. No-op when payments isn't installed (the extraction goal).

Single handler slot on purpose — exactly one consumer (payments).
``set_sepa_mandate_revoked_handler`` is idempotent so re-running ``ready()``
just re-registers the same handler.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_handler: Callable[[Any], None] | None = None


def set_sepa_mandate_revoked_handler(handler: Callable[[Any], None]) -> None:
    """Register the single handler invoked when a member revokes SEPA consent.

    Called once from ``apps.payments.apps.PaymentsConfig.ready()``.
    """
    global _handler
    _handler = handler


def notify_sepa_mandate_revoked(member: Any) -> None:
    """Tell the registered handler that *member* withdrew SEPA-mandate consent
    so it can stop the direct-debit path. No-op when no handler is registered.

    Callers run inside ``ConsentService.revoke``'s ``@transaction.atomic``, so a
    handler exception rolls the revoke back rather than committing a revoked
    consent whose mandate is still live — don't wrap this in a swallowing
    try/except.
    """
    if _handler is not None:
        _handler(member)
