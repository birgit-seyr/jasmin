"""Errors of trial members, subscriptions, cooperative shares, cancellations,
additional shares and on-off opt-ins."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
)

# --------------------------------------------------------------------------- #
# Subscriptions                                                               #
# --------------------------------------------------------------------------- #


class SubscriptionDeliveryStationDayOutOfRange(BadRequestError):
    """The subscription's chosen default delivery-station day doesn't cover the
    whole subscription term — it either becomes valid after the subscription
    starts, or stops being valid before the subscription ends with no successor
    day to take over. ``field`` is ``default_delivery_station_day``."""

    code = "subscription.delivery_station_day_out_of_range"


# --------------------------------------------------------------------------- #
# Trial members / subscriptions                                                #
# --------------------------------------------------------------------------- #


class TrialMembersNotAllowed(BadRequestError):
    """Caller tried to create a trial Member while the tenant has the
    trial-member concept effectively off — i.e. either
    ``allows_trial_subscriptions=False`` (no trial subs anywhere) or
    ``allows_trial_subscriptions_for_trial_members=False`` (trial subs only
    for full members). With nothing for a trial member to do,
    creating one is rejected."""

    code = "trial.members_not_allowed"


class TrialSubscriptionsNotAllowed(BadRequestError):
    """Caller tried to create a trial Subscription while the tenant has
    ``allows_trial_subscriptions=False``."""

    code = "trial.subscriptions_not_allowed"


class TrialSubscriptionsOnlyForFullMembers(BadRequestError):
    """Caller tried to attach a trial Subscription to a Member whose
    ``is_trial=True`` while the tenant has
    ``allows_trial_subscriptions_for_trial_members=False``."""

    code = "trial.subscriptions_only_for_full_members"


class SubscriptionAlreadyConfirmed(ConflictError):
    """Confirm called on an already-confirmed subscription. Mirrors
    ``MemberAlreadyConfirmed``."""

    code = "subscription.already_confirmed"


class SubscriptionMemberNotAdmitted(BadRequestError):
    """In onboarding mode, a subscription of a member who has already left is
    confirmed before the member. Confirming a subscription doesn't admit a
    departed member, so the member is confirmed first with their own date."""

    code = "subscription.member_not_admitted"

    def __init__(self) -> None:
        super().__init__(
            "Confirm the member first: a member who has left isn't admitted "
            "through a subscription.",
            field="member",
        )


class SubscriptionEndsAfterMemberExit(BadRequestError):
    """In onboarding mode, a subscription of a member who has already left ends
    after the member's exit date (or the member has no exit date), so it would
    deliver and bill after the exit. ``details.exit_date`` carries the exit
    date when there is one."""

    code = "subscription.ends_after_member_exit"

    def __init__(self, exit_date) -> None:
        super().__init__(
            "The subscription ends after the member's exit date.",
            field="valid_until",
            details={"exit_date": exit_date.isoformat() if exit_date else None},
        )


class SubscriptionConfirmedImmutable(ConflictError):
    """Edit/delete attempted on an admin-confirmed subscription. Confirmed
    subscriptions are immutable through CRUD — end them early via the
    ``cancel`` action instead."""

    code = "subscription.confirmed_immutable"


class MemberConfirmedImmutable(ConflictError):
    """Delete attempted on an admin-confirmed member. A confirmed member holds
    membership + equity history that must survive — cancel it (the ``cancel``
    action, which stamps ``cancelled_at``) instead of hard-deleting."""

    code = "member.confirmed_immutable"


class CoopShareConfirmedImmutable(ConflictError):
    """Delete attempted on an admin-confirmed coop share. Confirmed
    Geschäftsanteile carry statutory GenG retention — cancel the share (or the
    member) instead of hard-deleting it."""

    code = "coop_share.confirmed_immutable"


class CoopShareConfirmedFieldsLocked(ConflictError):
    """Update attempted to change the committed terms of an admin-confirmed
    coop share (amount, member, due date, increase flag). Once confirmed the
    Geschäftsanteil is part of the GenG register; only the payment / payback /
    note bookkeeping stays editable. Cancel the share and record a new one
    instead of rewriting it."""

    code = "coop_share.confirmed_fields_locked"

    def __init__(self, field_names: list[str]) -> None:
        super().__init__(
            "Cannot change "
            + ", ".join(field_names)
            + " on a confirmed coop share. Cancel it and record a new share instead.",
            field=field_names[0] if field_names else None,
            details={"fields": field_names},
        )


class CoopShareNotPending(ConflictError):
    """An onboarding-mode confirm of a coop share that is already confirmed or
    cancelled. A manual confirmation date may only date a pending share, so an
    existing confirmation or cancellation is never re-stamped."""

    code = "coop_share.not_pending"

    def __init__(self) -> None:
        super().__init__(
            "Only a pending coop share (not confirmed, not cancelled) can be "
            "confirmed."
        )


class CoopShareInvalidAmount(BadRequestError):
    """``amount_of_coop_shares`` is not a whole number greater than zero. A
    cooperative share is a whole Geschäftsanteil (GenG) — zero, negative and
    fractional amounts are rejected on every write path (office, CSV import,
    member self-service)."""

    code = "coop_share.invalid_amount"

    def __init__(self, message: str) -> None:
        super().__init__(message, field="amount_of_coop_shares")


class CoopShareTransferSameMember(BadRequestError):
    """A coop share transfer names the same member as giver and receiver."""

    code = "coop_share_transfer.same_member"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can't be transferred to the same member.", field="to_member"
        )


class CoopShareTransferGiverNotAdmitted(BadRequestError):
    """Only an admitted, non-trial member holds Geschäftsanteile that can be
    transferred."""

    code = "coop_share_transfer.giver_not_admitted"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can only be transferred from an admitted member.",
            field="from_member",
        )


class CoopShareTransferReceiverNotAdmitted(BadRequestError):
    """The receiving member of a coop share transfer must be admitted (full or
    trial member); a pending or rejected applicant can't hold equity."""

    code = "coop_share_transfer.receiver_not_admitted"

    def __init__(self) -> None:
        super().__init__(
            "Coop shares can only be transferred to an admitted member.",
            field="to_member",
        )


