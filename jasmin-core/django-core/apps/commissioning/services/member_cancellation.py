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
``transaction.on_commit`` and stamps
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
from dataclasses import dataclass
from datetime import date, datetime

from django.db import DatabaseError, transaction
from django.db.models import DateField, F, Max, Q, Value
from django.db.models.functions import Least
from django.utils import timezone

from apps.shared.display_formats import DisplayFormats
from core.tenant_db import connection

from ..errors import MemberAlreadyCancelled, MemberExitBeforeTransfer
from ..models import CoopShare, CoopShareTransfer, Member

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemberCancellation:
    """Which active subscriptions a cancellation ended, and which it could not
    end: those keep a live mandate and need the office's attention."""

    subscriptions_ended: list[str]
    subscriptions_not_ended: list[str]


def latest_coop_share_transfer_date(member: Member) -> date | None:
    """The date of the member's latest coop share transfer, given or received.

    A member's exit can't come before it: the shares of a transfer stop counting
    for one side on the date they start counting for the other.
    """
    return CoopShareTransfer.objects.filter(
        Q(from_member=member) | Q(to_member=member)
    ).aggregate(latest=Max("transfer_date"))["latest"]


@transaction.atomic
def cancel_member_with_coop_shares(
    member: Member,
    *,
    cancelled_at: datetime | None = None,
    cancelled_effective_at: date | None = None,
    cancelled_by=None,
    reason: str | None = None,
    force: bool = False,
    shares_transferred: bool = False,
    notify: bool = True,
) -> MemberCancellation:
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

    A member already cancelled is refused with :class:`MemberAlreadyCancelled`,
    and an exit dated before one of the member's coop share transfers, given or
    received, with :class:`MemberExitBeforeTransfer`.

    Each cascaded ``CoopShare`` also gets its ``payback_due_date`` snapshotted
    to ``effective + TenantSettings.retention_period_…_months`` — the equity
    stays in the cooperative for the retention period after exit, then
    becomes due to be paid back. Frozen per-share so a later retention change
    doesn't move already-cancelled members' due dates.

    ``shares_transferred`` tells the cancellation email that the member's shares
    went to another member, so no settlement of their share balance follows.
    ``notify=False`` cancels without scheduling that email.

    Returns a :class:`MemberCancellation`, so the caller can surface to the
    office which subscriptions a force-cancel could NOT end (those keep an
    active mandate and need manual attention).
    """
    # The row lock a coop share transfer of this member holds while it writes:
    # the exit is checked against a transfer recorded concurrently, and a second
    # cancellation of the same member waits for the first and is refused. Only
    # the row: GDPR erasure has written it before it gets here, so taking the
    # transfer's advisory lock now could deadlock with a transfer waiting for it.
    locked = Member.objects.select_for_update().only("cancelled_at").get(pk=member.pk)
    if locked.cancelled_at is not None:
        raise MemberAlreadyCancelled("This membership is already cancelled.")

    now = cancelled_at or timezone.now()
    # Tenant-local date of the cancellation instant — NOT ``now.date()`` (UTC),
    # which would skew a day behind ``entry_date`` (stored tenant-local) near
    # the local/UTC midnight boundary and trip ``cancelled_effective_after_entry``.
    effective = cancelled_effective_at or timezone.localdate(now)
    latest_transfer = latest_coop_share_transfer_date(member)
    if latest_transfer is not None and effective < latest_transfer:
        raise MemberExitBeforeTransfer(transfer_date=latest_transfer.isoformat())
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
        member, now=now, effective=effective, cancelled_by=cancelled_by, today=today
    )

    _cancel_draft_subscriptions(
        member, now=now, effective=effective, cancelled_by=cancelled_by
    )

    if notify and member.email:
        _send_cancellation_email(member, shares_transferred=shares_transferred)

    return MemberCancellation(
        subscriptions_ended=subscriptions_ended,
        subscriptions_not_ended=subscriptions_not_ended,
    )


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


def cancel_coop_shares_of_departed_member(member: Member) -> None:
    """Cancel the open coop shares of a member who has already left, with the
    member's own exit stamps and the normal payback due date.

    Used when onboarding mode confirms a departed member or one of their coop
    shares: the confirmed equity must not stay open on a closed membership.
    Unlike :func:`cancel_member_with_coop_shares` the member row, its
    subscriptions and its cancellation email are left alone. A no-op for a
    member who has not left.
    """
    if member.cancelled_at is None:
        return
    effective = member.cancelled_effective_at or timezone.localdate(member.cancelled_at)
    _cascade_cancel_coop_shares(
        member,
        now=member.cancelled_at,
        effective=effective,
        cancelled_by=member.cancelled_by,
    )


def _cancel_active_subscriptions(
    member: Member, *, now, effective, cancelled_by, today: date
) -> tuple[list[str], list[str]]:
    """End the member's still-active (admin-confirmed) subscriptions, so
    "member leaves" owns the full billing lifecycle (truncate term, drop
    future ShareDeliveries, re-plan charges via notify_subscription_changed)
    instead of relying on the caller incidentally deactivating the billing
    profile. ``cancel_subscription`` aligns to a Sunday within the term; a
    subscription it can't cancel at that date (it hasn't started by then, or
    the exit lies in an earlier week than ``today``) is force-ended instead of
    aborting the member exit, on the date :func:`_force_end_date` picks.

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
            # The normal Sunday-aligned cancel can't truncate THIS
            # subscription — it hasn't started yet (e.g. a future-dated trial),
            # or the exit lies in an earlier week than today. The member is
            # leaving, so it must NOT survive: end it leniently (stamp cancelled
            # + drop deliveries after its end) instead of recording a silent
            # failure.
            try:
                with transaction.atomic():
                    _force_end_subscription(
                        subscription,
                        effective=_force_end_date(
                            subscription, exit_date=effective, today=today
                        ),
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
            # A genuine per-subscription failure must NOT abort the member
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
    reservation, freeing a departed member's slot. The confirm endpoint refuses
    a departed member's subscription; in onboarding mode it confirms one only
    when it ends by the exit date. The member's waiting-list entries leave the
    list, and an open offer is cancelled, so its magic link stops working.
    """
    from ..models import Subscription
    from .capacity_reservation_service import CapacityReservationService
    from .waiting_list_offer_service import withdraw_from_waiting_list

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
    withdraw_from_waiting_list(Subscription.objects.filter(member_id=member.pk))


def _force_end_date(subscription, *, exit_date: date, today: date) -> date:
    """The ``cancelled_effective_at`` a member exit stamps on a subscription it
    force-ends.

    The exit date itself, unless the exit lies before ``today``: the boxes up to
    the end of the current ISO week have been packed and handed out, or are
    about to be, and are owed, so the subscription then runs to
    ``next_sunday(today)`` — the earliest end ``cancel_subscription`` accepts.
    Only the member and its coop shares keep the backdated exit date. Never
    past ``valid_until`` (``subscription_cancel_before_valid_until``): a term
    that ends before that Sunday keeps its end and every delivery in it.
    """
    from ..utils.iso_week_utils import next_sunday

    end = exit_date if exit_date >= today else next_sunday(today)
    if subscription.valid_until is not None:
        end = min(end, subscription.valid_until)
    return end


def _force_end_subscription(subscription, *, effective, now, cancelled_by) -> None:
    """Lenient end for a confirmed subscription the Sunday-aligned
    ``cancel_subscription`` can't truncate (it hasn't started yet, or the exit
    lies in an earlier week than today). Used only by the member-exit cascade:
    the member is leaving, so the subscription must not survive even if its
    term can't be cleanly truncated.

    Stamps it cancelled effective ``effective`` — the date
    :func:`_force_end_date` picks — and drops every ShareDelivery after it
    (mirrors the delivery-drop in ``SubscriptionService.cancel_subscription``,
    minus the date-validation guards). ``valid_until`` is deliberately left
    untouched — ``TimeBoundMixin`` requires it to fall on a Sunday and
    ``effective`` may not be one; the ``cancelled_at`` stamp is what marks the
    subscription ended (the "active" check keys on ``cancelled_at IS NULL``).
    The paths that build deliveries or charges from the term read its end
    through ``subscription_term.effective_term_end``, so ``cancelled_effective_at``
    bounds them: a later pause edit restores nothing after it.
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
    # exit. The cancellation stamp itself needs no term re-validation, and
    # ``_force_end_date`` never picks a date past ``valid_until``, so the
    # cancel-before-valid_until constraint holds.
    Subscription.objects.filter(pk=subscription.pk).update(
        cancelled_at=now,
        cancelled_effective_at=effective,
        cancelled_by=cancelled_by,
    )
    subscription.cancelled_at = now
    subscription.cancelled_effective_at = effective
    subscription.cancelled_by = cancelled_by

    # Drop the deliveries after ``effective`` + re-plan charges (shared with
    # SubscriptionService.cancel_subscription).
    truncate_future_deliveries(subscription, cutoff_date=effective)


def _send_cancellation_email(member: Member, *, shares_transferred: bool) -> None:
    """Schedule the ``commissioning.member_cancelled`` confirmation
    via ``on_commit``.

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
        # Pre-formatted, so the template stays substitution-only and renders
        # identically under the safe Mustache renderer used for tenant
        # overrides.
        "cancelled_effective_at": DisplayFormats.current().format_date(
            member.cancelled_effective_at
        ),
        "shares_transferred": shares_transferred,
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
