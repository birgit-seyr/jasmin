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

**Closed entries.** An entry whose subscription is cancelled or rejected, or
whose member has cancelled the membership or was rejected, is out of the
running (:func:`waiting_list_entry_closed`): an offer would hold a slot for an
application the office turned down, or for a member whose subscription the
confirm refuses. Such an entry is never offered a spot and its open offer can't
be accepted. Rejecting the subscription or the member, and the member's exit,
take the entry off the list and cancel its open offer
(:func:`withdraw_from_waiting_list`).

**Holds / race-safety.** Offering must reserve the slot for the whole response
window so a concurrent subscribe can't snipe it out from under the notified
member:

* **Station-day** — a :class:`CapacityReservation` (the existing TTL hold).
* **Variation** — the status-counted occupancy in
  :class:`VariationCapacityService`: a ``SPOT_AVAILABLE`` (offered) or
  ``CONFIRMED``-but-not-yet-admin-confirmed (accepted) subscription counts
  toward the farm-wide cap (see ``_occupying_q`` there). No extra table.

The offer itself is taken under the subscription's row lock, which serialises it
with a concurrent rejection or exit, and then under the variation row lock, so
two concurrent offers for the last share serialise (subscription → variation →
station-day, the order the subscription confirm takes them in).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.shared.display_formats import DisplayFormats
from apps.shared.money import fits_decimal_column, to_decimal

from ..errors import (
    SubscriptionPriceInvalid,
    WaitingListOfferEntryClosed,
    WaitingListOfferExpired,
    WaitingListOfferInvalid,
    WaitingListOfferMemberHasNoEmail,
    WaitingListOfferNotAvailable,
)
from ..models import DeliveryStationDay, Subscription
from .capacity_reservation_service import CapacityReservationService
from .solidarity_pricing import assert_price_meets_solidarity_floor
from .variation_capacity_service import VariationCapacityService
from .waiting_list_policy import assert_waiting_list_enabled, waiting_list_enabled

logger = logging.getLogger(__name__)

# How long the member has to respond to a "your spot is available" offer.
OFFER_EXPIRY_DAYS = 7


def offer_price_fits_column(amount: Decimal) -> bool:
    """Whether ``amount`` is storable in ``Subscription.price_per_delivery``.

    The offer price reaches this service outside any serializer, so nothing
    upstream holds it to the column. The model's own ``full_clean`` does catch
    an unstorable amount, but only at the save inside
    :meth:`WaitingListOfferService.offer_spot` — after the capacity hold has
    been taken — and as a bare ``ValidationError`` rather than a priced error
    the API can render.

    The bounds are read off the field so they can't drift from the column.
    """
    field = Subscription._meta.get_field("price_per_delivery")
    return fits_decimal_column(
        amount,
        max_digits=field.max_digits,
        decimal_places=field.decimal_places,
    )


def offer_station_name(station_day: DeliveryStationDay | None) -> str:
    """The pick-up station as a waiting-list offer names it: by its contact,
    else by its short name; "" without a station-day."""
    if station_day is None:
        return ""
    station = station_day.delivery_station
    contact_name = station.contact.name if station.contact else None
    return contact_name or station.short_name or ""


def waiting_list_entry_closed(subscription: Subscription) -> bool:
    """Whether ``subscription`` is out of the running for a freed spot: it was
    cancelled or rejected, or its member has cancelled the membership or was
    rejected. A member who has given notice counts as gone: outside onboarding
    mode, which makes no offers, the subscription confirm refuses their
    subscription whatever the exit date."""
    member = subscription.member
    return (
        subscription.cancelled_at is not None
        or subscription.admin_rejected_at is not None
        or member.cancelled_at is not None
        or member.admin_rejected_at is not None
    )


@transaction.atomic
def withdraw_from_waiting_list(subscriptions: QuerySet[Subscription]) -> list[str]:
    """Take the waiting-list entries among ``subscriptions`` off the list and
    cancel their open offers. Returns the ids of the entries withdrawn.

    An entry loses its queue position and an open offer its token, so the
    offer's magic link stops working. The station-day reservation the offer
    took is released the way a decline or an expiry releases it, and the
    variation hold ends with the spot-available status. Rows off the list
    without an open offer, accepted offers among them, are left as they are.

    The rows are written with ``update()``: a rejection or an exit must not fail
    on a term that the subscription's own validation has come to refuse.
    """
    entries = list(
        subscriptions.filter(
            Q(on_waiting_list=True)
            | Q(waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE)
        )
        .select_for_update(of=("self",))
        .order_by("pk")
    )
    if not entries:
        return []
    withdrawn_ids = [entry.pk for entry in entries]
    Subscription.objects.filter(pk__in=withdrawn_ids).update(
        on_waiting_list=False,
        waiting_list_status=Subscription.WaitingListStatus.NOT_ON_LIST,
        waiting_list_position=None,
        notification_token=None,
    )
    for entry in entries:
        CapacityReservationService.release_for_subscription(entry)
    logger.info("waiting_list.entries_withdrawn subscriptions=%s", withdrawn_ids)
    return withdrawn_ids


