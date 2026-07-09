"""Cancel a Member and cascade-cancel their open CoopShares.

GenG §30 requires an Austrittsdatum (exit date) on the Mitgliederliste,
and §31 needs the per-share cancellation date so the equity history
can be reconstructed for 10 years after exit. We therefore stamp the
exit date on the Member AND on every still-open CoopShare in one
atomic transaction — the two records can never disagree about whether
a member has left or when.

"Open" = ``cancelled_at IS NULL``. Already-cancelled shares are left
alone: cancelling a member doesn't reset the date on a share they
voluntarily downsized last year.

A successful cancellation also schedules a
``commissioning.member_cancelled`` confirmation email via
``transaction.on_commit`` (P1-3 atomicity policy) and stamps
``Member.cancellation_email_sent_at`` after a successful send. The
send is skipped silently when ``member.email`` is unset — most
importantly for the GDPR anonymisation path
(``apps/gdpr/services/anonymization.py::_anonymize_member``), which scrubs
``member.email`` to ``None`` BEFORE calling this function, so no
ghost confirmation goes to a recipient who explicitly asked to be
forgotten.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from django.db import DatabaseError, connection, transaction
from django.db.models import DateField, F, Value
from django.db.models.functions import Least
from django.utils import timezone

from ..models import CoopShare, Member

logger = logging.getLogger(__name__)


@transaction.atomic
def cancel_member_with_coop_shares(
    member: Member,
    *,
    cancelled_at: datetime | None = None,
    cancelled_effective_at: date | None = None,
    cancelled_by=None,
    reason: str | None = None,
    force: bool = False,
) -> Member:
    """Stamp cancellation timestamps on ``member`` and cascade to every
    still-open ``CoopShare`` for that member.

    Defaults: ``cancelled_at`` = now, ``cancelled_effective_at`` =
    today's date. Callers that need a future effective date (e.g.
    end-of-year exits after a notice period) pass it explicitly.

    **Active-subscription restraint.** Unless ``force=True``, a member who still
    holds an active subscription (admin-confirmed, not cancelled, term not past)
    cannot be cancelled — :class:`MemberHasActiveSubscriptions` is raised before
    anything is written. This makes "member leaves" an explicit decision: the
    office ends the subscriptions first (abo column), or force-cancels — which
    cascades and ends the subscriptions in the same transaction. Member
    self-service always runs with ``force=False`` (no force option for members).

    Each cascaded ``CoopShare`` also gets its ``payback_due_date`` snapshotted
    to ``effective + TenantSettings.retention_period_…_months`` — the equity
    stays in the Genossenschaft for the retention period after exit, then
    becomes due to be paid back. Frozen per-share so a later retention change
    doesn't move already-cancelled members' due dates.

    Returns ``member`` with a transient ``cancellation_result`` attribute —
    ``{"subscriptions_ended": [...], "subscriptions_not_ended": [...]}`` — so the
    caller can surface to the office which subscriptions a force-cancel could
    NOT end (those keep an active mandate and need manual attention).
    """
    now = cancelled_at or timezone.now()
    # Tenant-local date of the cancellation instant — NOT ``now.date()`` (UTC),
    # which would skew a day behind ``entry_date`` (stored tenant-local) near
    # the local/UTC midnight boundary and trip ``cancelled_effective_after_entry``.
    effective = cancelled_effective_at or timezone.localdate(now)
    today = timezone.localdate()

    if not force:
        _assert_no_active_subscription(member, today=today)

    member.cancelled_at = now
    member.cancelled_effective_at = effective
    member.cancelled_by = cancelled_by
    if reason is not None:
        member.cancellation_reason = reason
    member.save(
        update_fields=[
            "cancelled_at",
            "cancelled_effective_at",
            "cancelled_by",
            "cancellation_reason",
        ]
    )

    _cascade_cancel_coop_shares(
        member, now=now, effective=effective, cancelled_by=cancelled_by
    )

    subscriptions_ended, subscriptions_not_ended = _cancel_active_subscriptions(
        member, now=now, effective=effective, cancelled_by=cancelled_by
    )

    _cancel_draft_subscriptions(
        member, now=now, effective=effective, cancelled_by=cancelled_by
    )

    if member.email:
        _send_cancellation_email(member)

    # Transient (not persisted) report for the caller — which subscriptions the
    # cancellation ended vs. could not end (the latter keep a live mandate).
    member.cancellation_result = {
        "subscriptions_ended": subscriptions_ended,
        "subscriptions_not_ended": subscriptions_not_ended,
    }
    return member


def _assert_no_active_subscription(member: Member, *, today: date) -> None:
    """Restraint: refuse to cancel a member who still holds an active
    subscription unless explicitly forced. "Active" mirrors the member
    self-cancel rule: admin-confirmed, not yet cancelled, and not past its
    term. Force-cancel (e.g. a deceased member) bypasses this and ends the
    subscriptions later in the cascade."""
    from ..models import Subscription

    has_active_subscription = Subscription.active_for_member(member, today).exists()
    if has_active_subscription:
        from ..errors import MemberHasActiveSubscriptions

        raise MemberHasActiveSubscriptions(
            "This member still has active subscriptions. End them first, or "
            "force-cancel to end the membership and its subscriptions "
            "together."
        )


def _cascade_cancel_coop_shares(
    member: Member, *, now, effective, cancelled_by
) -> None:
    """Stamp the exit timestamps + a frozen ``payback_due_date`` on every
    still-open CoopShare for the member in a single UPDATE (avoids per-share
    ``.save()`` and the Python loop). The retention window is snapshotted
    per-share so a later retention-setting change doesn't move already-
    cancelled members' due dates."""
    from dateutil.relativedelta import relativedelta

    from apps.shared.tenants.models import TenantSettings

    settings = TenantSettings.get_current_settings(connection.tenant)
    retention_months = (
        settings.retention_period_cancelled_members_coop_shares_in_months
        if settings
        else 0
    )
    payback_due = effective + relativedelta(months=retention_months)

    CoopShare.objects.filter(member=member, cancelled_at__isnull=True).update(
        cancelled_at=now,
        cancelled_effective_at=effective,
        cancelled_by=cancelled_by,
        payback_due_date=payback_due,
    )


