import datetime
import logging

from django.conf import settings
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

from apps.commissioning.services import InvoiceService
from apps.shared.tenants.sweep import for_each_tenant

log = logging.getLogger("django.security")
ops_log = logging.getLogger("tasks")

# Stale-import-batch retention window.
IMPORT_BATCH_RETENTION_DAYS = 90


@db_periodic_task(crontab(hour="3", minute="0"), retries=2, retry_delay=300)
def nightly_invoice_hash_check():
    """Nightly tamper-detection sweep for finalized invoices.

    For each tenant schema, recomputes the document_hash on every
    finalized invoice and warns on any drift. Warnings land in
    ``logs/security.log`` and are grepped by ``grep invoice.hash_drift``

    """

    def check(tenant):
        for inv in InvoiceService.find_drifted_invoices():
            log.warning(
                "invoice.hash_drift tenant=%s invoice_id=%s prefix=%s number=%s",
                tenant.schema_name,
                inv["id"],
                inv["prefix"],
                inv["number"],
            )

    # Per-tenant isolation: one bad tenant must NOT abort the sweep. Failures
    # are logged (to the security log) and skipped.
    # ``include_inactive=True``: a frozen (is_active=False) tenant is exactly
    # when tamper detection matters most (offboarding dispute, non-payment,
    # suspected breach). Deactivation is soft (schema kept), the request path is
    # already blocked by TenantActiveMiddleware, and this scan is read-only — so
    # keep watching finalized-invoice hash drift on frozen schemas too.
    for_each_tenant(
        check, label="invoice.hash_check", logger=log, include_inactive=True
    )


@db_periodic_task(
    crontab(hour="2", minute="45", day_of_week="0"), retries=2, retry_delay=300
)
def cleanup_stale_import_batches() -> None:
    """Prune abandoned ShareShareImportBatch rows.

    Upload + preview cycles leave behind rows in ``FAILED`` or
    ``PREVIEW_READY`` status. Delete those older than
    ``IMPORT_BATCH_RETENTION_DAYS``. Rows in status ``APPLIED`` are
    NEVER deleted — those are the audit trail of what membership
    changes actually happened and when.

    Per-tenant: ``ShareShareImportBatch`` lives in the tenant schema.
    """
    # Lazy import: model lives in a TENANT_APP.
    from apps.commissioning.models.imports import ShareImportBatch

    cutoff = timezone.now() - datetime.timedelta(days=IMPORT_BATCH_RETENTION_DAYS)
    deletable_statuses = (
        ShareImportBatch.STATUS_FAILED,
        ShareImportBatch.STATUS_PREVIEW_READY,
    )
    counters = {"deleted": 0}

    def prune(tenant):
        deleted, _ = ShareImportBatch.objects.filter(
            created_at__lt=cutoff,
            status__in=deletable_statuses,
        ).delete()
        counters["deleted"] += deleted
        if deleted:
            ops_log.info(
                "housekeeping.import_batch_pruned tenant=%s deleted=%s",
                tenant.schema_name,
                deleted,
            )

    for_each_tenant(prune, label="housekeeping.import_batch_pruned")

    ops_log.info(
        "housekeeping.import_batch_pruned total_deleted=%s retention_days=%s",
        counters["deleted"],
        IMPORT_BATCH_RETENTION_DAYS,
    )


@db_periodic_task(
    crontab(hour="2", minute="30", day_of_week="0"), retries=2, retry_delay=300
)
def cleanup_expired_capacity_reservations() -> None:
    """Prune lapsed ``CapacityReservation`` rows.

    Pure housekeeping: correctness does NOT depend on this — occupancy already
    ignores reservations whose ``expires_at <= now`` (they stop holding the
    slot the instant they expire). This just keeps the table from growing
    unbounded with dead holds from abandoned/never-confirmed drafts.

    Per-tenant: reservations live in each tenant schema.
    """
    from apps.commissioning.models import CapacityReservation

    cutoff = timezone.now()
    counters = {"deleted": 0}

    def prune(tenant):
        deleted, _ = CapacityReservation.objects.filter(expires_at__lt=cutoff).delete()
        counters["deleted"] += deleted
        if deleted:
            ops_log.info(
                "housekeeping.capacity_reservations_pruned tenant=%s deleted=%s",
                tenant.schema_name,
                deleted,
            )

    for_each_tenant(prune, label="housekeeping.capacity_reservations_pruned")

    ops_log.info(
        "housekeeping.capacity_reservations_pruned total_deleted=%s",
        counters["deleted"],
    )


