"""Auto-renewal: create draft renewals for subscriptions whose cancellation
deadline has lapsed uncancelled.

A renewal is a fresh ``Subscription`` for the term immediately following the
current one — same member, quantity, payment cycle and delivery station-day,
re-resolved price, and the same-size successor variation if the current one has
ended. It is created **unconfirmed** (``admin_confirmed=False``) so the office
reviews and confirms it; the normal confirm flow then materialises Shares /
ShareDeliveries / charges. Each subscription renews inside its own transaction;
a failure is captured with a per-subscription reason code (surfaced to the office
— the daily sweep logs it per row + emails a digest, the bulk-renew button
returns it) rather than aborting the run. At most one renewal per predecessor is
enforced by a DB partial-unique constraint, so a race is a caught failure, never
a forked chain.
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet

from apps.commissioning.models import (
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    Subscription,
)

ops_log = logging.getLogger("tasks")


def find_renewable_subscriptions(
    today: datetime.date, min_weeks_to_cancel: int
) -> QuerySet[Subscription]:
    """Confirmed, non-trial subscriptions whose cancellation deadline
    (``valid_until - min_weeks_to_cancel`` weeks) has passed while they are
    still running, whose member is active, and that have not been renewed yet.
    """
    deadline_cutoff = today + datetime.timedelta(weeks=min_weeks_to_cancel)
    return Subscription.objects.filter(
        admin_confirmed=True,
        is_trial=False,
        cancelled_at__isnull=True,
        member__cancelled_at__isnull=True,
        # ``is_active=False`` is currently only set by GDPR anonymisation — an
        # anonymised member must never be auto-renewed. Kept in lock-step with
        # ``manual_renewal_skip_reason`` (SKIP_MEMBER_INACTIVE).
        member__is_active=True,
        valid_until__isnull=False,
        # already started: a term SHORTER than the notice period has its
        # cancellation deadline before its own start, which would otherwise
        # make it auto-renew on day one — only renew once
        # ``today >= max(valid_from, valid_until - min_weeks)``.
        valid_from__lte=today,
        # still running (term not yet over) …
        valid_until__gte=today,
        # … but past the cancellation deadline.
        valid_until__lte=deadline_cutoff,
        # not already renewed (reverse of ``previous_subscription``)
        renewals__isnull=True,
    )


def resolve_variation_for_term(
    old_variation: ShareTypeVariation,
    valid_from: datetime.date,
    valid_until: datetime.date,
) -> ShareTypeVariation | None:
    """The ``(share_type, size)`` lineage member whose validity window covers
    the whole ``[valid_from, valid_until]`` term, or ``None`` if there is a gap
    (the current variation ended with no same-size successor reaching across the
    new term). Variations are non-overlapping per ``(share_type, size)``, so at
    most one row can cover the whole span — the current variation if still open,
    otherwise its documented successor.
    """
    return (
        ShareTypeVariation.objects.filter(
            share_type_id=old_variation.share_type_id,
            size=old_variation.size,
            valid_from__lte=valid_from,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=valid_until))
        .order_by("-valid_from")
        .first()
    )


def _resolve_price(
    variation: ShareTypeVariation, on_date: datetime.date
) -> Decimal | None:
    gross = (
        ShareTypeVariationGrossPrice.current.active_at_date(on_date.isoformat())
        .filter(share_type_variation_id=variation.pk)
        # Overlapping windows are only guarded by clean(); newest-effective wins
        # deterministically instead of DB-arbitrary ``.first()`` order.
        .order_by("-valid_from")
        .first()
    )
    return gross.price_per_delivery if gross is not None else None


def _most_recent_reference_price(
    variation: ShareTypeVariation, on_date: datetime.date
) -> Decimal | None:
    """The variation's newest REFERENCE price window starting on/before
    ``on_date``, regardless of whether it is still open — the fallback when no
    window is active at the renewal start. Always a reference figure from a
    price window, never a member/office-chosen per-subscription price."""
    gross = (
        ShareTypeVariationGrossPrice.objects.filter(
            share_type_variation_id=variation.pk,
            valid_from__lte=on_date,
        )
        .order_by("-valid_from")
        .first()
    )
    return gross.price_per_delivery if gross is not None else None


@transaction.atomic
def create_renewal_draft(subscription: Subscription) -> Subscription:
    """Create the unconfirmed renewal draft following ``subscription``'s term.

    Raises ``RenewalVariationUnavailable`` if no variation covers the new term;
    the model's ``clean()`` may also raise (e.g. the carried-over delivery
    station-day doesn't reach into the new term) — both bubble up to
    ``run_renewals``, which records the failure for the office.
    """
    term_length = subscription.valid_until - subscription.valid_from
    new_valid_from = subscription.valid_until + datetime.timedelta(days=1)
    new_valid_until = new_valid_from + term_length

    variation = resolve_variation_for_term(
        subscription.share_type_variation, new_valid_from, new_valid_until
    )
    if variation is None:
        from apps.commissioning.errors import RenewalVariationUnavailable

        raise RenewalVariationUnavailable(
            "No share-type variation of the same size covers the renewal term "
            f"{new_valid_from} – {new_valid_until}.",
        )

    # Re-resolve the price on the new term's start. When no window is active
    # there yet, fall back to the variation's most recent REFERENCE window —
    # NEVER to the predecessor's stored ``price_per_delivery``: that figure can
    # be a member-chosen solidarity or office custom price, and the renewal
    # must reset to reference on every path (the active-window path already
    # does; a fallback carrying the old figure would silently perpetuate an
    # over/underpayment into the new term). Because the price always comes
    # from a price window's reference figure, the solidarity floor is
    # satisfied by construction — no separate floor check needed here.
    price = _resolve_price(variation, new_valid_from)
    if price is None:
        price = _most_recent_reference_price(variation, new_valid_from)
    if price is None:
        # No price window on/before the new start at all — creating the draft
        # would bill a fully €0 term on confirm. Refuse it (FAIL_NO_PRICE);
        # the office adds a gross-price window and renews again.
        from apps.commissioning.errors import RenewalPriceUnavailable

        raise RenewalPriceUnavailable(
            "No price could be resolved for the renewal term "
            f"{new_valid_from} – {new_valid_until}.",
        )

    return Subscription.objects.create(
        member=subscription.member,
        share_type_variation=variation,
        previous_subscription=subscription,
        valid_from=new_valid_from,
        valid_until=new_valid_until,
        quantity=subscription.quantity,
        price_per_delivery=price,
        payment_cycle=subscription.payment_cycle,
        default_delivery_station_day=subscription.default_delivery_station_day,
        is_trial=False,
        admin_confirmed=False,
    )


# Reason codes for renewal outcomes. SKIP_* = the subscription is ineligible;
# FAIL_* = it's eligible but a draft couldn't be created. Both the daily sweep
# (rich per-row log + office digest) and the office bulk-renew button use these;
# the frontend maps each to a localized label so the office sees exactly why a
# selected row did not renew.
SKIP_NOT_CONFIRMED = "not_confirmed"
SKIP_TRIAL = "trial"
SKIP_CANCELLED = "cancelled"
SKIP_MEMBER_CANCELLED = "member_cancelled"
SKIP_MEMBER_INACTIVE = "member_inactive"
SKIP_OPEN_ENDED = "open_ended"
SKIP_ALREADY_RENEWED = "already_renewed"
FAIL_NO_VARIATION = "no_variation"
FAIL_NO_PRICE = "no_price"
FAIL_DSD_COVERAGE = "dsd_coverage"
FAIL_INVALID = "invalid"


def _renewal_business_errors() -> tuple[type[Exception], ...]:
    """The exception types a per-row renewal is EXPECTED to raise (no covering
    variation, the carried-over station-day not reaching the new term, a
    validation failure, or the one-renewal-per-predecessor unique constraint
    losing a race). Callers catch exactly these and let everything else — lost
    DB connections, genuine bugs — propagate rather than masking an outage as N
    benign row failures."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.db import IntegrityError

    from apps.commissioning.errors import (
        RenewalChainNumberMissing,
        RenewalPriceUnavailable,
        RenewalVariationUnavailable,
        SubscriptionDeliveryStationDayOutOfRange,
    )

    return (
        RenewalVariationUnavailable,
        RenewalPriceUnavailable,
        # Predecessor has no subscription_number to inherit (created bypassing
        # save()) — a data-repair case, counted per-row (FAIL_INVALID + warning)
        # so one broken chain doesn't abort the whole sweep/batch.
        RenewalChainNumberMissing,
        SubscriptionDeliveryStationDayOutOfRange,
        DjangoValidationError,
        IntegrityError,
    )