class CoopShareTransferReceiverCancelled(BadRequestError):
    """The receiving member of a coop share transfer has already left the
    cooperative; a departed member can't acquire new Geschäftsanteile."""

    code = "coop_share_transfer.receiver_cancelled"

    def __init__(self) -> None:
        super().__init__(
            "The receiving member is already cancelled.", field="to_member"
        )


class CoopShareTransferExceedsHeld(BadRequestError):
    """A coop share transfer asks for more shares than the giving member holds as
    confirmed, uncancelled shares paid by the transfer date. Pending and unpaid
    shares are not transferable."""

    code = "coop_share_transfer.exceeds_held"

    def __init__(self, *, available: int | float) -> None:
        super().__init__(
            f"The member only holds {available} confirmed, paid coop shares.",
            field="amount_of_coop_shares",
            details={"available": available},
        )


class CoopShareTransferDateInFuture(BadRequestError):
    """A coop share transfer is dated in the future; a transfer is recorded when
    it has happened."""

    code = "coop_share_transfer.date_in_future"

    def __init__(self) -> None:
        super().__init__(
            "The transfer date can't be in the future.", field="transfer_date"
        )


class CoopShareTransferDateBeforeEntry(BadRequestError):
    """A coop share transfer is dated before the giving or the receiving member's
    entry date: nobody gives or receives Geschäftsanteile before joining.
    ``details.context`` names the side (``from_member`` / ``to_member``)."""

    code = "coop_share_transfer.date_before_entry"

    def __init__(self, *, entry_date: str, member: str) -> None:
        side = "giving" if member == "from_member" else "receiving"
        super().__init__(
            f"The transfer date is before the {side} member's entry date ({entry_date}).",
            field="transfer_date",
            details={"entry_date": entry_date, "context": member},
        )