# Office-facing text for each renewal FAIL_* reason code. The frontend
# localizes the same codes for the bulk-renew modal; the daily digest email is
# server-rendered, so it carries its own copy (de + en).
_RENEWAL_FAIL_REASON_TEXT = {
    "de": {
        "no_variation": "Keine passende Anteils-Variante deckt die neue Laufzeit ab.",
        "dsd_coverage": "Der Verteilstationstag reicht nicht in die neue Laufzeit.",
        "invalid": "Der Verlängerungs-Entwurf konnte nicht erstellt werden.",
    },
    "en": {
        "no_variation": "No matching share variation covers the new term.",
        "dsd_coverage": "The delivery station-day does not reach into the new term.",
        "invalid": "The renewal draft could not be created.",
    },
}


def _renewal_reason_text(reason: str, language: str) -> str:
    table = _RENEWAL_FAIL_REASON_TEXT.get(language, _RENEWAL_FAIL_REASON_TEXT["en"])
    return table.get(reason, table["invalid"])


def _renewal_member_label(item: dict, language: str) -> str:
    """ "Name (Mitglied #NN)" / "Name (member #NN)"; number omitted if absent."""
    who_word = "Mitglied" if language == "de" else "member"
    name = item.get("member_name") or who_word
    number = item.get("member_number")
    return f"{name} ({who_word} #{number})" if number else name


def _build_renewal_failures_html(failed: list[dict], language: str):
    """Pre-flattened, per-cell-escaped ``<li>`` rows for the digest email — same
    trusted-HTML pattern as the invoice-reminder table (``renewal_failures_html``
    is a renderer RAW_KEY, so no Django ``{% for %}`` loop is needed)."""
    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    abo_word = "Abo" if language == "de" else "subscription"
    rows = [
        f"<li><strong>{escape(_renewal_member_label(item, language))}</strong> — "
        f"{abo_word} {escape(str(item.get('label') or ''))}: "
        f"{escape(_renewal_reason_text(item.get('reason', 'invalid'), language))}</li>"
        for item in failed
    ]
    return mark_safe("".join(rows))


def _build_renewal_failures_text(failed: list[dict], language: str):
    from django.utils.safestring import mark_safe

    abo_word = "Abo" if language == "de" else "subscription"
    lines = [
        f"- {_renewal_member_label(item, language)} — {abo_word} "
        f"{item.get('label') or ''}: "
        f"{_renewal_reason_text(item.get('reason', 'invalid'), language)}"
        for item in failed
    ]
    return mark_safe("\n".join(lines))


def _office_review_url(tenant, path: str) -> str:
    """Absolute frontend URL for the tenant, built from its primary domain (the
    sweep runs with no request, so ``connection.tenant`` isn't reliably set)."""
    domain = tenant.domains.filter(is_primary=True).first() or tenant.domains.first()
    if domain:
        scheme = "http" if settings.DEBUG else "https"
        return f"{scheme}://{domain.domain}{path}"
    return f"{getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:3000')}{path}"


def _notify_office_of_renewal_failures(tenant, failed: list[dict], run_date) -> None:
    """Best-effort office digest of the subscriptions the daily sweep could NOT
    renew (so the at-risk members aren't buried in a log counter). Goes to the
    tenant office mailbox (``Tenant.email``); a missing address or a failed send
    is logged and swallowed — it must never abort the sweep. Mirrors
    ``_notify_office_of_self_cancel``."""
    office_email = getattr(tenant, "email", None)
    if not office_email:
        ops_log.info(
            "renewal.digest_skipped tenant=%s reason=no_office_email failed=%d",
            tenant.schema_name,
            len(failed),
        )
        return

    raw_lang = (getattr(tenant, "tenant_language", "") or "").strip().lower()[:2]
    language = "de" if raw_lang == "de" else "en"

    from apps.shared.deferred_email import send_email_best_effort

    context = {
        "tenant_name": tenant.name,
        "failure_count": str(len(failed)),
        "run_date": run_date.strftime("%d.%m.%Y"),
        "renewal_failures_html": _build_renewal_failures_html(failed, language),
        "renewal_failures_text": _build_renewal_failures_text(failed, language),
        "review_url": _office_review_url(tenant, "/abos/abos"),
    }
    # Runs inside the sweep's ``schema_context(tenant.schema_name)``, so the
    # helper's default ``EmailService()`` resolves the same schema the explicit
    # ``EmailService(tenant.schema_name)`` used to. Best-effort: a crashed or
    # unsent digest logs ``renewal.digest_failed`` on the ops log and is
    # swallowed so the sweep never aborts.
    send_email_best_effort(
        slug="commissioning.subscription_renewal_failures_office",
        to_emails=[office_email],
        context=context,
        language=language,
        priority="normal",
        logger=ops_log,
        log_error_event="renewal.digest_failed",
        log_not_sent_event="renewal.digest_failed",
        log_ref=f"tenant={tenant.schema_name}",
    )


