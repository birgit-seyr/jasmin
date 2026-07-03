"""Charge schedule generation + SEPA export services for member billing.

See `text/payments_design.md` for the design rationale.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from sepaxml import SepaDD
from sepaxml.validation import ValidationError as SepaXmlValidationError

from apps.commissioning.models import (
    ShareDelivery,
    Subscription,
)
from apps.commissioning.models.choices_text import PaymentCycleOptions
from apps.commissioning.utils.iso_week_utils import share_delivery_date
from apps.shared.money import round_money as _money
from apps.shared.tenants.models import Tenant, TenantSettings

from .constants import BillingRunStatus, ChargeStatus, PaymentMethodOptions
from .errors import (
    BillingRunHasNoCharges,
    BillingRunInvalidCollectionDate,
    BillingRunInvalidPeriod,
    BillingRunMixedCurrency,
    BillingRunNotDraft,
    NoEligibleCharges,
    NoValidSepaMandates,
    SepaExportInvalid,
)
from .models import BillingProfile, BillingRun, ChargeSchedule

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_CYCLE_TO_RELATIVEDELTA: dict[str, relativedelta] = {
    PaymentCycleOptions.WEEKLY: relativedelta(weeks=1),
    PaymentCycleOptions.BIWEEKLY: relativedelta(weeks=2),
    PaymentCycleOptions.MONTHLY: relativedelta(months=1),
    PaymentCycleOptions.QUARTERLY: relativedelta(months=3),
    PaymentCycleOptions.SEMI_ANNUALLY: relativedelta(months=6),
    PaymentCycleOptions.ANNUALLY: relativedelta(years=1),
}


def _current_tenant() -> Tenant:
    """Resolve the active django-tenants tenant from the connection."""
    return Tenant.objects.get(schema_name=connection.schema_name)


@dataclass(frozen=True)
class _BillingConfig:
    """Snapshot of the dynamic billing settings for the current tenant.

    Pulled from `TenantSettings.get_current_settings(tenant)` with safe
    defaults if no settings row exists yet.
    """

    strategy: str
    bills_joker_deliveries: bool
    due_day: int

    @classmethod
    def for_tenant(cls, tenant: Tenant) -> _BillingConfig:
        ts = TenantSettings.get_current_settings(tenant)
        if ts is None:
            return cls(
                strategy=TenantSettings.BILLING_STRATEGY_EXACT,
                bills_joker_deliveries=False,
                due_day=1,
            )
        return cls(
            strategy=ts.billing_strategy,
            bills_joker_deliveries=ts.bills_joker_deliveries,
            due_day=ts.billing_due_day_of_month,
        )


def _due_date_for(period_start: date, period_end: date, billing_due_day: int) -> date:
    """Due date for a billing period: the configured day-of-month, clamped into
    the period.

    The candidate is ``billing_due_day`` (capped at 28 to dodge short months) in
    ``period_start``'s month. Clamping into ``[period_start, period_end]`` is what
    keeps the result honest across cycles:

    - a charge is never collectable BEFORE its period begins (the old code put
      the due date at e.g. the 1st even when the period started on the 15th);
    - sub-monthly cycles (weekly / biweekly) get a DISTINCT in-window due date
      per period instead of every period in a month collapsing onto the same
      monthly day (which bundled a member's weekly charges into one collection).
    """
    day = min(billing_due_day, 28)
    candidate = period_start.replace(day=day)
    if candidate < period_start:
        return period_start
    if candidate > period_end:
        return period_end
    return candidate


@dataclass(frozen=True)
class _Period:
    start: date
    end: date  # inclusive


def _iter_cycle_periods(
    valid_from: date, valid_until: date, cycle_choice: str
) -> Iterable[_Period]:
    """Walk the subscription's term in cycle-sized chunks.

    The first period starts at `valid_from`, the last ends at `valid_until`
    (inclusive). Periods are aligned to the subscription start, NOT to
    calendar boundaries — keeps the math predictable.
    """
    step = _CYCLE_TO_RELATIVEDELTA[cycle_choice]
    # CHG-3: anchor each boundary off the ORIGINAL valid_from (valid_from +
    # step*(i+1)) instead of re-adding step to the previous — possibly
    # month-clamped — cursor. relativedelta clamps e.g. Jan-31 + 1 month → Feb-28
    # and, if you keep adding to the clamped value, never recovers the 31st (it
    # ratchets down to the 28th for the rest of the term). Anchoring off
    # valid_from lets a day-29/30/31 start snap back to month-end whenever the
    # month allows. Periods stay contiguous (each end = next start − 1 day).
    index = 0
    cursor = valid_from
    while cursor <= valid_until:
        next_cursor = valid_from + step * (index + 1)
        end = min(next_cursor - timedelta(days=1), valid_until)
        yield _Period(cursor, end)
        index += 1
        cursor = next_cursor


# --------------------------------------------------------------------------- #
# ChargeScheduleService
# --------------------------------------------------------------------------- #


class ChargeScheduleService:
    """Generates and reconciles `ChargeSchedule` rows for subscriptions."""

    @staticmethod
    @transaction.atomic
    def regenerate_for_subscription(
        subscription: Subscription,
        deliveries: list[ShareDelivery] | None = None,
        *,
        tenant: Tenant | None = None,
        billing: _BillingConfig | None = None,
    ) -> int:
        """Regenerate PLANNED rows for a single subscription.

        Idempotent: existing PLANNED rows are updated/deleted as needed;
        ISSUED / PAID / FAILED / WAIVED rows are NEVER touched.

        ``deliveries`` lets the bulk ``regenerate_all`` path pass this
        subscription's ShareDeliveries (pre-fetched in one query for the whole
        set) so it doesn't run a ``filter(subscription=...)`` per row. When
        ``None`` (standalone call), they're fetched here as before.

        ``tenant`` / ``billing`` are run-invariant: the bulk ``regenerate_all``
        path resolves them ONCE and passes them in, so this method doesn't
        re-query the tenant + settings tables once per subscription. When
        ``None`` (standalone call), they're resolved here as before.

        Returns the count of PLANNED rows after the operation.
        """
        if not subscription.valid_from:
            logger.info("subscription %s has no valid_from; skipping", subscription.pk)
            return 0
        # BL-10: a waiting-list subscription must NOT get a billable ledger — it
        # is not yet a committed membership and must never enter a SEPA run. The
        # bulk regenerate_all path filters these out (on_waiting_list=False); the
        # single-subscription confirm/materialize path reaches here directly, so
        # apply the same exclusion in ONE place (the billing service) rather than
        # at every notify_subscription_changed call site.
        if subscription.on_waiting_list:
            logger.info(
                "subscription %s is on the waiting list; skipping billing",
                subscription.pk,
            )
            return 0
        valid_until = subscription.valid_until or (
            subscription.valid_from + relativedelta(years=1)
        )
        if valid_until < subscription.valid_from:
            return 0

        # Standalone entrypoint (the notify_subscription_changed handler hands us
        # an un-prefetched Subscription; the bulk regenerate_all path already
        # select_relates this chain and passes both ``tenant`` and
        # ``deliveries``). Re-load the chain once here so the per-period
        # ``subscription.share_type_variation`` deref in _description, the
        # ``subscription.member`` deref, and ``payment_cycle`` don't each
        # fire a lazy query (≈1 query replaces ~1-per-period + 2).
        if tenant is None and deliveries is None:
            subscription = Subscription.objects.select_related(
                "member",
                "share_type_variation",
                "payment_cycle",
            ).get(pk=subscription.pk)

        if tenant is None:
            tenant = _current_tenant()
        if billing is None:
            billing = _BillingConfig.for_tenant(tenant)
        cycle_choice = subscription.payment_cycle.choice

        ChargeScheduleService._lock_and_unbundle_stale_planned(
            subscription, valid_until
        )

        locked, locked_total, failed_periods = (
            ChargeScheduleService._resolve_locked_periods(subscription)
        )

        # Drop stale PLANNED rows; we'll recreate in the loop below. TXN-1: never
        # delete a PLANNED row already bundled into a run (``billing_run`` set) —
        # those are committed to a DRAFT run about to be exported and are kept in
        # ``locked`` above so their period isn't recreated either.
        ChargeSchedule.objects.filter(
            subscription=subscription,
            status=ChargeStatus.PLANNED,
            billing_run__isnull=True,
        ).delete()

        periods = list(
            _iter_cycle_periods(subscription.valid_from, valid_until, cycle_choice)
        )
        if not periods:
            return 0

        delivery_dates = ChargeScheduleService._billable_delivery_dates(
            subscription, deliveries, valid_until, billing
        )

        # SMOOTHED splits only the REMAINING term total (the recomputed total
        # minus what the locked ISSUED/PAID/... rows already collected) across
        # ONLY the still-unlocked periods, assigned by position among them. The
        # old code split the FULL total across ALL periods (locked included),
        # which double-counted the locked amounts and broke the sum==total
        # invariant whenever any charge had already left PLANNED (over- or
        # under-collecting the difference).
        smoothed_unlocked: list[Decimal] = []
        if billing.strategy == TenantSettings.BILLING_STRATEGY_SMOOTHED:
            smoothed_unlocked = ChargeScheduleService._smoothed_unlocked_amounts(
                subscription, delivery_dates, periods, locked, locked_total
            )

        return ChargeScheduleService._persist_planned_periods(
            subscription,
            tenant,
            billing,
            periods,
            delivery_dates,
            locked,
            failed_periods,
            smoothed_unlocked,
        )

    # ------------------------------------------------------------------ #
    # Phases of regenerate_for_subscription
    # ------------------------------------------------------------------ #
    @staticmethod
    def _lock_and_unbundle_stale_planned(
        subscription: Subscription, valid_until: date
    ) -> None:
        """Lock this subscription's PLANNED rows and unbundle stale DRAFT rows.

        Side-effecting only: takes the row lock and issues the two unbundle
        updates. Must run before the snapshot/delete/recreate below.
        """
        # CONC-1: serialize against ``BillingRunService.create_run`` on THIS
        # subscription's PLANNED charge rows before we snapshot/delete/recreate
        # them. Without this lock a concurrent create_run can bundle a
        # still-PLANNED row (set ``billing_run`` + commit) AFTER our snapshot;
        # the delete below (``billing_run__isnull=True``) then keeps that bundled
        # row, and the recreate loop attempts a fresh PLANNED row for the same
        # ``(subscription, period_start)`` — which hits the
        # ``chargeschedule_unique_subscription_period`` constraint and raises an
        # IntegrityError that rolls back the triggering subscription change.
        # ``create_run`` locks with ``skip_locked=True`` (services.py), so while
        # we hold these rows it simply skips this subscription and bundles the
        # freshly-recreated PLANNED rows on a later run — no deadlock cycle.
        # ``of=("self",)`` locks only the ChargeSchedule rows, not any join.
        list(
            ChargeSchedule.objects.select_for_update(of=("self",))
            .filter(subscription=subscription, status=ChargeStatus.PLANNED)
            .values_list("pk", flat=True)
        )

        # A cancellation can truncate ``valid_until`` below a PLANNED row an
        # operator already bundled into a DRAFT run for a now-removed future
        # period. That row sits OUTSIDE the regenerated term, so the loop below
        # never reconciles it, and the TXN-1 "keep bundled rows" lock would
        # otherwise let it reach export and SEPA-debit a cancelled period.
        # Unbundle DRAFT-bundled PLANNED rows whose period starts after the
        # (possibly truncated) term so the delete below drops them. Only DRAFT
        # runs + PLANNED rows are touched — ISSUED / exported charges are never
        # unbundled.
        ChargeSchedule.objects.filter(
            subscription=subscription,
            status=ChargeStatus.PLANNED,
            period_start__gt=valid_until,
            billing_run__status=BillingRunStatus.DRAFT,
        ).update(billing_run=None)

        # MEM-1: the cut can also land INSIDE a DRAFT-bundled period
        # (period_start <= valid_until < period_end) — a "straddling" row. Left
        # bundled it stays locked at its FULL, un-prorated amount and would
        # SEPA-debit both the served AND the now-cancelled portion. Unbundle it
        # too so the delete below drops it and the loop recreates it at the
        # clamped period [period_start, valid_until] with a prorated amount.
        # Same DRAFT-only / PLANNED-only safety; only relevant when truncated.
        if valid_until is not None:
            ChargeSchedule.objects.filter(
                subscription=subscription,
                status=ChargeStatus.PLANNED,
                period_start__lte=valid_until,
                period_end__gt=valid_until,
                billing_run__status=BillingRunStatus.DRAFT,
            ).update(billing_run=None)

    @staticmethod
    def _resolve_locked_periods(
        subscription: Subscription,
    ) -> tuple[set[date], Decimal, set[date]]:
        """Snapshot the immutable/locked periods for this subscription.

        Returns ``(locked, locked_total, failed_periods)``:
        the set of period-start dates we must NOT recreate, the amount already
        committed against them (subtracted from the term total before the
        SMOOTHED re-split), and the subset whose charge FAILED.
        """
        # Periods we must NOT recreate, and the amount already committed against
        # them. A period is locked if it has left PLANNED (ISSUED/PAID/...) OR —
        # TXN-1 — if a still-PLANNED row is already bundled into a BillingRun
        # (``billing_run`` set at create_run, status flips to ISSUED only at
        # export). Treating bundled rows as locked is what stops the delete below
        # from silently dropping a charge committed to a DRAFT run and lets no
        # fresh PLANNED row be recreated for that period (which a second run could
        # then bundle → double-charge).
        locked_rows = list(
            ChargeSchedule.objects.filter(subscription=subscription)
            .filter(Q(billing_run__isnull=False) | ~Q(status=ChargeStatus.PLANNED))
            .values_list("period_start", "expected_amount", "status", "billing_run_id")
        )
        locked = {period_start for period_start, _amount, _st, _br in locked_rows}
        # BIZ-4: periods whose charge FAILED (bank-returned) — the money is still
        # owed. Under SMOOTHED it stays in ``remaining`` and is re-spread; under
        # EXACT each period is independent, so a FAILED period is neither
        # recreated nor absorbed and would be silently written off. Surfaced in
        # the loop below.
        failed_periods = {
            ps for ps, _amt, st, _br in locked_rows if st == ChargeStatus.FAILED
        }
        # ``locked_total`` is subtracted from the term total before the SMOOTHED
        # split re-distributes the REMAINING amount over the still-unlocked
        # periods. It must hold every amount that the term no longer needs to
        # collect from the unlocked periods:
        #   * ISSUED / PAID / PARTIAL — money already committed/collected;
        #   * a bundled-but-still-PLANNED row — about to be collected (TXN-1);
        #   * WAIVED — a deliberate per-period FORGIVENESS. It MUST be in here:
        #     subtracting it drops ``remaining`` by the waived amount so the other
        #     periods keep their normal share and the member actually saves it.
        #     Leaving it OUT would keep the waived amount inside ``remaining`` and
        #     re-spread it across every other period — silently clawing the
        #     forgiveness back (MON-1 review fix).
        # FAILED is the ONE status left out on purpose: bank-returned money is
        # still owed, so excluding it keeps that amount in ``remaining`` and
        # re-bills it across the unlocked periods instead of writing it off.
        _SETTLED_STATUSES = {
            ChargeStatus.ISSUED,
            ChargeStatus.PAID,
            ChargeStatus.PARTIAL,
            ChargeStatus.WAIVED,
        }
        locked_total = sum(
            (
                amount
                for _ps, amount, status, billing_run_id in locked_rows
                if status in _SETTLED_STATUSES
                or (status == ChargeStatus.PLANNED and billing_run_id is not None)
            ),
            Decimal("0.00"),
        )
        return locked, locked_total, failed_periods

    @staticmethod
    def _billable_delivery_dates(
        subscription: Subscription,
        deliveries: list[ShareDelivery] | None,
        valid_until: date,
        billing: _BillingConfig,
    ) -> list[date]:
        """Resolve the billable delivery dates for this subscription's term.

        Pre-fetches deliveries when the bulk path didn't supply them, applies
        the joker + opt-in filters, then clamps to the enumerated term.
        """
        # Pre-fetch all relevant deliveries once (the bulk path supplies them).
        if deliveries is None:
            deliveries = list(
                ShareDelivery.objects.filter(
                    subscription=subscription,
                ).select_related("share__share_type_variation")
            )
        if not billing.bills_joker_deliveries:
            deliveries = [d for d in deliveries if not d.joker_taken]
        # On-off variations: only opted-in deliveries are billable. One rule,
        # shared with demand/preparation/Abos via the model — see
        # ``ShareDelivery.is_opted_in_for_delivery`` (joker is handled separately
        # above because it's gated on the ``bills_joker_deliveries`` setting).
        deliveries = [d for d in deliveries if d.is_opted_in_for_delivery]

        # CHG-4: clamp to the enumerated term so EXACT and SMOOTHED bill the SAME
        # set. Both consume ``delivery_dates`` — EXACT counts dates inside each
        # period, SMOOTHED counts ``len(...)``. A date OUTSIDE [valid_from,
        # valid_until] (e.g. a stray delivery past a truncated end) falls in no
        # period (EXACT drops it) yet still inflates the SMOOTHED total. Filtering
        # to the term makes ``len`` equal the sum of the per-period counts (the
        # periods partition the term), so the two strategies agree.
        return [
            d
            for d in (
                share_delivery_date(share_delivery) for share_delivery in deliveries
            )
            if d and subscription.valid_from <= d <= valid_until
        ]

    @staticmethod
    def _smoothed_unlocked_amounts(
        subscription: Subscription,
        delivery_dates: list[date],
        periods: list[_Period],
        locked: set[date],
        locked_total: Decimal,
    ) -> list[Decimal]:
        """SMOOTHED per-period amounts for the still-unlocked periods.

        Splits the REMAINING term total (recomputed total minus ``locked_total``)
        across only the unlocked periods, by position among them.
        """
        term_total = ChargeScheduleService._term_total(subscription, delivery_dates)
        remaining = term_total - locked_total
        # Clamp at zero. SMOOTHED front-loads even amounts, so the amount
        # locked into early ISSUED periods isn't proportional to the
        # deliveries they covered. If later deliveries are then dropped
        # (opt-out / joker / cancellation) the recomputed term total can
        # fall BELOW what's already locked → ``remaining`` goes negative,
        # which would create negative PLANNED charges (a refund this system
        # has no concept of, and which a SEPA pain.008 can't carry). The
        # unlocked periods bill 0 instead; the over-collection is owed back
        # out-of-band — so raise an operator-actionable ERROR (MEM-4) that
        # surfaces as a Sentry event (money owed back needs a human), rather
        # than clamping silently (there's no refund/credit model yet).
        if remaining < Decimal("0.00"):
            logger.error(
                "subscription %s SMOOTHED over-collection: locked %s > "
                "recomputed term total %s; %s owed back as an out-of-band "
                "refund (unlocked periods clamped to 0)",
                subscription.pk,
                locked_total,
                term_total,
                locked_total - term_total,
            )
            remaining = Decimal("0.00")
        n_unlocked = sum(1 for period in periods if period.start not in locked)
        return ChargeScheduleService._largest_remainder_split(remaining, n_unlocked)

    @staticmethod
    def _persist_planned_periods(
        subscription: Subscription,
        tenant: Tenant,
        billing: _BillingConfig,
        periods: list[_Period],
        delivery_dates: list[date],
        locked: set[date],
        failed_periods: set[date],
        smoothed_unlocked: list[Decimal],
    ) -> int:
        """Create a PLANNED row per still-unlocked period; return total count.

        Locked periods are skipped (but counted); unlocked periods get their
        SMOOTHED (by position among unlocked) or EXACT amount and a fresh row.
        """
        member = subscription.member
        created_count = 0
        unlocked_index = 0

        for period in periods:
            if period.start in locked:
                created_count += 1
                # BIZ-4: no production path sets FAILED yet; if a future
                # reconciliation endpoint does, a FAILED period under EXACT is
                # skipped here and its owed amount would vanish silently.
                # Surface it as an operator-actionable error (Sentry) instead —
                # actually re-billing it needs that endpoint to first supersede
                # the FAILED row (the (subscription, period_start) unique
                # constraint blocks a second row for the same period). Mirrors
                # the SMOOTHED over-collection error above.
                if (
                    period.start in failed_periods
                    and billing.strategy != TenantSettings.BILLING_STRATEGY_SMOOTHED
                ):
                    logger.error(
                        "subscription %s EXACT: FAILED charge for period %s is "
                        "still owed but not re-billed; reconcile manually",
                        subscription.pk,
                        period.start,
                    )
                continue

            if billing.strategy == TenantSettings.BILLING_STRATEGY_SMOOTHED:
                amount = smoothed_unlocked[unlocked_index]
                unlocked_index += 1
            else:
                amount = ChargeScheduleService._exact_amount_for_period(
                    subscription, delivery_dates, period
                )

            ChargeSchedule.objects.create(
                member=member,
                subscription=subscription,
                period_start=period.start,
                period_end=period.end,
                due_date=_due_date_for(period.start, period.end, billing.due_day),
                expected_amount=amount,
                currency=tenant.currency or "EUR",
                description=ChargeScheduleService._description(subscription, period),
                status=ChargeStatus.PLANNED,
            )
            created_count += 1

        return created_count

    # ------------------------------------------------------------------ #
    # Strategy: EXACT_PER_PERIOD
    # ------------------------------------------------------------------ #
    @staticmethod
    def _exact_amount_for_period(
        subscription: Subscription,
        delivery_dates: list[date],
        period: _Period,
    ) -> Decimal:
        if subscription.price_per_delivery is None:
            return Decimal("0.00")
        count = sum(1 for d in delivery_dates if period.start <= d <= period.end)
        unit = Decimal(subscription.price_per_delivery) * Decimal(subscription.quantity)
        return _money(unit * count)

    # ------------------------------------------------------------------ #
    # Strategy: SMOOTHED across the subscription term
    # ------------------------------------------------------------------ #
    @staticmethod
    def _term_total(
        subscription: Subscription,
        delivery_dates: list[date],
    ) -> Decimal:
        """Full SMOOTHED term total: price × quantity × billable-delivery count."""
        if subscription.price_per_delivery is None:
            return Decimal("0.00")
        return _money(
            Decimal(subscription.price_per_delivery)
            * Decimal(subscription.quantity)
            * Decimal(len(delivery_dates))
        )

    @staticmethod
    def _largest_remainder_split(total: Decimal, n: int) -> list[Decimal]:
        """Split ``total`` across ``n`` parts that sum EXACTLY to ``total``.

        Largest-remainder allocation: the total (in cents) is split as evenly
        as possible across ``n`` parts — the first ``remainder`` parts get one
        extra cent — so ``sum(parts) == total`` with no rounding drift (a
        uniform ``_money(total / n)`` would over/under-collect by up to ``n``
        cents). Deterministic by index. ``n <= 0`` (every period already
        locked) yields no parts.
        """
        if n <= 0:
            return []
        total_cents = int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))
        base, remainder = divmod(total_cents, n)
        return [
            (Decimal(base + (1 if i < remainder else 0)) / Decimal(100)).quantize(
                Decimal("0.01")
            )
            for i in range(n)
        ]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _description(subscription: Subscription, period: _Period) -> str:
        share_type_variation = getattr(subscription, "share_type_variation", None)
        label = str(share_type_variation) if share_type_variation else "Subscription"
        return f"{label} {period.start.isoformat()}-{period.end.isoformat()}"[:140]

    # ------------------------------------------------------------------ #
    @classmethod
    @transaction.atomic
    def regenerate_all(cls) -> dict[str, int]:
        subs = list(
            # Only BILLABLE subscriptions get a ledger. ``admin_confirmed=True``
            # excludes both unconfirmed and admin-rejected subs (reject clears
            # the flag); ``on_waiting_list=False`` excludes waiting-list subs.
            # Without this, never-confirmed / rejected / waiting-list subs got
            # PLANNED ChargeSchedule rows (zero-amount under EXACT), polluting
            # the ledger and the SEPA run.
            Subscription.objects.filter(
                admin_confirmed=True, on_waiting_list=False
            ).select_related(
                "member",
                # ``_description`` reads subscription.share_type_variation;
                # without this it fired one extra query per subscription.
                "share_type_variation",
                "payment_cycle",
            )
        )
        # Tenant + billing config are invariant across the whole run —
        # resolve them ONCE and pass down, so regenerate_for_subscription
        # doesn't re-query the tenant + settings tables per subscription.
        tenant = _current_tenant()
        billing = _BillingConfig.for_tenant(tenant)
        # Batch every subscription's ShareDeliveries into one query (was a
        # ``filter(subscription=...)`` per subscription inside the loop).
        deliveries_by_subscription: dict[str, list[ShareDelivery]] = {}
        subscription_ids = [sub.pk for sub in subs]
        if subscription_ids:
            for delivery in ShareDelivery.objects.filter(
                subscription_id__in=subscription_ids
            ).select_related("share__share_type_variation"):
                deliveries_by_subscription.setdefault(
                    delivery.subscription_id, []
                ).append(delivery)

        per_sub: dict[str, int] = {}
        for sub in subs:
            per_sub[str(sub.pk)] = cls.regenerate_for_subscription(
                sub,
                deliveries=deliveries_by_subscription.get(sub.pk, []),
                tenant=tenant,
                billing=billing,
            )
        return per_sub


# --------------------------------------------------------------------------- #
# SEPA remittance text (the pain.008 ``Ustrd`` — what the member sees on their
# bank statement). Operator-configurable per tenant; rendered at export time.
# --------------------------------------------------------------------------- #

# Used when ``Tenant.sepa_remittance_template`` is blank. Friendly + compact:
# "<creditor> – <Month> <Year>" (e.g. "Marillenhof – Juni 2026") instead of the
# internal ``ChargeSchedule.description`` (share label + ISO date range).
# Plain hyphen (not en-dash) — the SEPA Latin charset excludes "–", and
# sepaxml's clean=True would silently downgrade it to "-" anyway.
_DEFAULT_SEPA_REMITTANCE_TEMPLATE = "{creditor} - {month}"

# de is the platform's primary locale and the members are German-speaking, so
# ``{month}`` renders German month names. Tenants wanting locale-neutral text
# can use ``{period}`` (numeric dates) instead.
_DE_MONTHS = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def _render_remittance(
    template: str,
    *,
    creditor: str,
    member: str,
    period_start: date,
    period_end: date,
    amount: Decimal,
) -> str:
    """Render a tenant remittance template into the pain.008 ``Ustrd`` text.

    Substitution is literal ``str.replace`` (NOT ``str.format``) so a stray
    brace or an unknown ``{placeholder}`` in operator-entered text can never
    raise — unknown tokens are simply left in place. Supported placeholders:
    ``{creditor}``, ``{member}``, ``{month}``, ``{period}``, ``{amount}``.
    Result is trimmed to the ISO 20022 140-char ``Ustrd`` limit.
    """
    month = f"{_DE_MONTHS[period_start.month]} {period_start.year}"
    period = f"{period_start.strftime('%d.%m.%Y')}–{period_end.strftime('%d.%m.%Y')}"
    replacements = {
        "{creditor}": creditor,
        "{member}": member,
        "{month}": month,
        "{period}": period,
        "{amount}": f"{amount}",
    }
    text = template
    for token, value in replacements.items():
        text = text.replace(token, str(value))
    return text.strip()[:140]


# --------------------------------------------------------------------------- #
# BillingRunService — bundles eligible charges and exports a CSV
# --------------------------------------------------------------------------- #


class BillingRunService:
    """Builds a `BillingRun` and produces a German-bank CSV export."""

    @staticmethod
    @transaction.atomic
    def create_run(
        period_start: date,
        period_end: date,
        collection_date: date,
        *,
        created_by=None,
        payment_method: str = PaymentMethodOptions.SEPA_DIRECT_DEBIT,
    ) -> BillingRun:
        """Bundle eligible PLANNED charges into a new BillingRun (DRAFT).

        Eligible = status==PLANNED, due_date in [period_start, period_end],
        member has an active billing profile suited to `payment_method`.
        Caller still has to call :meth:`export` to produce files + flip status.
        """
        if period_end < period_start:
            raise BillingRunInvalidPeriod("period_end must be >= period_start")
        # RUN-4: enforce the past-date invariant in the service itself, not just
        # the create view — a management command / script / bulk job would
        # otherwise mint a DRAFT that fails at the bank on export. The
        # collection_date >= period_end relationship stays a soft warning:
        # advance / prepaid collection can legitimately debit before the period
        # ends, so it is not a hard error.
        if collection_date < timezone.localdate():
            raise BillingRunInvalidCollectionDate(
                f"collection_date {collection_date} is in the past."
            )
        if collection_date < period_end:
            logger.warning(
                "collection_date %s is before period_end %s",
                collection_date,
                period_end,
            )

        # ``select_for_update(skip_locked=True, of=("self",))`` locks the
        # eligible ChargeSchedule rows — and ONLY those (``of=("self",)``
        # excludes the select_related member / billing_profile joins, so a
        # locked member row can't make us skip an otherwise-free charge).
        # Two concurrent ``create_run`` calls therefore can't bundle the same
        # PLANNED charge into two different runs (which would double-charge a
        # SEPA mandate): the loser skips the locked rows and bundles whatever
        # is left — possibly nothing, surfacing as NoEligibleCharges. The lock
        # is acquired when the queryset is materialised below, inside the
        # method's @transaction.atomic.
        eligible = (
            ChargeSchedule.objects.select_related("member", "member__billing_profile")
            .select_for_update(skip_locked=True, of=("self",))
            .filter(
                status=ChargeStatus.PLANNED,
                due_date__gte=period_start,
                due_date__lte=period_end,
                billing_run__isnull=True,
            )
            # Only strictly-positive charges become payment lines: a SEPA
            # pain.008 direct-debit of zero is invalid, and a NEGATIVE amount
            # (a refund/over-collection) must never be debited or it fails the
            # XSD / the bank rejects the batch. ``> 0`` covers both — defensive
            # belt-and-braces alongside the regenerate clamp and the
            # regenerate_all billable filter (manual/legacy 0-amount rows).
            .filter(expected_amount__gt=Decimal("0.00"))
        )

        if payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT:
            eligible = eligible.filter(
                member__billing_profile__is_active=True,
                member__billing_profile__payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            )
        elif payment_method == PaymentMethodOptions.BANK_TRANSFER:
            # A BANK_TRANSFER run must only bundle charges whose member has an
            # active BANK_TRANSFER billing profile. Without this, a SEPA
            # member's PLANNED charge would be swept into the transfer run
            # (and vice-versa) — and ``export`` would then try to direct-debit
            # money the operator explicitly marked as bank transfer.
            eligible = eligible.filter(
                member__billing_profile__is_active=True,
                member__billing_profile__payment_method=PaymentMethodOptions.BANK_TRANSFER,
            )

        eligible_list = list(eligible)
        if not eligible_list:
            # Diagnose the empty result so the operator isn't misled into
            # thinking the PERIOD is wrong: the common cause is members without
            # an active billing profile / mandate, not an empty period.
            planned_in_period = ChargeSchedule.objects.filter(
                status=ChargeStatus.PLANNED,
                due_date__gte=period_start,
                due_date__lte=period_end,
                billing_run__isnull=True,
                expected_amount__gt=Decimal("0.00"),
            ).count()
            if planned_in_period:
                raise NoEligibleCharges(
                    f"{planned_in_period} PLANNED charge(s) are due between "
                    f"{period_start} and {period_end}, but none belong to a "
                    f"member with an active {payment_method} billing profile / "
                    "mandate. Set up the members' payment details first."
                )
            raise NoEligibleCharges(
                "No PLANNED charges with a positive amount are due between "
                f"{period_start} and {period_end} (and not already in a run)."
            )

        # Filter out anything where the profile isn't actually SEPA-ready.
        if payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT:
            eligible_list = [
                c for c in eligible_list if c.member.billing_profile.is_sepa_ready
            ]
        if not eligible_list:
            raise NoValidSepaMandates("No charges with valid SEPA mandates.")

        # MON-3: ``total_amount`` below sums ``expected_amount`` across the
        # eligible charges. A mixed-currency set would yield a meaningless
        # cross-currency total (for SEPA the per-charge EUR guard fires at export,
        # but a BANK_TRANSFER run never hits it). Require a single currency.
        currencies = {(c.currency or "EUR") for c in eligible_list}
        if len(currencies) > 1:
            raise BillingRunMixedCurrency(
                "Eligible charges span multiple currencies "
                f"({', '.join(sorted(currencies))}); a run must be single-currency.",
                details={"currencies": sorted(currencies)},
            )

        run = BillingRun.objects.create(
            created_by=created_by,
            period_start=period_start,
            period_end=period_end,
            collection_date=collection_date,
            payment_method=payment_method,
            status=BillingRunStatus.DRAFT,
            total_amount=sum((c.expected_amount for c in eligible_list), Decimal("0")),
            charge_count=len(eligible_list),
            msg_id=f"BR-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}",
        )

        for c in eligible_list:
            c.billing_run = run
            # EndToEndId is the per-transaction reconciliation key (matched back
            # from bank-statement lines to a ChargeSchedule). msg_id is constant
            # within a run, so uniqueness rests on the charge pk — carry the FULL
            # 12-char pk (``msg_id[:22] + "-" + 12 == 35``, the EndToEndId max)
            # rather than truncating it to 9 and discarding reconciliation keyspace.
            c.end_to_end_id = f"{run.msg_id[:22]}-{c.pk}"[:35]
        # One UPDATE for the whole batch instead of a per-charge save(). A
        # save() on each freshly-locked PLANNED row would fire its immutability
        # reload SELECT *and* (ChargeSchedule is auditlog-registered) an
        # old-row fetch + a log INSERT — roughly three extra queries per charge,
        # all inside the lock-holding @transaction.atomic. bulk_update writes
        # billing_run + end_to_end_id in a single statement. Only those two
        # mutable columns change on PLANNED rows, so the immutability guard is a
        # no-op here regardless. (The bundling step is therefore not recorded in
        # auditlog; the BillingRun.charges relation is the record of membership,
        # and the audited money-event is the export → ISSUED status flip, which
        # still goes through save().)
        ChargeSchedule.objects.bulk_update(
            eligible_list, ["billing_run", "end_to_end_id"]
        )
        return run

    # ------------------------------------------------------------------ #
    @staticmethod
    @transaction.atomic
    def export(run: BillingRun) -> BillingRun:
        """Export a DRAFT run and flip its charges to ISSUED.

        SEPA_DIRECT_DEBIT runs produce a SEPA ISO 20022 Direct Debit
        Initiation file (pain.008.001.02, ``CstmrDrctDbtInitn`` root) — one
        PaymentInformation block per sequence type; we emit FRST (first use
        of a mandate, read from ``BillingProfile.sepa_mandate_first_use_at``)
        and RCUR (recurring).

        BANK_TRANSFER runs produce NO direct-debit file — those charges are
        settled manually by the operator (the member transfers the money).
        Building a pain.008 here would either 400 for the first member
        without SEPA fields or, worse, pull money the operator explicitly
        marked as bank transfer.
        """
        # Re-fetch the run under a row lock and re-check status INSIDE the
        # transaction. ``run`` arrived as an unlocked get_object() snapshot, so
        # two concurrent exports of the same DRAFT run would both read DRAFT and
        # both produce a valid, persisted pain.008 — two direct-debit files for
        # the same charges (double-debit). With the lock, the second export
        # blocks here until the first commits its EXPORTED flip, then reads
        # EXPORTED and raises BillingRunNotDraft (409) instead of a second file.
        run = BillingRun.objects.select_for_update().get(pk=run.pk)
        if run.status != BillingRunStatus.DRAFT:
            raise BillingRunNotDraft(f"Run already {run.status}, cannot re-export.")

        charges = list(
            run.charges.select_related("member", "member__billing_profile").order_by(
                "pk"
            )
        )
        if not charges:
            raise BillingRunHasNoCharges("Run has no charges.")

        is_sepa = run.payment_method == PaymentMethodOptions.SEPA_DIRECT_DEBIT

        # RUN-2: collection_date is frozen at create_run. A DRAFT exported days
        # later must still settle in the future — a pain.008 RequestedCollectionDate
        # in the past is rejected by the bank for the WHOLE batch. Fail loudly here
        # rather than ship a doomed file (the run stays DRAFT, the @transaction
        # rolls back, so the operator can rebuild with a future date).
        today = timezone.localdate()
        if is_sepa and run.collection_date < today:
            raise BillingRunInvalidCollectionDate(
                f"collection_date {run.collection_date} is in the past "
                f"(today is {today}); rebuild the run with a future date.",
                details={"collection_date": str(run.collection_date)},
            )

        if is_sepa:
            # Serialise concurrent exports that share a SEPA mandate. ``charges``
            # was select_related off a PRE-LOCK snapshot, so two DRAFT runs each
            # holding different charges of the same never-used mandate could both
            # read ``sepa_mandate_first_use_at IS NULL`` and both emit FRST — a
            # duplicate first-collection sequence the bank rejects. Lock the
            # billing profiles (ordered by pk to keep the lock order deterministic
            # / deadlock-free) and re-attach the freshly-read rows to the charges,
            # so BOTH the XML builder and the stamp loop below see the value AS OF
            # the lock. The second concurrent export blocks here until the first
            # commits its first-use stamp, then reads non-NULL and emits RCUR.
            locked_profiles = {
                bp.pk: bp
                for bp in BillingProfile.objects.select_for_update()
                .filter(
                    pk__in={
                        c.member.billing_profile.pk
                        for c in charges
                        if getattr(c.member, "billing_profile", None) is not None
                    }
                )
                .order_by("pk")
            }
            for c in charges:
                profile = getattr(c.member, "billing_profile", None)
                if profile is not None:
                    c.member.billing_profile = locked_profiles.get(profile.pk, profile)

            # RUN-1 / TXN-2: eligibility (is_active / payment_method / mandate
            # completeness — all folded into ``is_sepa_ready``) was checked at
            # create_run. A profile deactivated, switched to bank transfer, or
            # stripped of its mandate AFTER create_run but BEFORE export keeps its
            # IBAN/mandate columns, so without re-checking we would direct-debit a
            # mandate the operator revoked — a chargeback-able SEPA R-transaction
            # and a compliance breach. Re-assert ``is_sepa_ready`` on the
            # freshly-locked profiles and refuse the whole export if any charge's
            # mandate is no longer collectable (the run stays DRAFT for rebuild).
            not_ready = [
                c
                for c in charges
                if not getattr(
                    getattr(c.member, "billing_profile", None),
                    "is_sepa_ready",
                    False,
                )
            ]
            if not_ready:
                raise SepaExportInvalid(
                    f"Cannot export: {len(not_ready)} charge(s) belong to a billing "
                    "profile that is no longer SEPA-ready (mandate deactivated, "
                    "switched to bank transfer, or missing IBAN/mandate). Rebuild "
                    "the run so these charges are re-evaluated.",
                    details={
                        "charges": [c.pk for c in not_ready],
                        "members": sorted({str(c.member_id) for c in not_ready}),
                    },
                )

            xml_bytes = BillingRunService._build_pain008_xml(run, charges)
            run.sepa_xml_export.save(
                f"billing_run_{run.pk}.xml", ContentFile(xml_bytes), save=False
            )

        # Mark charges as ISSUED + bump first-use date for SEPA mandates only.
        for c in charges:
            c.status = ChargeStatus.ISSUED
            c.save(allow_immutable_change=True)

            if is_sepa:
                billing_profile = c.member.billing_profile
                if billing_profile.sepa_mandate_first_use_at is None:
                    billing_profile.sepa_mandate_first_use_at = today
                    billing_profile.save()

        # TXN-3: the totals snapshotted at create_run can drift if charges were
        # deleted / unbundled between create and export. Re-derive them from the
        # charges actually issued so the operator's confirmation and the
        # DebitsAbos list reflect what really went into the file.
        run.charge_count = len(charges)
        run.total_amount = sum((c.expected_amount for c in charges), Decimal("0"))

        run.status = BillingRunStatus.EXPORTED
        run.save()
        return run

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_pain008_xml(run: BillingRun, charges: list[ChargeSchedule]) -> bytes:
        """Build a pain.008.001.02 SEPA Direct Debit XML for the run.

        Uses the ``sepaxml`` library so the generated document is
        schema-validated against the bundled XSD before it leaves the
        process — a malformed file can never reach the office. Missing
        creditor / debtor fields raise :class:`SepaExportInvalid`
        (a ``BadRequestError`` → HTTP 400 with the offending fields in
        ``details``).

        Rows are ordered ``(member_id, due_date, end_to_end_id)`` so
        the file is deterministic across re-runs of the same set of
        charges (locked by
        ``apps/payments/tests/test_billing_run_pain008.py``).
        """
        tenant = connection.tenant

        # --- Creditor identity (the farm / cooperative) -----------------
        # These fields used to be dormant; the move to pain.008 makes
        # them load-bearing. Fail loudly here rather than producing a
        # half-built XML the bank would reject anyway.
        creditor_name = (tenant.sepa_creditor_name or "").strip()
        creditor_id = (tenant.sepa_creditor_id or "").strip()
        creditor_iban = (tenant.iban or "").replace(" ", "")
        # ``sepaxml`` requires BIC in its config even though
        # pain.008.001.02 marks the field as optional in the actual
        # XML. The library validates the config up-front and won't
        # accept an empty BIC — so we require it here for parity.
        creditor_bic = (tenant.sepa_creditor_bic or "").strip().upper()
        missing = [
            name
            for name, value in (
                ("Tenant.sepa_creditor_name", creditor_name),
                ("Tenant.sepa_creditor_id", creditor_id),
                ("Tenant.iban", creditor_iban),
                ("Tenant.sepa_creditor_bic", creditor_bic),
            )
            if not value
        ]
        if missing:
            raise SepaExportInvalid(
                "Cannot export SEPA XML: tenant is missing required "
                "creditor fields: " + ", ".join(missing),
                details={"missing_creditor_fields": missing},
            )

        config = {
            "name": creditor_name,
            "IBAN": creditor_iban,
            "BIC": creditor_bic,
            "batch": True,
            "creditor_id": creditor_id,
            "currency": "EUR",
        }
        sepa = SepaDD(config, schema="pain.008.001.02", clean=True)

        # Operator-configurable bank-statement text (pain.008 ``Ustrd``). Blank
        # → a friendly default ("{creditor} – {month}"). Rendered per charge
        # below so each member sees readable text instead of the internal
        # ``ChargeSchedule.description`` (share label + ISO date range).
        remittance_template = (
            tenant.sepa_remittance_template or ""
        ).strip() or _DEFAULT_SEPA_REMITTANCE_TEMPLATE

        ordered = sorted(
            charges,
            key=lambda c: (c.member_id, c.due_date, c.end_to_end_id or c.pk),
        )
        # Mandates already assigned their single FRST in THIS file. SEPA
        # allows only one FRST per mandate, so a never-used mandate with
        # several charges in one run gets FRST on the first transaction and
        # RCUR on the rest (see the per-mandate sequence logic below).
        frst_assigned: set = set()
        today = timezone.localdate()
        for c in ordered:
            billing_profile = getattr(c.member, "billing_profile", None)
            if billing_profile is None:
                raise SepaExportInvalid(
                    f"Charge {c.pk}: member has no billing_profile; "
                    "cannot include in SEPA XML.",
                    details={"charge": str(c.pk)},
                )
            mandate_ref = (billing_profile.sepa_mandate_reference or "").strip()
            mandate_signed = billing_profile.sepa_mandate_signed_at
            debtor_iban = (billing_profile.iban or "").replace(" ", "")
            debtor_name = (billing_profile.account_holder or "").strip()
            if not (mandate_ref and mandate_signed and debtor_iban and debtor_name):
                raise SepaExportInvalid(
                    f"Charge {c.pk}: debtor missing mandate fields "
                    "(mandate_reference, mandate_signed_at, IBAN, "
                    "account_holder are all required).",
                    details={"charge": str(c.pk)},
                )

            # RUN-5: a mandate signed in the FUTURE (DtOfSgntr) is logically
            # invalid and some banks reject the batch. sepaxml only checks it is a
            # date instance, so guard it here before it reaches the file.
            if mandate_signed > today:
                raise SepaExportInvalid(
                    f"Charge {c.pk}: sepa_mandate_signed_at {mandate_signed} is in "
                    "the future; a SEPA mandate cannot be dated after today.",
                    details={
                        "charge": str(c.pk),
                        "mandate_signed_at": str(mandate_signed),
                    },
                )

            # pain.008 is EUR-only — the file's currency is hardcoded EUR above.
            # A charge stamped with a non-EUR currency (tenant.currency is a
            # free CharField) would otherwise be silently direct-debited as the
            # same numeric amount in EUR. Fail loudly instead of emitting a
            # wrong-currency debit.
            if (c.currency or "EUR") != "EUR":
                raise SepaExportInvalid(
                    f"Charge {c.pk}: currency {c.currency} is not EUR; "
                    "SEPA pain.008 is EUR-only.",
                    details={"charge": str(c.pk), "currency": c.currency},
                )

            # FRST only for a mandate's very first-ever collection; RCUR
            # otherwise. ``sepa_mandate_first_use_at`` (stamped by
            # ``export()`` AFTER the file is built) covers PRIOR runs. But
            # within THIS file a never-used mandate can carry several charges
            # — only the first may be FRST, the rest must be RCUR, else the
            # bank rejects the batch for a duplicate FRST sequence.
            if billing_profile.sepa_mandate_first_use_at is not None:
                sequence_type = "RCUR"
            elif billing_profile.pk in frst_assigned:
                sequence_type = "RCUR"
            else:
                sequence_type = "FRST"
                frst_assigned.add(billing_profile.pk)

            sepa.add_payment(
                {
                    "name": debtor_name[:70],  # ISO 20022 ``Nm`` max length
                    "IBAN": debtor_iban,
                    # ``amount`` is in CENTS (integer) per sepaxml's API.
                    "amount": int(
                        (c.expected_amount * 100).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    ),
                    "type": sequence_type,
                    # RequestedCollectionDate is the operator-set run
                    # collection_date (when the bank debits), NOT each charge's
                    # due_date. Using per-charge due_dates ignored the field's
                    # documented purpose and (with batch=True) fragmented the
                    # file into one PmtInf per distinct due_date.
                    "collection_date": run.collection_date,
                    "mandate_id": mandate_ref,
                    "mandate_date": mandate_signed,
                    # ISO 20022 ``Ustrd`` (≤140 chars) — the operator's
                    # remittance template, falling back to the internal charge
                    # description only if the rendered text comes out empty.
                    "description": _render_remittance(
                        remittance_template,
                        creditor=creditor_name,
                        member=debtor_name,
                        period_start=c.period_start,
                        period_end=c.period_end,
                        amount=c.expected_amount,
                    )
                    or (c.description or f"Subscription {c.subscription_id}")[:140],
                    "endtoend_id": str(c.end_to_end_id or c.pk)[:35],
                }
            )

        # ``validate=True`` runs the bundled XSD against the generated
        # document and raises if anything is off — a malformed file never
        # reaches the office's download button. Translate sepaxml's opaque
        # ValidationError into our SepaExportInvalid (a clean 4xx) carrying the
        # failing element(s), so the office sees WHICH field is illegal (a
        # creditor BIC / creditor-id, an out-of-charset debtor name, a past
        # collection date, …) instead of an unhelpful 500.
        try:
            return sepa.export(validate=True)
        except SepaXmlValidationError as exc:
            # sepaxml validates via the ``xmlschema`` library; its
            # XMLSchemaValidationError carries the failing element ``path`` +
            # ``reason`` (NOT an lxml ``error_log``). Surface the offending field
            # (e.g. "BIC: value doesn't match pattern …") so the office can fix
            # the exact tenant/debtor field instead of guessing.
            cause = exc.__cause__ or exc.__context__
            reason = getattr(cause, "reason", None)
            path = getattr(cause, "path", None)
            field = path.rstrip("/").split("/")[-1].split("[")[0] if path else None
            if field and reason:
                detail = f"{field}: {reason}"
            elif cause is not None:
                detail = str(cause).strip().splitlines()[0]
            else:
                detail = str(exc)
            raise SepaExportInvalid(
                "The generated SEPA file failed validation. Check the creditor "
                "fields (name / IBAN / BIC / creditor-id) and the debtor data. "
                f"Details: {detail}",
                details={"validation_errors": detail},
            ) from exc
