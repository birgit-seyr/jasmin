"""Cross-app subscription-change hook (commissioning extraction seam).

Commissioning owns subscriptions but must not import ``apps.payments`` —
its isolation is one-way (it will be extracted to its own project, and may
import only ``accounts`` / ``authz`` / ``shared``). When a subscription's
set of billable deliveries changes (admin-confirm, early cancel, opt-in
toggle) commissioning calls ``notify_subscription_changed(subscription)``
here; ``apps.payments`` registers a handler in its ``AppConfig.ready()``
that re-plans the charge schedule.

This inverts the dependency: commissioning depends only on this shared
module, never on the billing service. If payments is ever removed (the
extraction goal) ``notify_subscription_changed`` becomes a graceful no-op —
there is no billing app to re-plan, which is the correct behaviour.

Single handler slot on purpose: there is exactly one consumer (payments).
``set_subscription_changed_handler`` is idempotent, so re-running
``ready()`` (e.g. across test setups) just re-registers the same handler.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_handler: Callable[[Any], None] | None = None


def set_subscription_changed_handler(handler: Callable[[Any], None]) -> None:
    """Register the single handler invoked on subscription changes.

    Called once from ``apps.payments.apps.PaymentsConfig.ready()``.
    """
    global _handler
    _handler = handler


def notify_subscription_changed(subscription: Any) -> None:
    """Tell the registered handler that *subscription*'s billable deliveries
    changed so it can re-plan billing. No-op when no handler is registered
    (payments not installed).

    A registered handler's exceptions propagate by design: all callers run
    inside an ``@transaction.atomic`` block, so a billing-regen failure rolls
    back the confirm/cancel/toggle rather than committing a half-done change.
    Don't wrap this call in a try/except that would silently skip billing.
    """
    if _handler is not None:
        _handler(subscription)
