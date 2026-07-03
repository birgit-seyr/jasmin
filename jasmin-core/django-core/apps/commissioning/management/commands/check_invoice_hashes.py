"""Detect drift between an invoice's stored ``document_hash`` and the
hash recomputed from its current contents.

Why this exists
---------------
``InvoiceReseller.document_hash`` is written once at ``finalize_invoice``
and never touched again by the application. The hash by itself is just a
checksum — anyone who manages to mutate a finalized invoice row could
also overwrite the hash to match the new content. Treating the hash as
tamper-proof therefore requires an **external** verification step that
the tamperer can't also defeat.

This command IS that step. It iterates every finalized invoice, recomputes
the canonical payload's SHA-256, and emits a structured WARNING to the
``security`` log stream for every row whose hash no longer matches. The
``security`` log is the auditor's grep target (see logs/security.log),
and is typically shipped off-box / write-protected.

Usage
-----
    python manage.py check_invoice_hashes --schema=<tenant_schema>

Exit code
---------
- ``0``  every finalized invoice's hash is intact
- ``1``  at least one drift was detected — alert / page someone

Schedule
--------
Run nightly via cron / systemd timer / k8s CronJob. Recommended:

    0 3 * * *  python manage.py check_invoice_hashes --schema=<tenant>
"""

from __future__ import annotations

import logging
import sys

from django.core.management.base import BaseCommand

from apps.commissioning.services import InvoiceService

logger = logging.getLogger("django.security")


class Command(BaseCommand):
    help = (
        "Detect drift between InvoiceReseller.document_hash and the "
        "recomputed SHA-256 of the canonical invoice payload."
    )

    def handle(self, *args, **options) -> None:
        drifts = InvoiceService.find_drifted_invoices()

        if not drifts:
            self.stdout.write(
                self.style.SUCCESS("OK — every finalized invoice hash is intact.")
            )
            return

        for entry in drifts:
            # ERROR-level: hash drift is a tampering/corruption signal an operator
            # must investigate, so it surfaces in the security log AND raises a
            # Sentry event (not just a breadcrumb). Structured key=value layout is
            # intentional — ``grep "invoice.hash_drift"`` is the auditor's pivot.
            logger.error(
                "invoice.hash_drift id=%s number=%s prefix=%s "
                "stored_hash=%s recomputed_hash=%s",
                entry["id"],
                entry["number"],
                entry["prefix"],
                entry["stored"],
                entry["recomputed"],
            )
            self.stdout.write(
                self.style.ERROR(
                    f"DRIFT: invoice {entry['prefix']}-{entry['number']} "
                    f"(id={entry['id']})"
                )
            )

        self.stdout.write(
            self.style.ERROR(
                f"\n{len(drifts)} drifted invoice(s) detected. "
                "Investigate immediately — see security.log."
            )
        )
        sys.exit(1)