@transaction.atomic
def release_rejected_subscription(subscription: Subscription) -> None:
    """Free what a rejected subscription holds: its station-day reservation, and
    its place on the waiting list with any open offer."""
    withdraw_from_waiting_list(Subscription.objects.filter(pk=subscription.pk))
    CapacityReservationService.release_for_subscription(subscription)


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
        :class:`WaitingListOfferEntryClosed` for a closed entry (see
        :func:`waiting_list_entry_closed`), :class:`WaitingListOfferNotAvailable`
        for any other entry that isn't pending, and the capacity errors (409) if
        a slot isn't actually free right now — the office's "available" view can
        go stale between render and click.
        """
        assert_waiting_list_enabled()
        # Read the entry under its row lock. A rejection or an exit that
        # withdraws it at the same time either commits first, and the checks
        # below see it, or waits for this offer to commit and then cancels it.
        subscription = Subscription.objects.select_for_update().get(pk=subscription.pk)
        if waiting_list_entry_closed(subscription):
            raise WaitingListOfferEntryClosed(
                "No spot can be offered to this entry: the subscription was "
                "cancelled or rejected, or the member cancelled their membership "
                "or was rejected."
            )
        if (
            not subscription.on_waiting_list
            or subscription.waiting_list_status
            != Subscription.WaitingListStatus.PENDING
        ):
            raise WaitingListOfferNotAvailable(
                "This subscription is not a pending waiting-list entry."
            )
        if not subscription.member.email:
            raise WaitingListOfferMemberHasNoEmail(
                "The member has no email address to send the offer to."
            )

        # Office-adjusted price (e.g. refreshed after a long wait) — applied
        # before the email so the member sees the FINAL price on the offer page.
        # Persisted by ``notify_spot_available``'s save below.
        offered_price = subscription.price_per_delivery
        if price_per_delivery is not None and price_per_delivery != "":
            try:
                offered_price = to_decimal(price_per_delivery)
            except (InvalidOperation, ValueError, TypeError):
                raise SubscriptionPriceInvalid(price_per_delivery) from None
            # The column check screens out NaN, so the sign comparison only
            # ever sees a finite amount — comparing a NaN raises.
            if not offer_price_fits_column(offered_price) or offered_price < 0:
                raise SubscriptionPriceInvalid(price_per_delivery)

        # The offered price (new or stored) must clear the solidarity floor —
        # the same rule the subscription serializer applies. The member accepts
        # exactly this price, so an under-floor offer would lock into billing.
        assert_price_meets_solidarity_floor(
            price=offered_price,
            share_type_variation_id=subscription.share_type_variation_id,
            effective_date=subscription.valid_from,
            is_trial=subscription.is_trial,
        )
        subscription.price_per_delivery = offered_price

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
        ``None`` when the tenant has the waiting list off, and for a closed
        entry (see :func:`waiting_list_entry_closed`), whose offer can't be
        accepted, so such a link renders as an invalid offer."""
        if not token or not waiting_list_enabled():
            return None
        subscription = (
            Subscription.objects.select_related(
                "member", "share_type_variation", "default_delivery_station_day"
            )
            .filter(
                notification_token=token,
                waiting_list_status=Subscription.WaitingListStatus.SPOT_AVAILABLE,
            )
            .first()
        )
        if subscription is None or waiting_list_entry_closed(subscription):
            return None
        return subscription

    @classmethod
    def accept_offer(cls, token) -> Subscription:
        """The member accepts: leave the waiting list as a normal,
        not-yet-admin-confirmed draft (``confirm_spot``). The variation hold
        continues via the accepted-pending occupancy clause and the station-day
        reservation persists until the office admin-confirms.

        Raises :class:`WaitingListOfferInvalid` for an unknown/consumed token and
        for a closed entry (see :func:`waiting_list_entry_closed`), whose offer
        is withdrawn, freeing the slot; and :class:`WaitingListOfferExpired`
        (freeing the slot) when the window lapsed.
        """
        assert_waiting_list_enabled()
        # Commit the outcome (withdrawal, expiry OR accept) inside the
        # transaction, then raise the error OUTSIDE it — raising inside would
        # roll the withdrawal or expiry and its reservation release back,
        # leaving a stale spot-available row.
        with transaction.atomic():
            subscription = cls._lock_open_offer(token)
            closed = waiting_list_entry_closed(subscription)
            expired = not closed and subscription.has_expired_notification
            if closed:
                withdraw_from_waiting_list(
                    Subscription.objects.filter(pk=subscription.pk)
                )
            elif expired:
                subscription.mark_as_expired()
                CapacityReservationService.release_for_subscription(subscription)
            else:
                subscription.confirm_spot()
        if closed:
            # The answer an unknown or used link gets, so the link tells its
            # holder nothing about why the entry closed.
            raise WaitingListOfferInvalid(
                "This offer link is invalid or has already been used."
            )
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
        from apps.shared.tenant_urls import frontend_base_url, tenant_name

        member = subscription.member
        share_type = subscription.share_type_variation.share_type
        station_day = subscription.default_delivery_station_day
        base_url = frontend_base_url()
        accept_url = f"{base_url}/waiting-list-offer/{subscription.notification_token}"
        formats = DisplayFormats.current()

        # Flatten to plain scalars — never hand a live ORM instance to the
        # tenant-editable email renderer.
        context = {
            "tenant_name": tenant_name(),
            "member": {
                "first_name": member.first_name or "",
                "email": member.email or "",
            },
            "variation_name": share_type.name or "",
            "delivery_station_name": offer_station_name(station_day),
            "valid_from": formats.format_date(subscription.valid_from),
            # Set by ``notify_spot_available`` just before this email.
            "expires_at": formats.format_datetime(subscription.notification_expires_at),
            "accept_url": accept_url,
        }
        member_email = member.email or ""
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
            # The linked user's language, else the tenant's.
            language=(member.user.user_language or None) if member.user_id else None,
            logger=logger,
            log_error_event="waiting_list_offer.email_failed",
            log_not_sent_event="waiting_list_offer.email_not_sent",
            log_ref=f"subscription={subscription.pk}",
        )
