"""Deferred (post-commit) best-effort email dispatch.

Every "state changed → notify by email" flow shares the same skeleton:
capture plain scalars, build the template context, then send the mail
through ``EmailService.send_email`` while isolating failures so a mail
outage never bubbles into (and rolls back) the caller's state change.

Two entry points:

* :func:`send_email_best_effort` — the synchronous skeleton: call
  ``EmailService.send_email``, swallow the narrow set of pre-send /
  connection exceptions, log a per-site event on crash or on an
  unsent (``send_email`` returned ``False``) mail, and return whether
  the send genuinely succeeded. Use it directly from a request/flow
  that has already committed (e.g. password reset, GDPR deletion).
* :func:`schedule_deferred_email` — the same skeleton, but deferred to
  ``transaction.on_commit`` so the mail only fires once the surrounding
  atomic block has actually persisted; a rolled-back state change must
  never produce a ghost notification. It delegates the actual send to
  :func:`send_email_best_effort` inside the callback.

The send is best-effort: ``EmailService`` catches its own send-time
exceptions and returns ``False``; the narrow except here covers
pre-send paths (invalid slug → ``ValueError``) and connection failures
that escape. Anything outside that set is a real bug and must
propagate — and because Django re-raises uncaught ``on_commit`` errors
(which would crash the response), the catch has to stay narrow.

Lives in ``apps.shared`` so ``apps.commissioning``, ``apps.accounts``
and ``apps.gdpr`` flows can reuse it without breaking the one-way
commissioning isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.db import transaction


def send_email_best_effort(
    *,
    slug: str,
    to_emails: list[str],
    context: dict[str, Any],
    related_object_type: str = "",
    related_object_id: str = "",
    language: str | None = None,
    priority: str = "normal",
    logger: logging.Logger,
    log_error_event: str,
    log_not_sent_event: str,
    log_ref: str,
    log_level: str = "error",
    post_send_callback: Callable[[], None] | None = None,
) -> bool:
    """Send one email synchronously, best-effort. Returns whether it went out.

    Calls ``EmailService.send_email`` and isolates the failure modes so a
    mail outage never propagates into the caller: a crashed send (one of
    ``ValueError`` / ``TypeError`` / ``AttributeError`` / ``OSError`` — the
    pre-send and connection paths that escape ``EmailService``) logs
    ``"<log_error_event> <log_ref> error=<exc>"`` and returns ``False``; an
    unsent mail (``send_email`` returned ``False``) logs
    ``"<log_not_sent_event> <log_ref>"`` and returns ``False``. Anything
    outside that except set is a real bug and propagates.

    ``log_level`` selects the severity of both failure lines: ``"error"``
    (the default — preserves the historic ERROR behaviour) or ``"warning"``
    for sites whose miss is genuinely non-actionable (e.g. the GDPR
    deletion-confirmation mail, which the user can simply re-request). Any
    value other than ``"warning"`` maps to ERROR so a typo never silently
    downgrades a real failure.

    ``log_ref`` is the pre-formatted identity of the recipient/subject, e.g.
    ``f"user={user.pk}"`` or ``f"member={member_id}"``.

    ``post_send_callback`` runs only after a genuinely successful send
    (``send_email`` returned ``True``) — e.g. stamping a "confirmation
    actually went out" timestamp — and its return value is ignored.
    """
    # Imported lazily so importing this module never drags in the email
    # stack (and so tests patching ``apps.shared.tenants.email_service``
    # see the patched class).
    from apps.shared.tenants.email_service import EmailService

    emit_log = logger.warning if log_level == "warning" else logger.error
    try:
        ok = EmailService().send_email(
            slug=slug,
            to_emails=to_emails,
            context=context,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            language=language,
            priority=priority,
        )
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        emit_log("%s %s error=%s", log_error_event, log_ref, exc)
        return False
    if not ok:
        emit_log("%s %s", log_not_sent_event, log_ref)
        return False
    if post_send_callback is not None:
        post_send_callback()
    return True


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
        send_email_best_effort(
            slug=slug,
            to_emails=to_emails,
            context=context,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            language=language,
            logger=logger,
            log_error_event=log_error_event,
            log_not_sent_event=log_not_sent_event,
            log_ref=log_ref,
            post_send_callback=post_send_callback,
        )

    transaction.on_commit(_dispatch)
