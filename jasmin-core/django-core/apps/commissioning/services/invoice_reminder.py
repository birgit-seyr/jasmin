"""Bulk invoice-reminder send, extracted from
``apps/commissioning/views/reseller_views.py::BulkSendInvoiceReminders
ViaEmailView.post`` so the Huey task can call it without going through
the HTTP layer.

Same grouped-by-reseller shape that view ships today (one consolidated
reminder email per reseller, not one per ticked invoice).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from django.db import DatabaseError
from django.utils import timezone
from django.utils.html import escape as _html_escape
from django.utils.safestring import SafeString, mark_safe

from apps.shared.tenants.email_service import (
    EmailService,
    capture_tenant_email_context,
)

from .bulk_email_job import create_send_record_idempotent, emit_progress

logger = logging.getLogger(__name__)

_REMINDER_TD = '<td style="padding: 8px; border: 1px solid #ddd;">'


def _build_invoices_table(invoices: list[dict[str, Any]], language: str) -> SafeString:
    """EML-1: pre-render the overdue-invoice rows as TRUSTED HTML (every cell
    HTML-escaped here in Python) so the template needs no Django ``{% for %}``
    loop — which the safe Mustache renderer used for tenant overrides cannot
    reproduce, silently dropping every row. The rows drop into the template's
    ``<tbody>``; the ``<thead>`` stays in the (tenant-editable) template.
    mark_safe so Django emits it raw; ``invoices_table`` is in the renderer's
    RAW_KEYS so the Mustache override path emits it raw too."""
    unit = "Tage" if language == "de" else "days"
    rows = []
    for inv in invoices:
        rows.append(
            "<tr>"
            f"{_REMINDER_TD}<strong>{_html_escape(str(inv['number']))}</strong></td>"
            f"{_REMINDER_TD}{_html_escape(str(inv['total']))}</td>"
            f"{_REMINDER_TD}{_html_escape(str(inv['issue_date']))}</td>"
            f"{_REMINDER_TD}{_html_escape(str(inv['due_date']))}</td>"
            f"{_REMINDER_TD}{_html_escape(str(inv['days_overdue']))} {unit}</td>"
            "</tr>"
        )
    return mark_safe("".join(rows))


def _build_invoices_text(invoices: list[dict[str, Any]], language: str) -> str:
    """Plain-text counterpart of :func:`_build_invoices_table` for the .txt body."""
    lines = []
    for inv in invoices:
        if language == "de":
            lines.append(
                f"- {inv['number']} ({inv['total']}), ausgestellt am "
                f"{inv['issue_date']}, fällig am {inv['due_date']} "
                f"({inv['days_overdue']} Tage überfällig)"
            )
        else:
            lines.append(
                f"- {inv['number']} ({inv['total']}), issued on "
                f"{inv['issue_date']}, due on {inv['due_date']} "
                f"({inv['days_overdue']} days overdue)"
            )
    return "\n".join(lines)


def _invoice_to_dict(invoice) -> dict[str, Any]:
    """Flatten an ``InvoiceReseller`` into the template/registry shape the
    ``commissioning.invoice_reminder`` template expects: ``number``,
    ``total``, ``issue_date``, ``due_date``, ``days_overdue``."""
    issue_date = getattr(invoice, "date", None)
    due_date = getattr(invoice, "due_date", None)
    today = timezone.localdate()
    days_overdue = (today - due_date).days if due_date and today > due_date else 0
    try:
        total = f"{invoice.sum_brutto:.2f}"
    except (AttributeError, TypeError):
        total = ""
    return {
        "number": invoice.full_number,
        "total": total,
        "issue_date": issue_date.isoformat() if issue_date else "",
        "due_date": due_date.isoformat() if due_date else "",
        "days_overdue": days_overdue,
    }


def bulk_send_invoice_reminders(
    *,
    order_ids: list[str],
    email_ctx: dict | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    """Send a consolidated reminder per reseller covering all of their
    ticked overdue invoices.

    Returns the same response shape ``BulkSendInvoiceRemindersView``
    used to construct inline: ``{total_processed, successful, failed,
    results, errors}`` — so the React drawer's success handler maps
    over with no per-task knowledge.

    ``progress_cb``: optional, receives ``{processed, successful,
    failed, total}`` after each reseller bucket is dispatched.
    """
    from apps.commissioning.models import Order
    from apps.commissioning.services import InvoiceService
    from apps.commissioning.services.bulk_results import (
        format_order_error,
        get_delivery_note_or_error,
    )

    orders = Order.objects.filter(id__in=order_ids).select_related(
        "delivery_note", "reseller", "reseller__contact"
    )

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not orders.exists():
        return {
            "total_processed": len(order_ids),
            "successful": 0,
            "failed": 0,
            "results": results,
            "errors": [
                {
                    "order_id": order_id,
                    "error": "Order not found",
                    "success": False,
                }
                for order_id in order_ids
            ],
        }

    by_reseller: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"reseller": None, "invoices": []}
    )

    # Resolve every delivery note's invoice in one batch up front, rather than
    # a per-order get_invoice_for_delivery_note() (1-2 queries each).
    # ``delivery_note`` is the reverse OneToOne (no ``_id`` attr) — access it
    # the same safe way get_delivery_note_or_error does (select_related-cached).
    invoice_by_delivery_note = InvoiceService.get_invoices_for_delivery_notes(
        [
            delivery_note.id
            for order in orders
            if (delivery_note := getattr(order, "delivery_note", None)) is not None
        ]
    )

    for order in orders:
        try:
            delivery_note, err = get_delivery_note_or_error(order)
            if err:
                errors.append(err)
                continue
            invoice = invoice_by_delivery_note.get(delivery_note.id)
            if not invoice:
                errors.append(
                    format_order_error(order, "No invoice found for this delivery note")
                )
                continue
            if not invoice.is_finalized:
                errors.append(format_order_error(order, "Invoice is not finalized"))
                continue
            if invoice.cancelled_by_invoice_id:
                # No reminders for a cancelled (storno'd) invoice — it is no
                # longer an outstanding payable.
                errors.append(format_order_error(order, "Invoice has been cancelled"))
                continue
            if invoice.has_been_paid:
                # A paid invoice is no longer an outstanding payable — never dun
                # it. Defense-in-depth: the UI also disables the send button for
                # paid rows, but a TOCTOU race or direct API call could slip one
                # through.
                errors.append(
                    format_order_error(order, "Invoice has already been paid")
                )
                continue
            reseller = order.reseller
            if not reseller or not reseller.invoice_email:
                errors.append(
                    format_order_error(order, "No email address found for reseller")
                )
                continue
            bucket = by_reseller[str(reseller.id)]
            bucket["reseller"] = reseller
            bucket["invoices"].append((order, invoice))
        except (DatabaseError, ValueError, TypeError, AttributeError) as exc:
            errors.append(format_order_error(order, str(exc)))

    # Tenant name / language / bank details — passed from the enqueueing
    # view (real Tenant); fall back to the live tenant for synchronous
    # callers. The worker's FakeTenant can't supply these.
    ctx = email_ctx or capture_tenant_email_context()

    total_buckets = len(by_reseller)
    processed = 0
    # Bucket-level counters so the progress snapshot is internally consistent:
    # ``processed`` / ``successful_buckets`` / ``failed_buckets`` all count
    # RESELLER buckets (one email per bucket). Deriving ``failed`` from a
    # per-invoice success count gave nonsense (successful > total, negative
    # failed) for a reseller with more than one invoice.
    successful_buckets = 0
    failed_buckets = 0

    def _emit_progress() -> None:
        emit_progress(
            progress_cb,
            processed=processed,
            successful=successful_buckets,
            failed=failed_buckets,
            total=total_buckets,
        )

    # EML-3: idempotency. Resellers already reminded TODAY (e.g. a retry after a
    # 'failed' job, or a re-click) are skipped below so they aren't dunned twice.
    # The set is the clean pre-check; the (reseller, sent_on) DB unique catches
    # races / concurrent runs.
    from apps.commissioning.models import ReminderSending

    today = timezone.localdate()
    already_reminded_today: set[str] = set(
        ReminderSending.objects.filter(sent_on=today).values_list(
            "reseller_id", flat=True
        )
    )

    # One EmailService for the whole run — its __init__ queries TenantEmailConfig
    # once, so building it per reseller bucket repeated that query N times.
    email_service = EmailService()

    for bucket in by_reseller.values():
        reseller = bucket["reseller"]
        invoices_with_orders = bucket["invoices"]

        # Skip a reseller already reminded today — record as success (they WERE
        # reminded, just not now) so a re-run shows them handled, not failed.
        if reseller.id in already_reminded_today:
            successful_buckets += 1
            for order, invoice in invoices_with_orders:
                results.append(
                    {
                        "order_id": str(order.id),
                        "invoice_number": invoice.full_number,
                        "success": True,
                        "skipped": "already_reminded_today",
                    }
                )
            processed += 1
            _emit_progress()
            continue

        reseller_name = (
            reseller.contact.name
            if getattr(reseller, "contact", None)
            else (reseller.invoice_name or "")
        )
        invoice_dicts = [_invoice_to_dict(inv) for _o, inv in invoices_with_orders]
        reminder_language = ctx["tenant_language"] or "en"
        try:
            success = email_service.send_email(
                slug="commissioning.invoice_reminder",
                to_emails=[reseller.invoice_email],
                context={
                    "tenant_name": ctx["tenant_name"],
                    "reseller": {"name": reseller_name},
                    # EML-1: pre-flattened so the template is substitution-only
                    # (no {% for %}) and renders identically under a tenant
                    # override (safe Mustache renderer).
                    "invoices_table": _build_invoices_table(
                        invoice_dicts, reminder_language
                    ),
                    "invoices_text": _build_invoices_text(
                        invoice_dicts, reminder_language
                    ),
                    "tenant": {"bank_details": ctx["bank_details"]},
                },
                language=ctx["tenant_language"] or None,
                related_object_type="reseller",
                related_object_id=str(getattr(reseller, "id", "") or ""),
            )
        except (DatabaseError, ValueError, TypeError, AttributeError) as exc:
            for order, _inv in invoices_with_orders:
                errors.append(format_order_error(order, str(exc)))
            failed_buckets += 1
            processed += 1
            _emit_progress()
            continue

        if success:
            successful_buckets += 1

            # Record the send so a retry/re-click today skips this reseller.
            # Guarded against a concurrent run racing on the same (reseller, day).
            def _create_reminder_record(reseller=reseller):
                ReminderSending.objects.create(reseller=reseller, sent_on=today)
                already_reminded_today.add(reseller.id)

            def _on_reminder_race(reseller=reseller):
                logger.warning(
                    "remindersending.race reseller=%s — concurrent reminder send, "
                    "dedup row already exists",
                    reseller.id,
                )

            create_send_record_idempotent(
                _create_reminder_record, on_race=_on_reminder_race
            )
            for order, invoice in invoices_with_orders:
                results.append(
                    {
                        "order_id": str(order.id),
                        "invoice_number": (invoice.full_number),
                        "success": True,
                    }
                )
        else:
            failed_buckets += 1
            for order, _inv in invoices_with_orders:
                errors.append(
                    format_order_error(order, "Failed to send reminder email")
                )
        processed += 1
        _emit_progress()

    return {
        "total_processed": len(order_ids),
        "successful": sum(1 for r in results if r["success"]),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
