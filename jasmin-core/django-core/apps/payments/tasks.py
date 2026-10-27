"""Periodic payments tasks."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from apps.shared.tenants.sweep import for_each_tenant

from .constants import (
    DIRECT_DEBIT_SETTLES_AFTER,
    BillingRunStatus,
    ChargeStatus,
    PaymentMethodOptions,
)
from .errors import BillingRunChargesBeingReplanned
from .models import BillingRun
from .services import BillingRunService

ops_log = logging.getLogger("tasks")


@db_periodic_task(crontab(hour="5", minute="30"), retries=2, retry_delay=600)
def settle_collected_direct_debits() -> dict[str, int]:
    """Settle every exported direct-debit run a member can no longer have
    refunded, per tenant: its issued charges become PAID, the run SETTLED.

    Nothing feeds the bank's answer back, so an issued charge would otherwise
    stay owed for good, and an owed charge blocks the member's erasure. A debit
    counts as collected once ``DIRECT_DEBIT_SETTLES_AFTER`` has passed since the
    run's collection date. Bank-transfer runs are left alone: nothing tells
    whether the member paid.
    """
    cutoff = timezone.localdate() - DIRECT_DEBIT_SETTLES_AFTER
    counters = {"runs_settled": 0, "charges_paid": 0}

    def settle(tenant):
        run_ids = list(
            BillingRun.objects.filter(
                status=BillingRunStatus.EXPORTED,
                payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                collection_date__lte=cutoff,
            ).values_list("pk", flat=True)
        )
        runs_settled = charges_paid = 0
        for run_id in run_ids:
            try:
                paid = _settle_run(run_id)
            except BillingRunChargesBeingReplanned:
                # The next day's sweep tries this run again.
                continue
            if paid is not None:
                runs_settled += 1
                charges_paid += paid
        if runs_settled:
            ops_log.info(
                "payments.direct_debits_settled tenant=%s runs=%s charges=%s",
                tenant.schema_name,
                runs_settled,
                charges_paid,
            )
        counters["runs_settled"] += runs_settled
        counters["charges_paid"] += charges_paid

    counters["tenants_failed"] = for_each_tenant(
        settle, label="payments.direct_debits_settled"
    )
    return counters


@transaction.atomic
def _settle_run(run_id: str) -> int | None:
    """Settle the run under its row lock and return how many charges it marked
    paid, or ``None`` when the run was settled in the meantime.

    Raises :class:`BillingRunChargesBeingReplanned` when a re-plan holds one of
    the run's charges, leaving the run as it was.
    """
    run = BillingRun.objects.select_for_update().get(pk=run_id)
    if run.status != BillingRunStatus.EXPORTED:
        return None
    paid = 0
    for charge in BillingRunService.lock_charges(run):
        if charge.status != ChargeStatus.ISSUED:
            continue
        charge.status = ChargeStatus.PAID
        # ``update_fields`` writes the flip alone: a plain save() whose UPDATE
        # matched no row would INSERT the charge back.
        charge.save(allow_immutable_change=True, update_fields=["status"])
        paid += 1
    run.status = BillingRunStatus.SETTLED
    run.save(update_fields=["status"])
    return paid