class CoopShareTransferBeforeAnother(BadRequestError):
    """A coop share transfer is dated before another transfer of the giving or
    the receiving member that is already recorded. Transfers are recorded in
    date order: the share window and the giver's exit are checked on today's
    holdings, which hold from the transfer date on only when no later transfer
    follows. ``details.context`` names the side (``from_member`` /
    ``to_member``)."""

    code = "coop_share_transfer.before_another"

    def __init__(self, *, transfer_date: str, member: str) -> None:
        side = "giving" if member == "from_member" else "receiving"
        super().__init__(
            f"The {side} member already has a coop share transfer dated "
            f"{transfer_date}; transfers are recorded in date order.",
            field="transfer_date",
            details={"transfer_date": transfer_date, "context": member},
        )


class CoopShareNotFromTransfer(BadRequestError):
    """Undoing a transfer was asked of a coop share no transfer created."""

    code = "coop_share.not_from_a_transfer"

    def __init__(self) -> None:
        super().__init__("This coop share was not created by a transfer.")


class CoopShareTransferReversalBlocked(ConflictError):
    """A later coop share transfer of the giving or the receiving member —
    dated after this one, or recorded after it — may build on the shares this
    one moved, so it has to be undone first."""

    code = "coop_share_transfer.reversal_blocked"

    def __init__(self, *, transfer_date: str) -> None:
        super().__init__(
            "A later coop share transfer of one of these members "
            f"({transfer_date}) builds on this one; undo that one first.",
            details={"transfer_date": transfer_date},
        )


class CoopShareTransferReversalAfterExit(ConflictError):
    """One of the members has left since the transfer, and that exit settled
    the shares the transfer moved."""

    code = "coop_share_transfer.reversal_after_exit"

    def __init__(self) -> None:
        super().__init__(
            "A member of this transfer has left since, and that exit settled the "
            "transferred shares."
        )


class CoopShareTransferReversalGiverInactive(ConflictError):
    """The transfer ended the giving member's membership, and that member's
    record has since been deactivated or erased, so it can't be reopened."""

    code = "coop_share_transfer.reversal_giver_inactive"

    def __init__(self) -> None:
        super().__init__(
            "The giving member's record has been deactivated or erased since the "
            "transfer, so the membership the transfer ended can't be reopened."
        )


class CoopShareTransferReversalEmptiesReceiver(ConflictError):
    """Undoing the transfer would leave the receiving member — still a member —
    without confirmed shares."""

    code = "coop_share_transfer.reversal_empties_receiver"

    def __init__(self) -> None:
        super().__init__(
            "Undoing this transfer would leave the receiving member without shares."
        )


class CoopShareTransferCancellationNotConfirmed(BadRequestError):
    """The transfer leaves the giving member without confirmed shares, which
    cancels the membership, and the request didn't confirm that."""

    code = "coop_share_transfer.cancellation_not_confirmed"

    def __init__(self) -> None:
        super().__init__(
            "This transfer leaves the giving member without shares and cancels the "
            "membership; confirm it with confirm_member_cancellation.",
            field="confirm_member_cancellation",
        )


class SubscriptionPriceInvalid(BadRequestError):
    """``price_per_delivery`` is not a valid non-negative amount on a path that
    takes it outside a serializer (the waiting-list offer). A negative price
    would make the subscription produce negative or no charges."""

    code = "subscription.invalid_price"

    def __init__(self, value) -> None:
        super().__init__(
            f"Invalid price_per_delivery ({value}); it must be a number of at least 0.",
            field="price_per_delivery",
            details={"value": str(value)},
        )


class SubscriptionStartTooSoon(BadRequestError):
    """``valid_from`` is earlier than the tenant's required lead time
    (``min_weeks_from_creation_to_start_delivery`` weeks from now, snapped to
    the next Monday). The office UI's date picker already floors the choice;
    this is the backstop for direct API calls."""

    code = "subscription.start_too_soon"

    def __init__(self, *, valid_from, earliest, min_weeks: int) -> None:
        super().__init__(
            f"Subscription cannot start before {earliest} "
            f"({min_weeks} week(s) lead time required).",
            field="valid_from",
            details={
                "valid_from": str(valid_from),
                "earliest": str(earliest),
                "min_weeks": min_weeks,
            },
        )