def _classify_renewal_failure(exc: Exception) -> str:
    """Map an expected ``create_renewal_draft`` failure to a ``FAIL_*`` code."""
    from apps.commissioning.errors import (
        RenewalPriceUnavailable,
        RenewalVariationUnavailable,
        SubscriptionDeliveryStationDayOutOfRange,
    )

    if isinstance(exc, RenewalVariationUnavailable):
        return FAIL_NO_VARIATION
    if isinstance(exc, RenewalPriceUnavailable):
        return FAIL_NO_PRICE
    if isinstance(exc, SubscriptionDeliveryStationDayOutOfRange):
        return FAIL_DSD_COVERAGE
    return FAIL_INVALID


def _outcome_item(subscription: Subscription, reason: str) -> dict:
    """One outcome row for a subscription that was skipped / failed to renew.
    ``id`` + ``label`` + ``reason`` are the office-facing minimum (the bulk-renew
    endpoint serialises exactly those); the ``member_*`` fields enrich the daily
    sweep's office digest email (ignored by the endpoint serializer)."""
    member = subscription.member
    return {
        "id": str(subscription.pk),
        "label": subscription.renewal_display_id,
        "reason": reason,
        "member_id": str(member.id),
        "member_name": f"{member.first_name} {member.last_name}".strip(),
        "member_number": member.member_number,
    }


