"""SSOT for scheduling member-lifecycle emails after commit.

Every commissioning "member state changed → email the member" flow
(welcome / approval / rejection / cancellation / trial-conversion)
shares the same plumbing: the recipient is ``member.email``, the
related object is the member, the log reference is ``member=<id>``, and
the mail renders in the member's stored language when known (EML-9).
Only the template ``slug``, the context, and the per-site log-event
names differ.

:func:`schedule_member_email` centralises that plumbing and delegates
the transaction-aware dispatch (P1-3: fire on ``transaction.on_commit``
so a rolled-back state change never emails the member) to
:func:`apps.shared.deferred_email.schedule_deferred_email`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apps.shared.deferred_email import schedule_deferred_email

if TYPE_CHECKING:
    from ..models import Member


def schedule_member_email(
    member: Member,
    *,
    slug: str,
    context: dict[str, Any],
    logger: logging.Logger,
    log_error_event: str,
    log_not_sent_event: str,
    language: str | None = None,
    post_send_callback: Callable[[], None] | None = None,
) -> None:
    """Schedule one member-lifecycle email via ``on_commit``, best-effort.

    Fills in the member-derived arguments every such email shares — the
    recipient (``member.email``), the ``related_object`` (the member),
    the ``log_ref`` (``member=<id>``), and the recipient-language
    fallback (the member's linked user language, else the tenant
    default) — then hands off to :func:`schedule_deferred_email`.

    ``context`` is passed through untouched: callers flatten their own
    ``member.*`` fields to scalars before calling (never hand a live ORM
    instance to the tenant-editable renderer). Pass ``language`` to
    override the derived recipient language. ``post_send_callback`` runs
    only after a genuinely successful send (e.g. stamping a tracker).
    """
    member_id = member.id
    # EML-9: render in the linked user's stored language when known
    # (captured as a plain scalar before the on_commit closure; None →
    # tenant-language fallback inside send_email).
    recipient_language = (
        language
        if language is not None
        else getattr(getattr(member, "user", None), "user_language", None) or None
    )
    schedule_deferred_email(
        slug=slug,
        to_emails=[member.email],
        context=context,
        related_object_type="member",
        related_object_id=str(member_id),
        language=recipient_language,
        logger=logger,
        log_error_event=log_error_event,
        log_not_sent_event=log_not_sent_event,
        log_ref=f"member={member_id}",
        post_send_callback=post_send_callback,
    )
