"""Deferred (post-commit) best-effort email dispatch.

Every "state changed → notify by email" flow shares the same skeleton:
capture plain scalars, build the template context, then hand the
``EmailService.send_email`` call to ``transaction.on_commit`` so the
mail only fires once the surrounding atomic block has actually
persisted — a rolled-back state change must never produce a ghost
notification. ``schedule_deferred_email`` centralises that skeleton.

The send is best-effort: ``EmailService`` catches its own send-time
exceptions and returns ``False``; the narrow except here covers
pre-send paths (invalid slug → ``ValueError``) and connection failures
that escape. Anything outside that set is a real bug and must
propagate — but Django re-raises uncaught ``on_commit`` errors (which
would crash the response), so the catch stays narrow inside the
callback.

Lives in ``apps.shared`` so both ``apps.commissioning`` and
``apps.accounts`` flows can reuse it without breaking the one-way
commissioning isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.db import transaction


def schedule_deferred_email(
    *,
    slug: str,
    to_emails: list[str],
    context: dict[str, Any],
    related_object_type: str,
    related_object_id: str,
    language: str | None = None,
    logger: logging.Logger,
    log_error_event: str,
    log_not_sent_event: str,
    log_ref: str,
    post_send_callback: Callable[[], None] | None = None,
) -> None:
    """Schedule ``EmailService.send_email`` via ``transaction.on_commit``.

    When called outside an atomic block Django runs the callback
    immediately, so non-transactional callers (e.g. plain shell
    scripts) keep fire-and-forget semantics.

    ``logger`` / ``log_error_event`` / ``log_not_sent_event`` /
    ``log_ref`` preserve each call site's log routing and message text:
    a crashed send logs ``"<log_error_event> <log_ref> error=<exc>"``
    and an unsent mail (``send_email`` returned ``False``) logs
    ``"<log_not_sent_event> <log_ref>"``, both at ERROR level on the
    caller's logger. ``log_ref`` is the pre-formatted identity of the
    recipient/subject, e.g. ``f"member={member_id}"``.

    ``post_send_callback`` runs only after a genuinely successful send
    (``send_email`` returned ``True``) — e.g. stamping a "confirmation
    actually went out" timestamp.
    """

    def _dispatch() -> None:
        # Imported lazily so importing this module never drags in the
        # email stack (and so tests patching the real class location
        # see the patched method).
        from apps.shared.tenants.email_service import EmailService

        try:
            ok = EmailService().send_email(
                slug=slug,
                to_emails=to_emails,
                context=context,
                related_object_type=related_object_type,
                related_object_id=related_object_id,
                language=language,
            )
        except (ValueError, TypeError, AttributeError, OSError) as exc:
            logger.error("%s %s error=%s", log_error_event, log_ref, exc)
            return
        if not ok:
            logger.error("%s %s", log_not_sent_event, log_ref)
            return
        if post_send_callback is not None:
            post_send_callback()

    transaction.on_commit(_dispatch)
