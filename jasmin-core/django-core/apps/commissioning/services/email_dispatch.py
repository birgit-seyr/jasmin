"""Shared best-effort document-email dispatch for the reseller Invoice /
DeliveryNote flows.

``InvoiceService.send_to_reseller`` / ``send_to_accounting`` and
``DeliveryNoteService.send_to_reseller`` all do the same thing: load the
finalized PDF (the invoice additionally attaches its ZUGFeRD XML), send it via
``EmailService`` under a bounded except list, then stamp a ``*_sent_*_at``
timestamp on success without ever raising. Only the recipient, slug, context,
purpose and timestamp field vary — those parameters live here so the dispatch
contract (and the bounded except list) is defined once.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


def load_pdf_attachments(
    document: Any,
    *,
    default_pdf_name: str,
    log_label: str,
    include_xml: bool = False,
    default_xml_name: str = "rechnung.xml",
) -> list[tuple]:
    """Load ``document.file`` (and, when ``include_xml``, ``document.xml_file``)
    into the ``(filename, bytes, mimetype)`` tuples ``EmailService.send_email``
    expects.

    Returns an empty list if the PDF isn't on disk yet — callers MUST bail in
    that case rather than send a body-only mail. ``include_xml`` is the only
    invoice-vs-delivery-note difference (ZUGFeRD XML is invoice-only).
    """
    attachments: list[tuple] = []
    if not document.file:
        return attachments
    try:
        with document.file.open("rb") as file_handle:
            pdf_bytes = file_handle.read()
    except OSError:
        logger.exception(
            "Could not read %s PDF for %s — bailing", log_label, document.pk
        )
        return []
    pdf_name = document.file.name.rsplit("/", 1)[-1] or default_pdf_name
    attachments.append((pdf_name, pdf_bytes, "application/pdf"))
    if include_xml and document.xml_file:
        try:
            with document.xml_file.open("rb") as file_handle:
                xml_bytes = file_handle.read()
            xml_name = document.xml_file.name.rsplit("/", 1)[-1] or default_xml_name
            attachments.append((xml_name, xml_bytes, "application/xml"))
        except OSError:
            logger.exception(
                "Could not read %s XML for %s — skipping", log_label, document.pk
            )
    return attachments


def send_document_email(
    document: Any,
    *,
    slug: str,
    to_email: str,
    context_builder: Callable[[], dict],
    attachments: list[tuple],
    purpose: str,
    related_object_type: str,
    timestamp_field: str,
    log_label: str,
) -> bool:
    """Best-effort send of ``attachments`` to ``to_email`` via the ``slug``
    template, stamping ``timestamp_field`` on success. Never raises.

    Returns ``False`` on any failure (no PDF on disk, SMTP error, template
    error). Callers resolve the recipient (and its skip-logging) first;
    ``context_builder`` is invoked lazily only once a real send is attempted.
    """
    from apps.shared.tenants.email_service import EmailService

    if not attachments:
        logger.warning(
            "Skipping %s send for %s: PDF not yet uploaded.", purpose, document.pk
        )
        return False

    try:
        success = EmailService().send_email(
            slug=slug,
            to_emails=[to_email],
            context=context_builder(),
            attachments=attachments,
            purpose=purpose,
            related_object_type=related_object_type,
            related_object_id=str(document.pk),
        )
    except (
        smtplib.SMTPException,
        ConnectionError,
        OSError,
        ValueError,
        TypeError,
        AttributeError,
    ):
        # No recipient address in the log line — the EmailLog row already
        # records it under proper retention (EmailService's no-recipient-PII
        # logging policy).
        logger.exception(
            "Failed to send %s %s (recipient in EmailLog)", log_label, document.pk
        )
        return False

    if success:
        # ``timestamp_field`` is in the model's ALLOWED_FINALIZED_UPDATES, so
        # this save is permitted post-finalize. Save outside any wrapping
        # atomic — the email already went out; if this single-row update fails
        # we lose the timestamp but the recipient already has the document.
        setattr(document, timestamp_field, timezone.now())
        try:
            document.save(update_fields=[timestamp_field])
        except Exception:
            logger.exception(
                "%s %s: email sent, but tracker update failed", log_label, document.pk
            )
    return bool(success)