def _cancel_active_subscriptions(
    member: Member, *, now, effective, cancelled_by
) -> tuple[list[str], list[str]]:
    """End the member's still-active (admin-confirmed) subscriptions, so
    "member leaves" owns the full billing lifecycle (truncate term, drop
    future ShareDeliveries, re-plan charges via notify_subscription_changed)
    instead of relying on the caller incidentally deactivating the billing
    profile. ``cancel_subscription`` aligns to a Sunday within the term; skip
    subscriptions it can't cancel at this date (e.g. exit in the past, or term
    already ended) rather than aborting the member exit.

    Returns ``(subscriptions_ended, subscriptions_not_ended)`` — the latter
    keep a live mandate and need manual attention.
    """
    from core.errors import JasminError

    from ..errors import SubscriptionCancellationError
    from ..models import Subscription
    from ..utils.iso_week_utils import next_sunday
    from .subscription_service import SubscriptionService

    aligned_effective = next_sunday(effective)
    service = SubscriptionService()
    subscriptions_ended: list[str] = []
    subscriptions_not_ended: list[str] = []
    _NON_CANCELLATION_ERRORS = (
        DatabaseError,
        ValueError,
        TypeError,
        AttributeError,
        IndexError,
        KeyError,
    )
    for subscription in Subscription.objects.filter(
        member=member,
        admin_confirmed=True,
        cancelled_at__isnull=True,
    ):
        if subscription.valid_until and subscription.valid_until <= aligned_effective:
            # Already ends on/before the exit — expires naturally, nothing to do.
            subscriptions_ended.append(subscription.id)
            continue
        try:
            with transaction.atomic():
                service.cancel_subscription(
                    subscription,
                    cancelled_by=cancelled_by,
                    effective_at=aligned_effective,
                )
            subscriptions_ended.append(subscription.id)
        except SubscriptionCancellationError:
            # MEM-10: the normal Sunday-aligned cancel can't truncate THIS
            # subscription — it hasn't started yet (e.g. a future-dated trial),
            # or no Sunday remains in its term. The member is leaving, so it must
            # NOT survive: end it leniently (stamp cancelled + drop deliveries
            # after the exit) instead of recording a silent failure.
            try:
                with transaction.atomic():
                    _force_end_subscription(
                        subscription,
                        effective=effective,
                        now=now,
                        cancelled_by=cancelled_by,
                    )
                subscriptions_ended.append(subscription.id)
            except (JasminError, *_NON_CANCELLATION_ERRORS) as exc:
                # Mirror the outer handler: a per-subscription business/validation
                # failure (JasminError) or infra error must be recorded, not
                # allowed to escape and roll back the whole member exit. The
                # savepoint above isolates the failed row.
                subscriptions_not_ended.append(subscription.id)
                logger.error(
                    "member_cancel.subscription_force_end_failed "
                    "member=%s subscription=%s error=%s",
                    member.id,
                    subscription.id,
                    exc,
                )
        except (JasminError, *_NON_CANCELLATION_ERRORS) as exc:
            # BIZ-1: a genuine per-subscription failure must NOT abort the member
            # exit (the savepoint isolates it) — but it must NOT be silent
            # either. Record it so the office knows which subscriptions still
            # hold a live mandate and need manual attention.
            subscriptions_not_ended.append(subscription.id)
            logger.error(
                "member_cancel.subscription_not_ended member=%s subscription=%s error=%s",
                member.id,
                subscription.id,
                exc,
            )

    return subscriptions_ended, subscriptions_not_ended


