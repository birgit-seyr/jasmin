"""Shared skeleton for the commissioning bulk-email jobs.

``OfferService.bulk_send_offers_via_email`` and
``bulk_send_invoice_reminders`` both drive a background bulk-email job that
polls a ``JobProgressDrawer`` in the React frontend. The two loops are
structurally divergent — offers count one result row per reseller while
reminders bucket several invoices per reseller, and the two returned
summary dicts differ (offers derives ``failed`` from ``results``; reminders
reports ``failed = len(errors)`` and carries an extra ``errors`` list). Those
divergent parts stay in each caller. What is byte-identical between them —
and therefore lives here — is:

1. the progress snapshot payload shape ``{processed, successful, failed,
   total}`` emitted through the optional ``progress_cb`` after each unit of
   work, and
2. the per-recipient idempotency race guard: a ``transaction.atomic()``
   wrapping the sending-record ``create()`` with an ``IntegrityError``
   fallback for the window between the in-memory "already sent" pre-check
   and the INSERT (a concurrent bulk-send racing on the same composite key).
"""

from __future__ import annotations

from collections.abc import Callable

from django.db import IntegrityError, transaction


def emit_progress(
    progress_cb: Callable[[dict], None] | None,
    *,
    processed: int,
    successful: int,
    failed: int,
    total: int,
) -> None:
    """Emit one progress snapshot through ``progress_cb`` if it is set.

    The payload shape ``{processed, successful, failed, total}`` is
    load-bearing: the React ``JobProgressDrawer`` reads exactly these keys.
    Synchronous callers (tests, legacy paths) pass ``progress_cb=None`` and
    this is a no-op, keeping the services identical to their pre-queue shape.
    """
    if progress_cb is None:
        return
    progress_cb(
        {
            "processed": processed,
            "successful": successful,
            "failed": failed,
            "total": total,
        }
    )


def create_send_record_idempotent(
    create_callback: Callable[[], None],
    *,
    on_race: Callable[[], None],
) -> None:
    """Run ``create_callback`` inside ``transaction.atomic()`` and swallow a
    racing ``IntegrityError`` by invoking ``on_race``.

    The recipient already got the email by the time this is called, so a
    composite-key clash means a concurrent bulk-send raced through the
    in-memory pre-check and inserted the dedup row first — treat it as
    success. ``create_callback`` performs the ``Model.objects.create(...)``;
    ``on_race`` performs the caller-specific logging / bookkeeping for the
    clash. The atomic savepoint keeps the ``IntegrityError`` from poisoning
    the surrounding transaction.
    """
    try:
        with transaction.atomic():
            create_callback()
    except IntegrityError:
        on_race()
