# Billing dates: charge **due date** vs. SEPA-run **collection date**

There are two distinct dates in the billing pipeline that are easy to conflate.
They answer different questions:

- **`billing_due_day_of_month`** → *when is each charge **due**?* (per-charge, set at
  plan time) — drives which billing-run period a charge is eligible for.
- A billing run's **`collection_date`** → *when does the bank actually **debit**?*
  (per-run, set at create time) — written into the SEPA pain.008 file.

They are independent. The collection date you enter when starting a SEPA run is
**not** derived from `billing_due_day_of_month`.

---

## `billing_due_day_of_month` — the per-charge due date

A `TenantSettings` field (default `1`, validated 1–28), editable in tenant
settings: `apps/shared/tenants/models.py` (`billing_due_day_of_month`), exposed
via the tenant-settings viewset.

The chain:

1. `_BillingConfig.for_tenant()` reads it into `due_day`
   — `apps/payments/services.py`.
2. When charges are **planned** (`ChargeScheduleService.regenerate_for_subscription`),
   each `ChargeSchedule.due_date` is stamped via
   `_due_date_for(period.start, period.end, billing.due_day)` — the configured
   day-of-month, **clamped into the billing period** (so a charge is never due
   before its period starts, and sub-monthly cycles get a distinct in-window due
   date per period instead of collapsing onto one monthly day).
3. That `due_date` is the **eligibility key** for a billing run:
   `create_run` bundles `PLANNED` charges whose `due_date` falls in the run's
   `[period_start, period_end]` window (`apps/payments/services.py`, the
   `eligible` queryset filtered on `due_date__gte/__lte`).

So `billing_due_day_of_month` decides each charge's due date, which decides
**which run period sweeps it up**. It is not dead config.

## A run's `collection_date` — the bank debit date

A per-run value passed to `create_run`, frozen there, and written into the
pain.008 SEPA file as the actual debit date (when the bank pulls the money).
Validated separately (must not be in the past; soft-warns if before
`period_end`). There is also a sibling tenant setting
`sepa_collection_day_of_month` (default `5`) — the collection-day default,
distinct from the due day.

---

## Summary

|                | `billing_due_day_of_month`                                   | run's `collection_date`                       |
| -------------- | ------------------------------------------------------------ | --------------------------------------------- |
| **Is**         | per-charge **due date** (day-of-month, clamped into period)  | the **bank debit date** for one SEPA run      |
| **Used for**   | which run period a charge is eligible for (`due_date` filter) | the actual debit in the pain.008 file         |
| **Scope**      | every `ChargeSchedule`, at plan time                          | one billing run, at create time               |
| **Set in**     | tenant settings                                               | entered when starting the run                 |

Not redundant: they answer *"which charges belong in this run"* vs. *"when does
the bank actually take the money."*