class SolidarityPriceBelowMinimum(BadRequestError):
    """The chosen solidarity price is below the variation's floor
    (``solidarity_min_price_per_delivery``, or the reference price if no
    explicit floor is set). Only enforced when the tenant enables
    ``allows_solidarity_pricing``."""

    code = "subscription.solidarity_price_below_minimum"

    def __init__(self, *, chosen, minimum) -> None:
        super().__init__(
            f"The chosen price ({chosen}) is below the solidarity minimum "
            f"({minimum}).",
            field="price_per_delivery",
            details={"chosen": str(chosen), "minimum": str(minimum)},
        )


class OpenEndedSubscriptionNotAllowed(BadRequestError):
    """A subscription was created / updated without a ``valid_until`` end date.

    Open-ended subscriptions materialise no ShareDeliveries (the materialiser
    skips a sub with no ``valid_until``) and therefore generate only
    zero-amount charges — they silently never bill. An end date is
    required so every billable subscription has a finite, billable term. The
    office UI's date picker already requires it; this is the backstop for
    direct API calls / imports / scripts."""

    code = "subscription.open_ended_not_allowed"


class SubscriptionVariationLocked(BadRequestError):
    """``Subscription.share_type_variation`` was changed after the subscription
    was admin-confirmed (and its Shares / ShareDeliveries materialised).

    The variation is the key the materialised Shares / ShareDeliveries are
    keyed by — changing it would orphan that data (deliveries + packing lists
    would still reference the OLD variation). It is fixed once confirmed; create
    a new subscription instead. (A raw ``QuerySet.update()`` still bypasses this,
    like every Django model validator — this guards the normal ``save()`` path,
    which is the only one any caller actually uses.)"""

    code = "subscription.variation_locked"


class RenewalVariationUnavailable(BadRequestError):
    """Auto-renewal could not find a share-type variation of the same size that
    covers the whole renewal term.

    The subscription's variation has ended and no same-``(share_type, size)``
    successor reaches across the new term, so there is nothing to renew onto.
    Counted as a failure (``no_variation`` reason in the bulk-renew result);
    the office adds/extends a variation and renews again (the source stays
    renewable)."""

    code = "subscription.renewal_variation_unavailable"


class RenewalPriceUnavailable(BadRequestError):
    """Auto-renewal could not resolve a price for the renewal term.

    The successor variation has no ``ShareTypeVariationGrossPrice`` window on or
    before the new start at all — so the draft would be a fully €0-billed term.
    (The predecessor's stored price is deliberately NOT a fallback: it can be a
    member-chosen solidarity or office custom figure that must not silently
    carry into a new term.) Counted as a failure (``no_price`` reason); the
    office adds a gross-price window for the term and renews again."""

    code = "subscription.renewal_price_unavailable"


class RenewalChainNumberMissing(ConflictError):
    """A renewal's predecessor has no ``subscription_number`` to inherit.

    A renewal must NEVER become a chain root: falling through to the
    fresh-``Max()+1`` numbering branch would assign a different number at
    ``generation=0``, silently splitting the "shared number across the chain"
    invariant. Only reachable if the predecessor was created bypassing
    ``save()`` (a ``bulk_create``, a partial import) — fix the predecessor's
    number, then renew again."""

    code = "subscription.renewal_chain_number_missing"


class SubscriptionTermAlreadyRenewed(ConflictError):
    """A new subscription continues a term that already has its next term — a
    renewal draft, typically, which the new one would duplicate: confirming
    both doubles the member's deliveries and charges."""

    code = "subscription.term_already_renewed"

    def __init__(
        self, *, predecessor: str, renewal: str, renewal_valid_from: str
    ) -> None:
        super().__init__(
            f"Subscription {predecessor} already continues with {renewal} from "
            f"{renewal_valid_from}; confirm or edit that one, or delete it "
            "first, instead of adding another next term.",
            details={
                "predecessor": predecessor,
                "renewal": renewal,
                "renewal_valid_from": renewal_valid_from,
            },
        )