@db_periodic_task(crontab(hour="4", minute="0"), retries=1, retry_delay=300)
def daily_subscription_renewals() -> None:
    """Create draft auto-renewals for subscriptions past their cancellation
    deadline, per tenant.

    Only runs for tenants with ``subscriptions_are_auto_renewed`` enabled. Each
    renewal is an UNCONFIRMED draft — the office reviews and confirms it, and
    the confirm flow then materialises Shares / ShareDeliveries / charges.
    Per-subscription failures (no covering variation, station-day out of range)
    are captured with a reason code, logged per row (member + reason), and — so
    the at-risk members aren't invisible — emailed to the office as a digest of
    who could NOT be renewed and why. One bad row never aborts the run.
    """

    def run(tenant):
        from apps.shared.tenants.models import TenantSettings

        tenant_settings = TenantSettings.get_current_settings(tenant)
        if not tenant_settings or not tenant_settings.subscriptions_are_auto_renewed:
            return

        from apps.commissioning.services.renewal import run_renewals

        run_date = timezone.localdate()
        result = run_renewals(
            run_date, tenant_settings.min_weeks_to_cancel_before_ending
        )
        failed = result["failed"]
        if result["created"] or failed:
            ops_log.info(
                "renewal.run tenant=%s created=%s failed=%s",
                tenant.schema_name,
                result["created"],
                len(failed),
            )
        if failed:
            _notify_office_of_renewal_failures(tenant, failed, run_date)

    for_each_tenant(run, label="subscription.renewals")


# ---------------------------------------------------------------------------
# Ad-hoc per-request work (BackgroundJob-backed)
# ---------------------------------------------------------------------------
# These are the user-triggered "I clicked a button, do the work in the
# background" tasks — distinct from the periodic sweeps above. Each one
# follows the same shape:
#
#   * accepts ``schema_name`` + ``job_id`` as the first two arguments
#     (passed in by ``apps.notifications.jobs.enqueue_job``);
#   * enters ``schema_context(schema_name)`` immediately;
#   * flips the job to ``running``, does the work, writes
#     ``progress`` snapshots in flight, flips to ``done`` / ``failed``
#     at the end;
#   * NEVER lets an exception escape Huey — the worker would retry
#     and that's almost never what you want for an SMTP blast.
#
# The catch-all ``except Exception`` is intentional and narrow in
# meaning: any error is captured, persisted to the job row, and
# surfaced to the office user via the polling drawer. The full
# traceback still lands in the worker logs.


@db_task(retries=0)
def run_bulk_offer_send(
    *,
    schema_name: str,
    job_id: str,
    reseller_ids: list[str],
    year: int,
    delivery_week: int,
    offer_group_id: str,
    email_ctx: dict | None = None,
) -> None:
    """Bulk-send weekly offers to resellers, on the Huey worker.

    ``email_ctx`` carries the tenant name / language / frontend URL captured
    at enqueue time (the worker's FakeTenant can't supply them).
    """
    from apps.commissioning.models import OfferGroup
    from apps.commissioning.services.offer_service import OfferService
    from apps.notifications.jobs import run_job

    with run_job(schema_name, job_id) as job:
        offer_group = OfferGroup.objects.get(pk=offer_group_id)
        job.result = OfferService.bulk_send_offers_via_email(
            reseller_ids=reseller_ids,
            year=year,
            delivery_week=delivery_week,
            offer_group=offer_group,
            email_ctx=email_ctx,
            progress_cb=job.progress,
        )


@db_task(retries=0)
def run_bulk_invoice_reminder_send(
    *,
    schema_name: str,
    job_id: str,
    order_ids: list[str],
    email_ctx: dict | None = None,
) -> None:
    """Bulk-send invoice reminder emails grouped by reseller.

    ``email_ctx`` carries the tenant name / language / bank details captured
    at enqueue time (the worker's FakeTenant can't supply them).
    """
    from apps.commissioning.services.invoice_reminder import (
        bulk_send_invoice_reminders,
    )
    from apps.notifications.jobs import run_job

    with run_job(schema_name, job_id) as job:
        job.result = bulk_send_invoice_reminders(
            order_ids=order_ids,
            email_ctx=email_ctx,
            progress_cb=job.progress,
        )


@db_periodic_task(crontab(minute="*/30"), retries=1, retry_delay=120)
def expire_stale_waiting_list_offers() -> None:
    """Expire spot-available waiting-list offers whose response window lapsed,
    freeing the held station-day + variation capacity for the next in line.

    Runs every 30 min so a freed slot isn't held long after a member goes
    quiet. Occupancy already ignores a lapsed offer (the
    ``notification_expires_at`` time check), so this is cleanup of the status +
    the station-day reservation rows, not a correctness gate.
    """
    from apps.commissioning.services.waiting_list_offer_service import (
        WaitingListOfferService,
    )

    def sweep(tenant):
        count = WaitingListOfferService.expire_stale_offers()
        if count:
            ops_log.info(
                "waiting_list.offers_expired tenant=%s count=%s",
                tenant.schema_name,
                count,
            )

    for_each_tenant(sweep, label="waiting_list.expire_offers", logger=ops_log)