def _cancel_draft_subscriptions(
    member: Member, *, now, effective, cancelled_by
) -> None:
    """Wind down the member's draft (unconfirmed) subscriptions.

    Drafts hold a CapacityReservation but have no ShareDeliveries or charges
    yet. ``_cancel_active_subscriptions`` only ends admin_confirmed subs, so
    wind drafts down here: stamp them cancelled + release their capacity
    reservation, freeing a departed member's slot and ensuring the leftover
    draft can never be confirmed into live deliveries/charges (the confirm
    endpoint also re-checks member.cancelled_at).
    """
    from ..models import Subscription
    from .capacity_reservation_service import CapacityReservationService

    draft_subscriptions = list(
        Subscription.objects.filter(
            member=member,
            admin_confirmed=False,
            cancelled_at__isnull=True,
        )
    )
    if draft_subscriptions:
        Subscription.objects.filter(
            pk__in=[draft.pk for draft in draft_subscriptions]
        ).update(
            cancelled_at=now,
            # Clamp the effective date to each draft's own term end. The DB
            # CheckConstraint ``subscription_cancel_before_valid_until`` requires
            # cancelled_effective_at <= valid_until whenever both are set, so a
            # future exit date (e.g. an end-of-year notice) or a stale draft
            # whose valid_until is already past would otherwise raise an
            # IntegrityError and abort the whole member exit. A draft has no
            # deliveries or charges, so the exact effective date is only
            # informational — pinning it to the term end is harmless. Least()
            # ignores a NULL valid_until, leaving ``effective`` untouched there.
            cancelled_effective_at=Least(
                Value(effective, output_field=DateField()), F("valid_until")
            ),
            cancelled_by=cancelled_by,
        )
        for draft in draft_subscriptions:
            CapacityReservationService.release_for_subscription(draft)