class SubscriptionTermPredecessorAmbiguous(ConflictError):
    """Several subscriptions of the member and share type end the day before a
    new one starts, so it can't be told which one the new one continues — and
    left unlinked, the renewal sweep would draft a second next term for it."""

    code = "subscription.term_predecessor_ambiguous"

    def __init__(self, *, valid_until: str, count: int) -> None:
        super().__init__(
            f"{count} subscriptions of this member and share type end on "
            f"{valid_until}; it can't be told which one this one continues.",
            details={"valid_until": valid_until, "count": count},
        )


# --------------------------------------------------------------------------- #
# Subscription cancellation                                                   #
# --------------------------------------------------------------------------- #


class SubscriptionCancellationError(BadRequestError):
    """Base for the validation failures raised by ``cancel_subscription``.

    Each concrete subclass carries a stable ``code`` so the frontend i18n
    layer can key on it and the tests can assert on the failure mode rather
    than a free-text English substring.
    """

    code = "subscription.cancel.invalid"


class SubscriptionNotConfirmed(SubscriptionCancellationError):
    """Only admin-confirmed subscriptions can be cancelled."""

    code = "subscription.cancel.not_confirmed"


class CancellationNotSunday(SubscriptionCancellationError):
    """``effective_at`` must fall on a Sunday (the end-of-delivery-week
    boundary that ``TimeBoundMixin.valid_until`` requires)."""

    code = "subscription.cancel.not_sunday"


class CancellationInPast(SubscriptionCancellationError):
    """``effective_at`` is before the next-Sunday floor — a cancellation
    cannot take effect in the past."""

    code = "subscription.cancel.in_past"


class CancellationBeforeValidFrom(SubscriptionCancellationError):
    """``effective_at`` is before the subscription's ``valid_from`` (a
    future-dated subscription cannot be cancelled before it has begun)."""

    code = "subscription.cancel.before_valid_from"


class CancellationAfterValidUntil(SubscriptionCancellationError):
    """``effective_at`` is after the subscription's ``valid_until`` — refusing
    so the office can't accidentally EXTEND the term."""

    code = "subscription.cancel.after_valid_until"


class NoSundayRemainsInTerm(SubscriptionCancellationError):
    """The next-Sunday floor is already past ``valid_until`` — there is no
    Sunday left to cancel into; let the term expire naturally."""

    code = "subscription.cancel.no_sunday_remains"


# --------------------------------------------------------------------------- #
# Additional-share (Zusatz) subscription rules                                #
# --------------------------------------------------------------------------- #


class AdditionalShareRequiresBase(BadRequestError):
    """An additional share ("Zusatz") is packed INTO a base box, so it can't be
    subscribed on its own: the member must already have a non-additional (base)
    share active over the same period."""

    code = "subscription.additional_requires_base"

    def __init__(self, *, share_type_variation_id: str) -> None:
        super().__init__(
            "This is an additional share and can only be added when the member "
            "already has a base share active for the same period.",
            field="share_type_variation",
            details={"share_type_variation_id": str(share_type_variation_id)},
        )


class AdditionalShareExceedsBase(BadRequestError):
    """The additional share would run past the end of the member's base share.
    Allowed, but only up to the base's effective end — that date is offered as
    ``suggested_valid_until`` so the frontend can prefill it."""

    code = "subscription.additional_exceeds_base"

    def __init__(self, *, suggested_valid_until) -> None:
        super().__init__(
            "An additional share cannot run longer than the base share it is "
            f"packed into. Set the end date to {suggested_valid_until} (the "
            "base share's end) to continue.",
            field="valid_until",
            details={"suggested_valid_until": str(suggested_valid_until)},
        )


# --------------------------------------------------------------------------- #
# On-off opt-in errors                                                        #
# --------------------------------------------------------------------------- #


class OptinNotApplicable(BadRequestError):
    """Caller tried to toggle ``is_opted_in`` on a ShareDelivery whose
    variation has ``requires_optin=False``. Use ``joker_taken`` (the
    opt-out path) for normal variations."""

    code = "optin.not_applicable"


class OptinDeadlinePassed(ConflictError):
    """Caller tried to toggle ``is_opted_in`` after the variation's
    ``optin_deadline_days_before_delivery`` cutoff. The decision is
    locked at the value it had when the deadline lapsed; the office
    runbook covers exceptional overrides via direct DB."""

    code = "optin.deadline_passed"
