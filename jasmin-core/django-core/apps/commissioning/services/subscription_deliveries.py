"""Shared tail of the subscription-cancellation paths.

Both ``SubscriptionService.cancel_subscription`` (the Sunday-aligned office
cancel) and the member-exit ``_force_end_subscription`` end a subscription by
dropping its future deliveries, recomputing the affected shares'
stock/theoreticals, and re-planning charges. That block is byte-identical and
touches money (charge re-planning) + stock correctness (recompute after
delete), so it lives here with ONE definition — a future change to the date
boundary or the recompute set lands in a single place instead of silently
diverging the two paths. Per-path concerns (date-validation guards,
``valid_until`` truncation, ``cancelled_*`` stamping) stay in the callers.
"""

from __future__ import annotations

from typing import Any


def truncate_future_deliveries(subscription, *, cutoff_date) -> None:
    """Drop every ``ShareDelivery`` for ``subscription`` whose calendar date
    falls strictly after ``cutoff_date``, recompute the affected shares, and
    re-plan charges via the subscription-changed hook.

    Locked charges (ISSUED/PAID/FAILED/WAIVED) are preserved by the charge
    service; only future PLANNED rows drop. A subscription with no future
    delivery just fires the re-plan notify.
    """
    from apps.shared.subscription_hooks import notify_subscription_changed

    from ..models import ShareDelivery
    from ..utils.iso_week_utils import share_delivery_date
    from .recompute import recompute_shares

    future_delivery_ids: list[Any] = []
    affected_share_ids: set = set()
    for share_delivery in ShareDelivery.objects.filter(
        subscription=subscription
    ).select_related("share", "share__delivery_day"):
        delivery_date = share_delivery_date(share_delivery)
        if delivery_date and delivery_date > cutoff_date:
            future_delivery_ids.append(share_delivery.pk)
            if share_delivery.share_id:
                affected_share_ids.add(share_delivery.share_id)
    if future_delivery_ids:
        ShareDelivery.objects.filter(pk__in=future_delivery_ids).delete()
        recompute_shares(affected_share_ids)

    # Re-plan charges against the now-truncated term (payments reacts via the
    # subscription-changed hook).
    notify_subscription_changed(subscription)