def run_renewals(today: datetime.date, min_weeks_to_cancel: int) -> dict:
    """Walk every renewable subscription, creating its draft renewal in its own
    transaction. Successes land in the abos table as unconfirmed drafts (the
    office reviews + confirms them). A failure (no variation covering the new
    term, the carried-over station-day not reaching into it, …) creates no
    draft, so the source stays renewable and the next run retries.

    Returns ``{"created": int, "failed": [outcome items]}`` where each failed
    item is ``{id, label, reason, member_*}`` — the caller (daily task) logs
    each row (member + reason, not just a pk) and emails the office a digest so
    the members who did NOT renew are visible, not buried in a counter. Only the
    expected business failures are caught; infra errors propagate (they must not
    be miscounted as row failures — see ``_renewal_business_errors``).

    Materialises the candidate set first so creating renewals (which populate
    the ``renewals`` reverse relation) can't disturb the iteration.
    """
    created = 0
    failed: list[dict] = []
    candidates = find_renewable_subscriptions(today, min_weeks_to_cancel)
    for subscription in list(
        candidates.select_related("member", "share_type_variation")
    ):
        try:
            # ``create_renewal_draft`` is itself ``@transaction.atomic`` — a
            # failure rolls back its own writes, leaving no partial renewal.
            create_renewal_draft(subscription)
            created += 1
        except _renewal_business_errors() as exc:
            reason = _classify_renewal_failure(exc)
            item = _outcome_item(subscription, reason)
            failed.append(item)
            ops_log.warning(
                "renewal.failed subscription=%s member=%s label=%s reason=%s error=%s",
                item["id"],
                item["member_id"],
                item["label"],
                reason,
                exc,
            )
    return {"created": created, "failed": failed}


def manual_renewal_skip_reason(subscription: Subscription) -> str | None:
    """Why this subscription can't be manually renewed (a reason code the
    frontend localizes), or ``None`` if it can.

    The office CAN renew any subscription that is confirmed, not a trial, not
    cancelled, whose member is not cancelled, that has an end date (an
    open-ended term never ends, so there is nothing to renew), and that has not
    already been renewed. These are the same exclusions as the daily sweep
    MINUS the deadline window — the office picks the rows explicitly, so it may
    renew ahead of the deadline."""
    if not subscription.admin_confirmed:
        return SKIP_NOT_CONFIRMED
    if subscription.is_trial:
        return SKIP_TRIAL
    if subscription.cancelled_at is not None:
        return SKIP_CANCELLED
    if subscription.member.cancelled_at is not None:
        return SKIP_MEMBER_CANCELLED
    # Lock-step with ``find_renewable_subscriptions``: is_active=False currently
    # means GDPR-anonymised — never renewable.
    if not subscription.member.is_active:
        return SKIP_MEMBER_INACTIVE
    if subscription.valid_until is None:
        return SKIP_OPEN_ENDED
    # ``bulk_renew`` annotates ``_has_renewal`` so the whole batch resolves the
    # "already renewed" check in one query; a plain instance (single-row caller)
    # falls back to the per-row EXISTS.
    has_renewal = getattr(subscription, "_has_renewal", None)
    if has_renewal is None:
        has_renewal = subscription.renewals.exists()
    if has_renewal:
        return SKIP_ALREADY_RENEWED
    return None


def bulk_renew(subscription_ids: list[str]) -> dict:
    """Renew the given subscriptions on demand (office bulk-renew button) with the
    same per-subscription logic + unconfirmed-draft output as the daily sweep.

    Returns ``{"created": int, "skipped": [...], "failed": [...]}`` where each
    skipped / failed item is ``{"id", "label", "reason", ...}`` — so the office
    sees exactly which selected subscriptions did NOT renew and why. Ineligible
    rows are skipped (with a reason); an eligible row whose draft can't be
    created (no covering variation, station-day doesn't reach the new term, a key
    collision) is captured as failed (with a reason). Neither aborts the batch
    (each renewal is its own ``@transaction.atomic``). Genuine infrastructure
    errors (lost DB connection, programming bugs) are NOT swallowed — they
    propagate (see ``_renewal_business_errors``)."""
    created = 0
    skipped: list[dict] = []
    failed: list[dict] = []
    subscriptions = (
        Subscription.objects.filter(pk__in=list(subscription_ids))
        .select_related("member", "share_type_variation")
        .annotate(
            _has_renewal=Exists(
                Subscription.objects.filter(previous_subscription=OuterRef("pk"))
            )
        )
    )
    for subscription in subscriptions:
        reason = manual_renewal_skip_reason(subscription)
        if reason is not None:
            skipped.append(_outcome_item(subscription, reason))
            continue
        try:
            create_renewal_draft(subscription)
            created += 1
        except _renewal_business_errors() as exc:
            reason = _classify_renewal_failure(exc)
            if reason == FAIL_INVALID:
                ops_log.warning(
                    "renewal.bulk_invalid subscription=%s error=%s",
                    subscription.pk,
                    exc,
                )
            failed.append(_outcome_item(subscription, reason))
    return {"created": created, "skipped": skipped, "failed": failed}
