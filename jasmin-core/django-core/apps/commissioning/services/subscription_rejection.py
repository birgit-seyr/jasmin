"""Rejecting a pending subscription application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from ..errors import SubscriptionAlreadyConfirmed
from ..models import Subscription
from .waiting_list_offer_service import release_rejected_subscription

if TYPE_CHECKING:
    from apps.accounts.models import JasminUser


@transaction.atomic
def reject_subscription(
    subscription: Subscription, *, admin_user: JasminUser, reason: str | None
) -> Subscription:
    """Reject the pending `subscription` and free what it holds.

    Decides on the row under the lock ``confirm`` takes. Checked on an unlocked
    read, a confirm committing in between would be undone here: a "rejected"
    subscription whose deliveries and PLANNED charges are still there, and still
    billed.

    No email goes out: subscriptions don't ship a
    ``subscription.application_rejected`` template yet. Add the wiring
    alongside the template if product asks.
    """
    subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)

    # ``reject`` is for PENDING applications only. Rejecting an already
    # CONFIRMED subscription would merely un-flip the flag while leaving its
    # materialised ShareDeliveries and PLANNED ChargeSchedule rows intact —
    # those are still SEPA-debited (create_run filters on status=PLANNED, not
    # admin_confirmed). Genuine revocation of a confirmed subscription must
    # route through ``cancel`` (which drops future deliveries + PLANNED charges
    # and re-plans). Already-rejected rows stay idempotent (admin_confirmed is
    # False).
    if subscription.admin_confirmed:
        raise SubscriptionAlreadyConfirmed(
            "Confirmed subscriptions cannot be rejected — cancel them instead."
        )
    subscription.reject(admin_user=admin_user, reason=reason, save=True)

    # Free what the rejected draft holds. The reject stamps flags but does NOT
    # delete the row, so the CASCADE that would otherwise drop the
    # CapacityReservation never fires — without this, the rejected applicant
    # keeps blocking the slot until the 14-day TTL lapses, and the link of an
    # open waiting-list offer keeps working.
    release_rejected_subscription(subscription)
    return subscription
