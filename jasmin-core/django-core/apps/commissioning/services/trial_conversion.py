"""Convert a trial Member to a full (GenG) member.

A "trial member" is someone who can hold trial subscriptions but has
not yet committed cooperative equity. Under the GenG, a person only
becomes a Mitglied when they acquire a Geschäftsanteil
(``CoopShare``). The conversion therefore fires the moment a
``CoopShare`` exists for that ``Member``:

* ``is_trial`` flips to ``False``
* ``trial_converted_at`` is stamped (audit trail; ``None`` means
  "still on trial" OR "joined as a full member directly").
* ``member_number`` is assigned via the existing sequence
  (``Member._generate_member_number()``), which holds the
  ``pg_advisory_xact_lock`` to serialise concurrent admin-confirm
  bursts.
* ``entry_date`` is stamped to today — the GenG §30 Eintrittsdatum.
  This is the date the person legally became a Mitglied (their first
  Geschäftsanteil), NOT the share-payment date and NOT a chosen value.
  Paired 1:1 with the Austrittsdatum on ``CancellableMixin``.

A successful conversion also schedules a
``commissioning.trial_converted`` welcome email via
``transaction.on_commit`` — the GenG-membership counterpart of
``accounts.welcome_user`` (user-account event). Best-effort: a send
failure logs and continues, the state change never rolls back on
mail-backend trouble.

Idempotent: calling this on a member who is already a full member is
a no-op. Always wrap the caller's CoopShare creation in the SAME
transaction so the trial flip and the share insert commit together.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from ..models import Member

logger = logging.getLogger(__name__)


def convert_trial_member_on_first_coop_share(member: Member) -> bool:
    """Convert ``member`` from trial → full when they acquire equity.

    Returns ``True`` if a conversion actually happened (state changed),
    ``False`` if the member was already a full member.

    Caller is expected to be inside a transaction that ALSO inserts the
    triggering ``CoopShare``. The current ``transaction.atomic`` wrapper
    here is a savepoint, not the outermost boundary — keep the share
    insert + this call in one block at the call site.
    """
    if not member.is_trial:
        return False

    with transaction.atomic():
        # Re-fetch the row under a write lock and re-check ``is_trial``
        # before doing anything. The guard above reads the caller's
        # in-memory snapshot, so two concurrent first-CoopShare inserts
        # would BOTH see ``is_trial=True`` and BOTH convert — burning a
        # second member_number from the sequence and firing a duplicate
        # welcome email. ``select_for_update`` serialises them: the
        # second transaction blocks until the first commits the flip,
        # then reloads ``is_trial=False`` here and bails out as a no-op.
        # Holds because we are inside ``transaction.atomic()``.
        # select_related("user") so the on_commit email callback's
        # ``member.user.user_language`` read doesn't fire a lazy query per
        # conversion (the user FK is eagerly joined into this locked SELECT).
        # ``of=("self",)`` locks ONLY the member row — ``user`` is nullable, so
        # select_related makes it a LEFT OUTER JOIN and Postgres refuses
        # ``FOR UPDATE`` on the nullable side of an outer join.
        member = (
            Member.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=member.pk)
        )
        if not member.is_trial:
            return False

        member.is_trial = False
        # ``is_trial`` just flipped, so the GenG min/max coop-share window
        # now applies (it exempts trial members). The triggering CoopShare
        # is already inserted by the caller's save(), so this counts it. An
        # out-of-range total raises MemberCoopSharesOutOfRange — and because
        # CoopShare.save() wraps the insert + this conversion in one atomic
        # block, that rolls back BOTH the conversion and the share insert.
        # Checked before stamping member_number so a rejected conversion
        # doesn't burn a number from the sequence.
        from .coop_share_service import CoopShareService

        # only_confirmed: admission counts CONFIRMED equity only — the triggering
        # share is confirmed but sibling pending shares aren't swept in here, so
        # a member must not be converted on pending equity that can later be
        # rejected/deleted (BIZ-3).
        CoopShareService.assert_member_total_within_bounds(member, only_confirmed=True)

        # ``trial_converted_at`` is a DateTimeField — full UTC
        # timestamp is correct for an audit moment.
        member.trial_converted_at = timezone.now()
        update_fields = ["is_trial", "trial_converted_at"]
        if not member.entry_date:
            # GenG §30 Eintrittsdatum — a CALENDAR day in the
            # operator's local timezone, NOT UTC. ``timezone.now()
            # .date()`` would drift by a day for tenants whose local
            # midnight is on the other side of the UTC line (Europe/
            # Berlin in winter / summer, anywhere east). Matches the
            # local-date stamp ``Member._post_confirm`` uses for the
            # non-trial admit path so the two flows agree.
            member.entry_date = timezone.localdate()
            update_fields.append("entry_date")
        if not member.member_number:
            # Mutates ``member.member_number`` AND issues its own save
            # of the ``member_number`` column under the advisory lock.
            member._generate_member_number()
        member.save(update_fields=update_fields)

    if member.email:
        _send_trial_converted_email(member)

    return True


def _send_trial_converted_email(member: Member) -> None:
    """Schedule the ``commissioning.trial_converted`` welcome via
    ``on_commit`` (P1-3 atomicity policy).

    Conceptually the GenG-membership counterpart of
    ``accounts.welcome_user`` (user-account event). Best-effort: the
    callback never bubbles out into the caller's response.
    """
    from apps.shared.tenant_urls import frontend_base_url, tenant_name

    from .member_email import schedule_member_email

    context = {
        "tenant_name": tenant_name(),
        # Flatten to plain scalars — never hand a live ORM instance to the
        # tenant-editable email renderer (see template_renderer._resolve).
        "member": {
            "first_name": member.first_name,
            "member_number": member.member_number,
        },
        # GenG §30 Eintrittsdatum is a local calendar day — render
        # it that way too. Templates use ``{{ entry_date }}``
        # directly so we pre-format with the locale-friendly
        # dd.mm.yyyy here rather than leaving Django to ISO-format
        # it.
        "entry_date": (
            member.entry_date.strftime("%d.%m.%Y") if member.entry_date else ""
        ),
        "portal_url": frontend_base_url(),
    }

    schedule_member_email(
        member,
        slug="commissioning.trial_converted",
        context=context,
        logger=logger,
        log_error_event="trial_converted.email_failed",
        log_not_sent_event="trial_converted.email_not_sent",
    )
