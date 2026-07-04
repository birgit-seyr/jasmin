from __future__ import annotations

import datetime
import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from isoweek import Week

from apps.shared.subscription_hooks import notify_subscription_changed

from ..errors import (
    CancellationAfterValidUntil,
    CancellationBeforeValidFrom,
    CancellationInPast,
    CancellationNotSunday,
    NoSundayRemainsInTerm,
    SubscriptionDeliveryStationDayOutOfRange,
    SubscriptionNotConfirmed,
)
from ..models import (
    DeliveryStationDay,
    Member,
    Share,
    ShareDelivery,
    SharesDeliveryDay,
    ShareTypeVariation,
    Subscription,
)
from .capacity_reservation_service import CapacityReservationService
from .delivery_cycle import filter_weeks_by_delivery_cycle

logger = logging.getLogger(__name__)


def _delivery_cycle_of(subscription: Subscription) -> str | None:
    """The ``ShareType.delivery_cycle`` governing this subscription's cadence,
    or ``None`` (→ weekly) when any link in the chain is missing."""
    variation = getattr(subscription, "share_type_variation", None)
    share_type = getattr(variation, "share_type", None)
    return getattr(share_type, "delivery_cycle", None)


class SubscriptionService:
    """Creates subscriptions and their associated Share/ShareDelivery objects."""

    @staticmethod
    def assert_delivery_station_day_covers_subscription(
        *,
        delivery_station_day: DeliveryStationDay | None,
        valid_from: datetime.date | None,
        valid_until: datetime.date | None,
    ) -> None:
        """Validate that the chosen DeliveryStationDay's validity covers the
        subscription's validity (with chained successors when needed).

        Exposed as a staticmethod so both ``Subscription.clean()`` and any
        bulk path (``bulk_create`` / ``bulk_update``) can call the same
        logic.
        """
        if not delivery_station_day or not valid_from:
            return

        if (
            delivery_station_day.valid_from
            and delivery_station_day.valid_from > valid_from
        ):
            raise SubscriptionDeliveryStationDayOutOfRange(
                f"Delivery station day starts ({delivery_station_day.valid_from}) "
                f"after subscription start ({valid_from})",
                field="default_delivery_station_day",
            )

        if (
            valid_until
            and delivery_station_day.valid_until
            and delivery_station_day.valid_until < valid_until
        ):
            # The default DSD ends before the subscription. Its successor chain
            # (same station + day_number) must cover the REST of the window
            # CONTIGUOUSLY through valid_until — proving merely that SOME later
            # DSD exists is not enough: a successor that starts weeks later (a
            # gap) or itself ends early leaves weeks with no valid station day.
            successors = DeliveryStationDay.objects.filter(
                delivery_station=delivery_station_day.delivery_station,
                delivery_day__day_number=delivery_station_day.delivery_day.day_number,
                valid_from__gt=delivery_station_day.valid_from,
            ).order_by("valid_from")
            covered_until = delivery_station_day.valid_until
            for successor in successors:
                if covered_until >= valid_until:
                    break
                if successor.valid_from > covered_until + timedelta(days=1):
                    break  # gap — coverage stays short, raised below
                if successor.valid_until is None:
                    covered_until = valid_until
                    break
                if successor.valid_until > covered_until:
                    covered_until = successor.valid_until
            if covered_until < valid_until:
                raise SubscriptionDeliveryStationDayOutOfRange(
                    f"Delivery station day coverage ends ({covered_until}) "
                    f"before subscription ends ({valid_until}): the successor "
                    "chain has a gap or ends too early.",
                    field="default_delivery_station_day",
                )

    @transaction.atomic
    def create_bare_subscription(self, validated_data: dict[str, Any]) -> Subscription:
        """Create the Subscription row only.

        Shares + ShareDeliveries are NOT created here. They are materialised
        on admin-confirmation (see ``materialize_confirmed_subscription``),
        because we don't want delivery / billing artefacts for subscriptions
        that may still be rejected.

        The draft DOES reserve its station-day capacity across the period so
        two drafts can't both claim the last slot — race-safe, and rolled back
        with the create if a week is full (``DeliveryStationOverCapacity``).

        Waiting-list entries (``on_waiting_list=True``) are the exception:
        they hold NO capacity — no reservation now, no deliveries until the
        office promotes them through the normal confirm flow (which re-checks
        capacity). They only get a PENDING status and a FIFO queue position.
        """
        subscription = self._create_subscription(validated_data)
        if subscription.on_waiting_list:
            self._enqueue_on_waiting_list(subscription)
        else:
            CapacityReservationService.reserve_for_subscription(subscription)
        return subscription

    @staticmethod
    def _enqueue_on_waiting_list(subscription: Subscription) -> None:
        """Mark the draft as a PENDING waiting-list entry with the next FIFO
        position for its station-day. The position is informational — the
        office may promote out of order."""
        highest = (
            Subscription.objects.filter(
                on_waiting_list=True,
                default_delivery_station_day_id=(
                    subscription.default_delivery_station_day_id
                ),
            )
            .exclude(pk=subscription.pk)
            .aggregate(highest=Max("waiting_list_position"))["highest"]
        )
        subscription.waiting_list_status = Subscription.WaitingListStatus.PENDING
        subscription.waiting_list_position = (highest or 0) + 1
        subscription.save(
            update_fields=["waiting_list_status", "waiting_list_position"]
        )

    @transaction.atomic
    def update_draft_subscription(
        self,
        subscription: Subscription,
        validated_data: dict[str, Any],
    ) -> Subscription:
        """Apply `validated_data` to a draft (unconfirmed) subscription.

        No related-object cascade is needed because draft subscriptions
        don't yet have shares / deliveries / charges. Caller must ensure
        ``subscription.admin_confirmed is False``.
        """
        previous_station_day_id = subscription.default_delivery_station_day_id
        was_waitlisted = subscription.on_waiting_list
        for field, value in validated_data.items():
            # ``member`` and ``share_type_variation`` are writable id STRINGS on
            # the serializer (CharField) — mirror ``_create_subscription`` and
            # assign them to the FK's ``_id`` attribute. Django rejects a raw pk
            # on the plain FK attribute ("must be a Member instance"); other FK
            # fields arrive as model instances and set directly.
            if field in ("member", "share_type_variation") and isinstance(value, str):
                setattr(subscription, f"{field}_id", value)
            else:
                setattr(subscription, field, value)
        subscription.save()
        if subscription.on_waiting_list:
            # Waitlisted drafts hold no capacity, so there is nothing to
            # re-reserve (reserving would 409 on the very full station the
            # entry is queued for).
            if not was_waitlisted:
                # Draft flipped ONTO the list: drop its capacity holds (a
                # waitlist entry holds nothing) and queue it.
                CapacityReservationService.release_for_subscription(subscription)
                self._enqueue_on_waiting_list(subscription)
            elif (
                subscription.default_delivery_station_day_id != previous_station_day_id
            ):
                # Moving the entry to another station-day re-queues it at the
                # end of that day's list.
                self._enqueue_on_waiting_list(subscription)
            return subscription
        if was_waitlisted:
            # Leaving the list needs a real slot: reserve first (raises
            # DeliveryStationOverCapacity while the station is full — the flip
            # rolls back), then clear the queue state.
            CapacityReservationService.reserve_for_subscription(subscription)
            subscription.waiting_list_status = (
                Subscription.WaitingListStatus.NOT_ON_LIST
            )
            subscription.waiting_list_position = None
            subscription.save(
                update_fields=["waiting_list_status", "waiting_list_position"]
            )
            return subscription
        # Re-reserve against the (possibly changed) station-day / period.
        CapacityReservationService.reserve_for_subscription(subscription)
        return subscription

    @transaction.atomic
    def materialize_confirmed_subscription(
        self, subscription: Subscription
    ) -> Subscription:
        """Create Shares + ShareDeliveries + ChargeSchedule for a freshly
        confirmed subscription.

        Idempotent for re-confirmation: existing ShareDeliveries for the sub
        are kept; only missing ones are created. Charge regeneration is
        delegated to ``ChargeScheduleService`` which itself protects locked
        (issued/paid/…) rows.
        """
        if not subscription.valid_from or not subscription.valid_until:
            logger.info(
                "Subscription %s missing valid_from/until; skipping materialise",
                subscription.pk,
            )
            return subscription
        if not subscription.default_delivery_station_day_id:
            logger.info(
                "Subscription %s has no default DSD; skipping materialise",
                subscription.pk,
            )
            return subscription

        # Only create ShareDeliveries if none exist yet — re-confirm is a no-op
        # for the delivery side; the charge service handles its own diffing.
        if not ShareDelivery.objects.filter(subscription=subscription).exists():
            # Race-safe backstop: the draft reserved these slots, but the hold
            # may have lapsed (TTL) and been taken in the meantime. Re-check
            # under a row lock before materialising; raises
            # ``DeliveryStationOverCapacity`` (and rolls back) if a week is now
            # full. Then drop our reservations — the real deliveries hold the
            # slots from here, so keeping them would double-count.
            CapacityReservationService.assert_capacity_available_for_confirm(
                subscription
            )
            shares = self._create_shares(subscription)
            self._create_share_deliveries(subscription, shares)
            CapacityReservationService.release_for_subscription(subscription)

        if subscription.on_waiting_list:
            # The office confirmed a waitlisted subscription: the capacity
            # backstop above proved a slot is free now (waitlist entries hold
            # no reservation, so the check counts everyone else). This IS the
            # promotion — leave the waiting list and record the confirmation.
            subscription.confirm_spot()

        notify_subscription_changed(subscription)
        return subscription

    @transaction.atomic
    def cancel_subscription(
        self,
        subscription: Subscription,
        *,
        cancelled_by: Any,
        effective_at: datetime.date,
        reason: str | None = None,
    ) -> Subscription:
        """End a confirmed subscription early (e.g. member died).

        - Sets CancellableMixin fields.
        - Truncates ``valid_until`` to ``effective_at`` so reports/queries see
          the new end immediately.
        - Deletes all future ShareDeliveries (those whose share's ISO date is
          strictly after ``effective_at``).
        - Drops PLANNED ChargeSchedule rows that start after ``effective_at``
          and re-runs the schedule for the truncated term.
        ISSUED/PAID/FAILED/WAIVED charges are NEVER touched.
        """
        if not subscription.admin_confirmed:
            raise SubscriptionNotConfirmed(
                "Only admin-confirmed subscriptions can be cancelled."
            )
        # Idempotency: a re-cancel is a no-op that preserves the ORIGINAL
        # cancellation audit stamp (cancelled_at / cancelled_by /
        # cancelled_effective_at) and the already-truncated valid_until, and must
        # NOT re-truncate the term, delete further deliveries, or re-fire the
        # payments hook. Mirrors cancel_member_with_coop_shares' cancelled_at guard.
        if subscription.cancelled_at is not None:
            return subscription
        # ``effective_at`` becomes the new ``valid_until`` further down,
        # and ``TimeBoundMixin`` requires ``valid_until`` to fall on a
        # Sunday (Python ``weekday() == 6``). Enforce that up front so
        # the office sees a clean error instead of a model-level
        # ValidationError later in the same transaction.
        if effective_at.weekday() != 6:
            raise CancellationNotSunday(
                "effective_at must fall on a Sunday — cancellations are "
                "aligned with the end-of-delivery-week boundary."
            )
        # Lower bound 1: never in the past. The earliest a cancellation
        # can take effect is the **next Sunday** (today if today IS
        # Sunday). Past dates are nonsense — there is no "we already
        # delivered last week" undo.
        from ..utils.iso_week_utils import next_sunday

        today = timezone.localdate()
        next_sunday_date = next_sunday(today)
        if effective_at < next_sunday_date:
            raise CancellationInPast(
                "effective_at must be on or after the next Sunday "
                f"({next_sunday_date.isoformat()}). Cancellation cannot "
                "take effect in the past."
            )
        # Lower bound 2: still respect valid_from for future-dated
        # subscriptions (rare — a subscription scheduled to start in two
        # months can't be cancelled before it has begun).
        if effective_at < subscription.valid_from:
            raise CancellationBeforeValidFrom(
                "effective_at must be on or after the subscription's valid_from."
            )
        # Upper bound — cancelling on or before the term's natural end is
        # the only meaningful case. Anything past ``valid_until`` is a
        # no-op (the subscription is already over) and would silently
        # *extend* the term via the ``valid_until = effective_at`` line
        # below. Refuse so the office can't accidentally do that.
        if (
            subscription.valid_until is not None
            and effective_at > subscription.valid_until
        ):
            raise CancellationAfterValidUntil(
                "effective_at must be on or before the subscription's valid_until."
            )
        # If the next-Sunday floor is already past the natural term end,
        # there is no Sunday left to cancel into. This matches the
        # frontend rule that hides the Cancel button on rows that are
        # already too close to their natural expiry.
        if (
            subscription.valid_until is not None
            and next_sunday_date > subscription.valid_until
        ):
            raise NoSundayRemainsInTerm(
                "There is no valid Sunday between today and the "
                "subscription's end date — let the term expire naturally."
            )

        subscription.cancelled_at = timezone.now()
        subscription.cancelled_by = cancelled_by
        subscription.cancelled_effective_at = effective_at
        # Truncate the term so future logic stops scheduling past this date.
        if subscription.valid_until is None or subscription.valid_until > effective_at:
            subscription.valid_until = effective_at
        subscription.save()

        # Drop future deliveries past the cancellation date, recompute the
        # affected shares, and re-plan charges (shared with the member-exit
        # path; locked ISSUED/PAID/FAILED/WAIVED charges are preserved).
        from .subscription_deliveries import truncate_future_deliveries

        truncate_future_deliveries(subscription, cutoff_date=effective_at)

        if reason:
            subscription.cancellation_reason = reason
            subscription.save(update_fields=["cancellation_reason"])

        return subscription

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @transaction.atomic
    def _create_subscription(self, validated_data: dict[str, Any]) -> Subscription:
        member_id = validated_data.pop("member")
        share_type_variation_id = validated_data.pop("share_type_variation")
        pickup_name = validated_data.pop("pickup_name", None)

        # Fetch both FKs in a single round-trip where possible
        member_obj = Member.objects.get(id=member_id)
        share_type_variation_obj = ShareTypeVariation.objects.get(
            id=share_type_variation_id
        )

        if pickup_name is not None:
            member_obj.pickup_name = pickup_name
            member_obj.save(update_fields=["pickup_name"])

        validated_data["member"] = member_obj
        validated_data["share_type_variation"] = share_type_variation_obj
        return Subscription.objects.create(**validated_data)

    @staticmethod
    def _get_delivery_weeks(
        start_date: datetime.date,
        end_date: datetime.date,
        delivery_day: int,
        delivery_cycle: str | None = None,
    ) -> list[tuple[int, int]]:
        """Return ``(year, isoweek)`` tuples between *start_date* and *end_date*
        that contain the given *delivery_day* (0=Monday … 5=Saturday).

        When *delivery_cycle* (``ShareType.delivery_cycle``) is given, the full
        weekly cadence is reduced to that cycle's delivery weeks: WEEKLY/blank →
        every week, ODD_WEEKS/EVEN_WEEKS → matching ISO-week parity, and the
        month-based cycles → every Nth week. See services/delivery_cycle.py.
        """
        # Convert delivery_day (0-5) to isoweekday (1-6)
        iso_delivery_day = delivery_day + 1

        current_date = start_date
        days_ahead = iso_delivery_day - current_date.isoweekday()
        if days_ahead < 0:
            days_ahead += 7
        current_date += timedelta(days=days_ahead)

        delivery_weeks: list[tuple[int, int]] = []
        while current_date <= end_date:
            year, week, _ = current_date.isocalendar()
            delivery_weeks.append((year, week))
            current_date += timedelta(days=7)

        # Reduce the full weekly cadence to the configured cycle's delivery weeks
        # (WEEKLY keeps all; ODD/EVEN by parity; ALL_THREE/ALL_FOUR by stride).
        return filter_weeks_by_delivery_cycle(delivery_weeks, delivery_cycle)

    @staticmethod
    def resolve_station_days_by_week(
        subscription: Subscription,
    ) -> dict[tuple[int, int], DeliveryStationDay]:
        """Map each delivery week of *subscription* to the DeliveryStationDay
        that will actually hold its ShareDelivery: the default DSD when it is
        open-ended, else the per-week successor resolved from the station's
        time-bounded chain (mirrors the resolution in
        ``_create_share_deliveries``). Empty when the subscription consumes no
        station-day (no default DSD or missing dates).

        Capacity enforcement uses this so it reserves/checks the SAME DSD that
        materialization will write to, not just the default DSD.
        """
        default_delivery_station_day = subscription.default_delivery_station_day
        if (
            not default_delivery_station_day
            or not subscription.valid_from
            or not subscription.valid_until
        ):
            return {}

        day_number = default_delivery_station_day.delivery_day.day_number
        year_weeks = SubscriptionService._get_delivery_weeks(
            subscription.valid_from,
            subscription.valid_until,
            day_number,
            _delivery_cycle_of(subscription),
        )
        if not year_weeks:
            return {}

        # A DeliveryExceptionPeriod ("Lieferpause") suppresses ShareDelivery
        # materialisation in its weeks (mirrors the filter in _create_shares), so
        # those weeks consume NO station-day slot. Exclude them here too — else the
        # capacity paths (reserve_for_subscription / assert_capacity_available_for_
        # confirm) would reserve/count phantom occupancy for weeks that are never
        # delivered, and resync's restore would re-create a still-paused week.
        from .delivery_exceptions import paused_weeks_for_variation

        paused = paused_weeks_for_variation(
            subscription.share_type_variation_id, year_weeks
        )
        if paused:
            year_weeks = [
                year_week for year_week in year_weeks if year_week not in paused
            ]
            if not year_weeks:
                return {}

        # Open-ended default DSD covers every week — the common fast path.
        if default_delivery_station_day.valid_until is None:
            return {year_week: default_delivery_station_day for year_week in year_weeks}

        mondays = {
            year_week: Week(year_week[0], year_week[1]).monday()
            for year_week in year_weeks
        }
        candidates = list(
            DeliveryStationDay.objects.filter(
                delivery_station=default_delivery_station_day.delivery_station,
                delivery_day__day_number=day_number,
                valid_from__lte=max(mondays.values()) + timedelta(days=6),
            )
            .exclude(valid_until__lt=min(mondays.values()))
            .select_related("delivery_day")
            # Deterministic tie-break: if two rows ever overlap a week, the
            # _active() loop picks the latest valid_from rather than an
            # arbitrary DB order.
            .order_by("-valid_from")
        )

        def _active(active_at: datetime.date) -> DeliveryStationDay | None:
            for delivery_station_day in candidates:
                if delivery_station_day.valid_from <= active_at and (
                    delivery_station_day.valid_until is None
                    or delivery_station_day.valid_until >= active_at
                ):
                    return delivery_station_day
            return None

        # Fall back to the default DSD when no successor covers a week (mirrors
        # _create_share_deliveries, which warns + materializes onto it).
        return {
            year_week: (_active(mondays[year_week]) or default_delivery_station_day)
            for year_week in year_weeks
        }

    @transaction.atomic
    def _create_shares(self, subscription: Subscription) -> list[Share]:
        delivery_day_obj = subscription.default_delivery_station_day.delivery_day
        share_type_variation = subscription.share_type_variation

        delivery_weeks = self._get_delivery_weeks(
            subscription.valid_from,
            subscription.valid_until,
            delivery_day_obj.day_number,
            _delivery_cycle_of(subscription),
        )

        if not delivery_weeks:
            return []

        # Skip weeks paused by a DeliveryExceptionPeriod ("Lieferpause") for this
        # variation: no Share / ShareDelivery is materialised there, so the week
        # produces no demand and — billing being delivery-driven — no charge.
        from .delivery_exceptions import paused_weeks_for_variation

        paused = paused_weeks_for_variation(share_type_variation.id, delivery_weeks)
        if paused:
            delivery_weeks = [
                year_week for year_week in delivery_weeks if year_week not in paused
            ]
            if not delivery_weeks:
                return []

        # Pre-fetch existing shares to avoid N+1 get_or_create calls
        existing_shares = {
            (s.year, s.delivery_week, s.delivery_day_id): s
            for s in Share.objects.filter(
                year__in={y for y, _ in delivery_weeks},
                delivery_week__in={w for _, w in delivery_weeks},
                share_type_variation=share_type_variation,
            ).select_related("delivery_day")
        }

        delivery_day_stays_the_same = delivery_day_obj.valid_until is None

        if delivery_day_stays_the_same:
            return self._create_shares_static_day(
                delivery_weeks, delivery_day_obj, share_type_variation, existing_shares
            )
        return self._create_shares_dynamic_day(
            delivery_weeks,
            delivery_day_obj,
            subscription,
            share_type_variation,
            existing_shares,
        )

    def _create_shares_static_day(
        self,
        delivery_weeks: list[tuple[int, int]],
        delivery_day_obj: SharesDeliveryDay,
        share_type_variation: ShareTypeVariation,
        existing_shares: dict[tuple[int, int, str], Share],
    ) -> list[Share]:
        shares: list[Share] = []
        for year, week in delivery_weeks:
            key = (year, week, delivery_day_obj.id)
            if key in existing_shares:
                shares.append(existing_shares[key])
            else:
                share, _ = Share.get_or_create_for_delivery(
                    year=year,
                    delivery_week=week,
                    delivery_day=delivery_day_obj,
                    share_type_variation=share_type_variation,
                )
                shares.append(share)
        return shares

    def _create_shares_dynamic_day(
        self,
        delivery_weeks: list[tuple[int, int]],
        delivery_day_obj: SharesDeliveryDay,
        subscription: Subscription,
        share_type_variation: ShareTypeVariation,
        existing_shares: dict[tuple[int, int, str], Share],
    ) -> list[Share]:
        day_number = delivery_day_obj.day_number

        # Batch-fetch active delivery days for all weeks to avoid N+1
        monday_dates = [Week(y, w).monday() for y, w in delivery_weeks]
        min_date = min(monday_dates)
        max_date = max(monday_dates) + timedelta(days=6)
        candidate_days = list(
            # ``.objects`` (not ``.current``) to match the sibling DSD resolvers
            # and so historical rows for PAST weeks aren't pre-filtered out — the
            # date-range filter below + _find_active_day do the validity scoping.
            SharesDeliveryDay.objects.filter(day_number=day_number)
            .filter(valid_from__lte=max_date)
            .exclude(valid_until__lt=min_date)
            .order_by("-valid_from")
        )

        def _find_active_day(
            active_at: datetime.date,
        ) -> SharesDeliveryDay | None:
            for day in candidate_days:
                if day.valid_from <= active_at and (
                    day.valid_until is None or day.valid_until >= active_at
                ):
                    return day
            return None

        shares: list[Share] = []
        for (year, week), monday in zip(delivery_weeks, monday_dates, strict=True):
            current_delivery_day = _find_active_day(monday)
            if current_delivery_day is None:
                logger.error(
                    "No active delivery day for day_number=%s at %s", day_number, monday
                )
                continue

            key = (year, week, current_delivery_day.id)
            if key in existing_shares:
                shares.append(existing_shares[key])
            else:
                share, _ = Share.get_or_create_for_delivery(
                    year=year,
                    delivery_week=week,
                    delivery_day=current_delivery_day,
                    share_type_variation=share_type_variation,
                )
                shares.append(share)
        return shares

    @staticmethod
    @transaction.atomic
    def _create_share_deliveries(
        subscription: Subscription, shares: list[Share]
    ) -> list[ShareDelivery]:
        default_delivery_station_day = subscription.default_delivery_station_day
        delivery_day_obj = default_delivery_station_day.delivery_day

        # bulk_create() below bypasses ShareDelivery.save(), which is the only
        # place is_opted_in gets stamped from the variation's default_optin_state.
        # Without this, an on-by-default opt-in variation would be born opted-OUT
        # — silently suppressing both its billing and its production demand.
        variation = subscription.share_type_variation
        is_opted_in = bool(
            variation and variation.requires_optin and variation.default_optin_state
        )

        # If the default DSD itself is open-ended it covers every week — use it
        # for all shares. This must check the DeliveryStationDay's OWN
        # valid_until, NOT delivery_day (the SharesDeliveryDay / day-of-week,
        # which is normally open): a default DSD that expires mid-subscription
        # must fall through to the per-week dynamic resolution below, otherwise
        # every week gets pinned to the expired station day.
        if default_delivery_station_day.valid_until is None:
            share_deliveries = [
                ShareDelivery(
                    subscription=subscription,
                    share=share,
                    delivery_station_day=default_delivery_station_day,
                    joker_taken=False,
                    is_opted_in=is_opted_in,
                )
                for share in shares
            ]
            ShareDelivery.objects.bulk_create(share_deliveries)
            from .recompute import recompute_shares

            try:
                recompute_shares(s.id for s in shares)
            except Exception:
                # Re-raise so the outer @transaction.atomic still rolls the
                # just-created deliveries back; add the subscription identifier
                # the bare recompute exception lacks.
                logger.exception(
                    "recompute failed for subscription=%s after creating share deliveries",
                    subscription.pk,
                )
                raise
            return share_deliveries

        # Dynamic: resolve the correct DSD for each share's week
        station = default_delivery_station_day.delivery_station
        day_number = delivery_day_obj.day_number

        monday_dates = [Week(s.year, s.delivery_week).monday() for s in shares]
        min_date = min(monday_dates) if monday_dates else timezone.localdate()
        max_date = max(monday_dates) + timedelta(days=6) if monday_dates else min_date

        # Batch-fetch all candidate DSDs for this station + day_number
        candidate_delivery_station_days = list(
            DeliveryStationDay.objects.filter(
                delivery_station=station,
                delivery_day__day_number=day_number,
                valid_from__lte=max_date,
            )
            .exclude(valid_until__lt=min_date)
            .select_related("delivery_day")
            # Deterministic tie-break for _find_active_delivery_station_day
            # (latest valid_from).
            .order_by("-valid_from")
        )

        def _find_active_delivery_station_day(
            active_at: datetime.date,
        ) -> DeliveryStationDay | None:
            for delivery_station_day in candidate_delivery_station_days:
                if delivery_station_day.valid_from <= active_at and (
                    delivery_station_day.valid_until is None
                    or delivery_station_day.valid_until >= active_at
                ):
                    return delivery_station_day
            return None

        share_deliveries: list[ShareDelivery] = []
        for share, monday in zip(shares, monday_dates, strict=True):
            resolved_delivery_station_day = _find_active_delivery_station_day(monday)
            if resolved_delivery_station_day is None:
                logger.error(
                    "No active DSD for station=%s day_number=%s at %s",
                    station,
                    day_number,
                    monday,
                )
                resolved_delivery_station_day = default_delivery_station_day  # fallback
            share_deliveries.append(
                ShareDelivery(
                    subscription=subscription,
                    share=share,
                    delivery_station_day=resolved_delivery_station_day,
                    joker_taken=False,
                    is_opted_in=is_opted_in,
                )
            )

        ShareDelivery.objects.bulk_create(share_deliveries)
        from .recompute import recompute_shares

        try:
            recompute_shares(s.id for s in shares)
        except Exception:
            # Re-raise so the outer @transaction.atomic still rolls the
            # just-created deliveries back; add the subscription identifier
            # the bare recompute exception lacks.
            logger.exception(
                "recompute failed for subscription=%s after creating share deliveries",
                subscription.pk,
            )
            raise
        return share_deliveries
