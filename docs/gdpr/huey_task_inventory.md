# Huey audit — 2026-07-01



## Task inventory

### Periodic (`@db_periodic_task`, cron)

| When (server TZ, UTC) | Task | Purpose |
|---|---|---|
| every 15 min | `accounts.alert_on_axes_bursts` | brute-force fingerprints from django-axes |
| every 15 min | `gdpr.alert_on_mass_deletes` | mass-deletion bursts on PII / legally-relevant tables |
| every 15 min | `gdpr.alert_on_deletion_endpoint_bursts` | abuse of public GDPR deletion endpoints |
| 02:15 | `notifications.cleanup_stale_email_logs` | prune per-tenant `EmailLog` |
| 02:30 | `accounts.clear_expired_sessions` | drop expired `django_session` rows |
| Sun 02:30 | `commissioning.cleanup_expired_capacity_reservations` | prune lapsed `CapacityReservation` |
| Sun 02:45 | `commissioning.cleanup_stale_import_batches` | prune abandoned `ShareImportBatch` |
| 02:45 | `authz.flush_expired_jwt_tokens` | drop expired refresh tokens per tenant |
| 03:00 | `commissioning.nightly_invoice_hash_check` | tamper-detection on finalized invoices |
| 03:00 | `gdpr.anonymise_long_cancelled_members` | anonymise ex-members past the 10-year retention window |
| 04:00 | `commissioning.daily_subscription_renewals` | create draft auto-renewals for subscriptions past their cancellation window |
| 05:00 | `tenants.prune_old_backups` | GFS retention on the pg_dump backups on disk |
| Mon 07:00 | `tenants.weekly_tenant_health_report` | weekly per-tenant row-count summary |
| Mon 09:00 | `super_admin.email_overdue_ops_items` | weekly digest of overdue ops-checklist items |

### On-demand (`@db_task`, enqueued from request code)

| Task | Retries | Trigger / purpose |
|---|---|---|
| `commissioning.recompute_shares_async` | 2 (30s delay) | the **deferred forecast recompute** — the only async recompute path; enqueued via `transaction.on_commit` from `ForecastService`. Rebuilds theoreticals + SHARECONTENT movements. |
| `commissioning.run_bulk_offer_send` | 0 | bulk-email offers to resellers; progress-tracked via `BackgroundJob` |
| `commissioning.run_bulk_invoice_reminder_send` | 0 | bulk-email invoice reminders; progress-tracked via `BackgroundJob` |

**Bulk-job infra:** the two bulk sends use `BackgroundJob` + `enqueue_job` /
`report_progress` / `mark_done` (`apps/notifications/jobs.py`) for status/progress
tracking. CLAUDE.md flags this `notifications.jobs` + `BackgroundJob` infra as a
known commissioning-extraction blocker (to relocate into `apps/shared/`).

