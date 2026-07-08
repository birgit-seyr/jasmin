"""Office-driven waiting-list promotion with member consent.

Flow:

1. A spot frees up (someone cancels, or the office raises capacity). The office
   sees the freed row light up on the waiting-list page and clicks *Notify*.
2. :meth:`WaitingListOfferService.offer_spot` **holds** the freed slot and emails
   the member a magic link.
3. The member opens the link and **accepts** (or declines) — no login needed.
   Accepting drops the subscription into the normal, not-yet-admin-confirmed abo
   flow (it leaves the waiting list); the office admin-confirms it the usual way.
4. If the member doesn't respond in time, a sweep job expires the offer and
   frees the slot again.

**Holds / race-safety.** Offering must reserve the slot for the whole response
window so a concurrent subscribe can't snipe it out from under the notified
member:

* **Station-day** — a :class:`CapacityReservation` (the existing TTL hold).
* **Variation** — the status-counted occupancy in
  :class:`VariationCapacityService`: a ``SPOT_AVAILABLE`` (offered) or
  ``CONFIRMED``-but-not-yet-admin-confirmed (accepted) subscription counts
  toward the farm-wide cap (see ``_occupying_q`` there). No extra table.

The offer itself is taken under the variation row lock (variation → station-day,
the canonical order) so two concurrent offers for the last share serialise.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from ..errors import (
    WaitingListOfferExpired,
    WaitingListOfferInvalid,
    WaitingListOfferNotAvailable,
)
from ..models import Subscription
from .capacity_reservation_service import CapacityReservationService
from .variation_capacity_service import VariationCapacityService
from .waiting_list_policy import assert_waiting_list_enabled, waiting_list_enabled

logger = logging.getLogger(__name__)

# How long the member has to respond to a "your spot is available" offer.
OFFER_EXPIRY_DAYS = 7


class WaitingListOfferService:
    @classmethod
    @transaction.atomic
    def offer_spot(
        cls,
        subscription,
        *,
        price_per_delivery=None,
        expiry_days: int = OFFER_EXPIRY_DAYS,
    ):
        """Offer a freed spot to a queued member: optionally re-price it, hold
        both capacity axes for the response window, flip the subscription to
        ``SPOT_AVAILABLE`` (which mints the magic-link token), and email the
        member.

        ``price_per_delivery`` lets the office set the price at offer time — a
        waiting_list entry can be a year old, so the office typically refreshes it to
        the current price before sending. When ``None`` the stored price stands.

        Only a ``PENDING`` waiting-list entry can be offered. Raises
        :class:`WaitingListOfferNotAvailable` otherwise, and the capacity errors
        (409) if a slot isn't actually free right now — the office's "available"
        view can go stale between render and click.
        """
        assert_waiting_list_enabled()
        if (
            not subscription.on_waiting_list
            or subscription.waiting_list_status
            != Subscription.WaitingListStatus.PENDING
        ):
            raise WaitingListOfferNotAvailable(
                "This subscription is not a pending waiting-list entry."
            )

        # Office-adjusted price (e.g. refreshed after a long wait) — applied
        # before the email so the member sees the FINAL price on the offer page.
        # Persisted by ``notify_spot_available``'s save below.
        if price_per_delivery is not None and price_per_delivery != "":
            from apps.shared.money import to_decimal

            subscription.price_per_delivery = to_decimal(price_per_delivery)

        # Confirm a slot is genuinely free NOW, under the row locks — variation
        # first (production cap), then station-day (logistics). ``reserve_for_
        # subscription`` both asserts the DSD cap and writes the hold. Either
        # gate being full raises the matching 409 and rolls back.
        VariationCapacityService.assert_capacity_available(subscription)
        CapacityReservationService.reserve_for_subscription(subscription)

        # Flip to SPOT_AVAILABLE (+ token + window). From here the subscription
        # itself counts toward the variation cap (status-counted hold), so no
        # concurrent subscribe can take the slot during the window.
        subscription.notify_spot_available(expiry_days=expiry_days)

        cls._send_offer_email(subscription)
        logger.info(
            "waiting_list.offer_sent subscription=%s member=%s expires=%s",
            subscription.pk,
            subscription.member_id,
            subscription.notification_expires_at,
        )
        return subscription

    @classmethod
    def get_open_offer(cls, token) -> Subscription | None:
        """The subscription behind an open (spot-available) offer token, or
        ``None``. Read-only — used to render the member's accept page. Returns
        ``None`` when the tenant has the waiting list off, so stale magic links
        render as an invalid offer."""
        if not token or not waiting_list_enabled():
            return None
        return (
            Subscription.objects.select_related(
                "member", "share_type_variation", "default_delivery_station_day"
            )
            .filter(
                notification_token=token,
                waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE,
            )
            .first()
        )

    @classmethod
    def accept_offer(cls, token) -> Subscription:
        """The member accepts: leave the waiting list as a normal,
        not-yet-admin-confirmed draft (``confirm_spot``). The variation hold
        continues via the accepted-pending occupancy clause and the station-day
        reservation persists until the office admin-confirms.

        Raises :class:`WaitingListOfferInvalid` for an unknown/consumed token and
        :class:`WaitingListOfferExpired` (freeing the slot) when the window lapsed.
        """
        assert_waiting_list_enabled()
        # Commit the outcome (expiry OR accept) inside the transaction, then
        # raise the "expired" error OUTSIDE it — raising inside would roll the
        # expiry + reservation release back, leaving a stale spot-available row.
        with transaction.atomic():
            subscription = cls._lock_open_offer(token)
            expired = subscription.has_expired_notification
            if expired:
                subscription.mark_as_expired()
                CapacityReservationService.release_for_subscription(subscription)
            else:
                subscription.confirm_spot()
        if expired:
            raise WaitingListOfferExpired(
                "This offer has expired. Please contact the office."
            )
        logger.info("waiting_list.offer_accepted subscription=%s", subscription.pk)
        return subscription

    @classmethod
    @transaction.atomic
    def decline_offer(cls, token) -> Subscription:
        """The member declines: leave the waiting list as DECLINED and free the
        held slot (drop the station-day reservation; the variation hold drops
        automatically once the status is no longer SPOT_AVAILABLE)."""
        assert_waiting_list_enabled()
        subscription = cls._lock_open_offer(token)
        subscription.decline_spot()
        CapacityReservationService.release_for_subscription(subscription)
        logger.info("waiting_list.offer_declined subscription=%s", subscription.pk)
        return subscription

    @classmethod
    def expire_stale_offers(cls) -> int:
        """Sweep: mark every SPOT_AVAILABLE offer past its window as EXPIRED and
        drop its station-day hold. Returns the count. Occupancy already ignores
        a lapsed offer (the ``notification_expires_at`` time check), so this is
        cleanup of the status + the reservation rows, not a correctness gate.
        """
        now = timezone.now()
        stale_ids = list(
            Subscription.objects.filter(
                waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE,
                notification_expires_at__lt=now,
            ).values_list("pk", flat=True)
        )
        count = 0
        for pk in stale_ids:
            with transaction.atomic():
                subscription = (
                    Subscription.objects.select_for_update().filter(pk=pk).first()
                )
                if (
                    subscription is None
                    or subscription.waiting_list_status
                    != Subscription.WaitingListStatus.SPOT_AVAILABLE
                ):
                    continue  # raced with an accept/decline
                subscription.mark_as_expired()
                CapacityReservationService.release_for_subscription(subscription)
                count += 1
        if count:
            logger.info("waiting_list.offers_expired count=%s", count)
        return count

    # ---- internals -----------------------------------------------------

    @staticmethod
    def _lock_open_offer(token) -> Subscription:
        if not token:
            raise WaitingListOfferInvalid("This offer link is invalid.")
        subscription = (
            Subscription.objects.select_for_update()
            .filter(
                notification_token=token,
                waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE,
            )
            .first()
        )
        if subscription is None:
            raise WaitingListOfferInvalid(
                "This offer link is invalid or has already been used."
            )
        return subscription

    @staticmethod
    def _send_offer_email(subscription) -> None:
        from apps.shared.deferred_email import schedule_deferred_email
        from apps.shared.invitations import _frontend_base_url, _tenant_name

        member = subscription.member
        variation = subscription.share_type_variation
        share_type = getattr(variation, "share_type", None) if variation else None
        station_day = subscription.default_delivery_station_day
        base_url = _frontend_base_url()
        accept_url = f"{base_url}/waiting-list-offer/{subscription.notification_token}"

        # Flatten to plain scalars — never hand a live ORM instance to the
        # tenant-editable email renderer.
        context = {
            "tenant_name": _tenant_name(),
            "member": {
                "first_name": getattr(member, "first_name", "") or "",
                "email": getattr(member, "email", "") or "",
            },
            "variation_name": getattr(share_type, "name", "") or "",
            "delivery_station_name": (
                getattr(station_day, "delivery_station_short_name", "") or ""
                if station_day
                else ""
            ),
            "valid_from": (
                subscription.valid_from.strftime("%d.%m.%Y")
                if subscription.valid_from
                else ""
            ),
            "expires_at": (
                subscription.notification_expires_at.strftime("%d.%m.%Y, %H:%M")
                if subscription.notification_expires_at
                else ""
            ),
            "accept_url": accept_url,
        }
        member_email = getattr(member, "email", "") or ""
        if not member_email:
            logger.warning(
                "waiting_list.offer_no_email subscription=%s member=%s",
                subscription.pk,
                subscription.member_id,
            )
            return
        schedule_deferred_email(
            slug="commissioning.waiting_list_offer",
            to_emails=[member_email],
            context=context,
            related_object_type="subscription",
            related_object_id=str(subscription.pk),
            language=getattr(member, "preferred_language", None) or None,
            logger=logger,
            log_error_event="waiting_list_offer.email_failed",
            log_not_sent_event="waiting_list_offer.email_not_sent",
            log_ref=f"subscription={subscription.pk}",
        )