def _force_end_subscription(subscription, *, effective, now, cancelled_by) -> None:
    """Lenient end for a confirmed subscription the Sunday-aligned
    ``cancel_subscription`` can't truncate (it hasn't started yet, or no Sunday
    remains in its term). Used only by the member-exit cascade: the member is
    leaving, so the subscription must not survive even if its term can't be
    cleanly truncated.

    Stamps it cancelled and drops every ShareDelivery after the member's exit
    (mirrors the delivery-drop in ``SubscriptionService.cancel_subscription``,
    minus the date-validation guards). ``valid_until`` is deliberately left
    untouched — ``TimeBoundMixin`` requires it to fall on a Sunday and the exit
    date may not be one; the ``cancelled_at`` stamp is what marks the
    subscription ended (the "active" check keys on ``cancelled_at IS NULL``).
    """
    from ..models import Subscription
    from .subscription_deliveries import truncate_future_deliveries

    # Stamp the cancellation columns with a targeted UPDATE, NOT
    # ``subscription.save()``: TimeBoundMixin.save() re-runs full_clean(), which
    # re-validates DSD coverage against the (unchanged) term via
    # SubscriptionService.assert_delivery_station_day_covers_subscription. If the
    # office has since edited the station-day chain so coverage no longer holds,
    # that re-validation raises SubscriptionDeliveryStationDayOutOfRange (a
    # JasminError) which would otherwise escape and roll back the whole member
    # exit. The cancellation stamp itself needs no term re-validation, and the
    # caller's line-220 pre-check guarantees valid_until > effective so the
    # cancel-before-valid_until constraint holds.
    Subscription.objects.filter(pk=subscription.pk).update(
        cancelled_at=now,
        cancelled_effective_at=effective,
        cancelled_by=cancelled_by,
    )
    subscription.cancelled_at = now
    subscription.cancelled_effective_at = effective
    subscription.cancelled_by = cancelled_by

    # Drop future deliveries past the exit date + re-plan charges (shared with
    # SubscriptionService.cancel_subscription).
    truncate_future_deliveries(subscription, cutoff_date=effective)


def _send_cancellation_email(member: Member) -> None:
    """Schedule the ``commissioning.member_cancelled`` confirmation
    via ``on_commit`` (P1-3 atomicity policy).

    On a successful send (``EmailService.send_email`` returns
    ``True``) the dispatcher stamps
    ``Member.cancellation_email_sent_at``. The stamp lives outside
    the outer cancellation transaction by design — recording "we
    actually sent it" after the SMTP round-trip is more honest than
    optimistically marking it inside the same transaction as
    ``cancelled_at``.
    """
    from apps.shared.tenant_urls import tenant_name

    from .member_email import schedule_member_email

    member_id = member.id
    context = {
        "tenant_name": tenant_name(),
        # Flatten to plain scalars — never hand a live ORM instance to the
        # tenant-editable email renderer (see template_renderer._resolve).
        "member": {
            "first_name": member.first_name,
            "member_number": member.member_number,
        },
        # GenG §30 Austrittsdatum is a local calendar day — pre-format
        # to dd.mm.yyyy here so the template stays substitution-only
        # and renders identically under the safe Mustache renderer
        # used for tenant overrides.
        "cancelled_effective_at": (
            member.cancelled_effective_at.strftime("%d.%m.%Y")
            if member.cancelled_effective_at
            else ""
        ),
    }

    def _stamp_email_sent() -> None:
        # Stamp the tracker only on a real send. Done via direct
        # ORM update so we don't fight any in-memory ``Member``
        # state on the caller's side.
        Member.objects.filter(pk=member_id).update(
            cancellation_email_sent_at=timezone.now()
        )

    schedule_member_email(
        member,
        slug="commissioning.member_cancelled",
        context=context,
        logger=logger,
        log_error_event="member_cancelled.email_failed",
        log_not_sent_event="member_cancelled.email_not_sent",
        post_send_callback=_stamp_email_sent,
    )
