"""Per-delivery opt-in service for on-off ShareTypeVariations.

When ``ShareTypeVariation.requires_optin`` is True, each
``ShareDelivery`` for the variation carries its own ``is_opted_in``
toggle. The member (or the office on their behalf) decides per
delivery whether the box actually ships. After the variation's
configured deadline, the value is locked at whatever it was — no
auto-conversion, no reminder email, no retroactive flips.

This service is the single legitimate writer of:
  * ``ShareDelivery.is_opted_in``
  * ``ShareDelivery.optin_decided_at``
  * ``ShareDelivery.optin_decided_by``

Direct ``ShareDelivery.objects.update(is_opted_in=...)`` calls bypass
the audit stamp and the deadline guard — don't do that in production
code. Tests that need to seed a particular state can either pass
through the service or set the model fields and call ``save()`` (the
default-stamping logic in ``ShareDelivery.save()`` only fires on
insert).

See ``docs/on-off-share-variations-workflow.md`` for the wider
rationale and the decisions that shaped this implementation.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from apps.commissioning.errors import (
    OptinDeadlinePassed,
    OptinNotApplicable,
)
from apps.commissioning.utils.iso_week_utils import share_delivery_date
from apps.shared.subscription_hooks import notify_subscription_changed

if TYPE_CHECKING:
    from apps.accounts.models import JasminUser
    from apps.commissioning.models import Member, ShareDelivery

logger = logging.getLogger(__name__)


class OptinService:
    """Read + write helpers for the on-off opt-in column."""

    # --------------------------------------------------------------- #
    # Deadline math
    # --------------------------------------------------------------- #

    @staticmethod
    def optin_deadline(share_delivery: ShareDelivery) -> datetime.date | None:
        """Return the last day on which the opt-in can still be
        toggled. ``None`` if the variation isn't on-off or the
        delivery date can't be resolved (malformed Share row)."""
        variation = share_delivery.share.share_type_variation
        if not variation or not variation.requires_optin:
            return None
        delivery_date = share_delivery_date(share_delivery)
        if delivery_date is None:
            return None
        return delivery_date - datetime.timedelta(
            days=variation.optin_deadline_days_before_delivery
        )

    @staticmethod
    def is_locked(
        share_delivery: ShareDelivery,
        *,
        today: datetime.date | None = None,
    ) -> bool:
        """Has the deadline already passed? Locked rows can't be
        toggled — the current ``is_opted_in`` value stands.

        Non-on-off variations always return ``True`` (the column is
        effectively locked because the toggle wasn't meaningful in
        the first place)."""
        deadline = OptinService.optin_deadline(share_delivery)
        if deadline is None:
            return True
        today = today or timezone.localdate()
        return today > deadline

    # --------------------------------------------------------------- #
    # The actual toggle
    # --------------------------------------------------------------- #

    @staticmethod
    @transaction.atomic
    def toggle(
        share_delivery: ShareDelivery,
        *,
        opt_in: bool,
        actor: JasminUser,
    ) -> ShareDelivery:
        """Set the opt-in state on a single delivery + stamp the audit
        trail. Triggers a charge-schedule recompute so billing stays
        in sync with the new state.

        Raises:
          * ``OptinNotApplicable`` (400 ``optin.not_applicable``) when
            the variation isn't on-off — caller should use
            ``joker_taken`` for normal variations instead.
          * ``OptinDeadlinePassed`` (409 ``optin.deadline_passed``)
            when the deadline has lapsed.
        """
        variation = share_delivery.share.share_type_variation
        if not variation or not variation.requires_optin:
            raise OptinNotApplicable(
                f"ShareDelivery {share_delivery.pk}: variation is not on-off."
            )
        if OptinService.is_locked(share_delivery):
            deadline = OptinService.optin_deadline(share_delivery)
            raise OptinDeadlinePassed(
                f"ShareDelivery {share_delivery.pk}: opt-in deadline "
                f"({deadline.isoformat() if deadline else 'unknown'}) "
                "has passed."
            )

        share_delivery.is_opted_in = bool(opt_in)
        share_delivery.optin_decided_at = timezone.now()
        share_delivery.optin_decided_by = actor
        share_delivery.save(
            update_fields=[
                "is_opted_in",
                "optin_decided_at",
                "optin_decided_by",
            ]
        )

        # The new is_opted_in value changes which deliveries count toward
        # this period's bill — notify payments (via the shared hook) to
        # re-plan the charge schedule.
        if share_delivery.subscription_id:
            notify_subscription_changed(share_delivery.subscription)

        # ``is_opted_in`` ALSO gates whether this delivery counts as
        # production/harvest demand — ShareDemandService excludes opted-out
        # on-off deliveries from every aggregation. So the share's
        # theoreticals (harvest/purchase/wash/clean) and SHARECONTENT stock
        # movements must be rebuilt too, or the harvest/packing lists stay
        # computed off the pre-toggle demand. Mirrors the joker_taken handling
        # in ShareDeliveryViewSet.perform_update; the billing notify above is
        # not enough on its own.
        if share_delivery.share_id:
            from .recompute import recompute_shares

            recompute_shares([share_delivery.share_id])

        return share_delivery

    # --------------------------------------------------------------- #
    # Read APIs (the office card + member portal both need a list)
    # --------------------------------------------------------------- #

    @staticmethod
    def list_pending_for_member(
        member: Member,
        *,
        today: datetime.date | None = None,
    ) -> list[ShareDelivery]:
        """All upcoming on-off deliveries this member can still
        toggle. The list is what the office's MemberDetail card (and
        the eventual self-service portal) renders.

        Filters:
          * ``subscription.member == member``
          * Variation has ``requires_optin=True``
          * Deadline is today or later (locked rows are NOT
            returned — office uses a separate query for the audit
            view)
          * Cancelled subscriptions are excluded
        """
        from apps.commissioning.models import ShareDelivery

        today = today or timezone.localdate()
        candidates = (
            ShareDelivery.objects.select_related(
                # Mirror every relation ShareDeliverySerializer dereferences so
                # pending_optin doesn't N+1 (member / share_type / station).
                "share__share_type_variation__share_type",
                "share__delivery_day",
                "subscription__member",
                "delivery_station_day__delivery_station",
            )
            .prefetch_related(
                # get_share_content walks share.sharecontent_set (+ article/seller)
                # per row — prefetch or it is a per-row query.
                "share__sharecontent_set",
                "share__sharecontent_set__share_article",
                "share__sharecontent_set__seller",
            )
            .filter(
                subscription__member=member,
                subscription__cancelled_at__isnull=True,
                share__share_type_variation__requires_optin=True,
            )
        )

        result = []
        for share_delivery in candidates:
            deadline = OptinService.optin_deadline(share_delivery)
            if deadline is None:
                continue
            if deadline < today:
                continue
            result.append(share_delivery)
        # Sort by delivery date so the card reads chronologically.
        result.sort(
            key=lambda share_delivery: share_delivery_date(share_delivery)
            or datetime.date.max
        )
        return result
