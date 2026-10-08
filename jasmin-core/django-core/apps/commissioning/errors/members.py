"""Errors of members, their logins and invitations, and consent versioning."""

from __future__ import annotations

from core.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)

# --------------------------------------------------------------------------- #
# Members                                                                     #
# --------------------------------------------------------------------------- #


class MemberNotFound(NotFoundError):
    code = "member.not_found"


class MemberProfileNotLinked(NotFoundError):
    """The authenticated user has no linked Member row (``member_profile``
    reverse OneToOne) — the self-service member endpoints have no target."""

    code = "member.profile_not_linked"


class CustomerProfileNotLinked(NotFoundError):
    """The authenticated user has no linked Reseller row
    (``linked_reseller`` reverse OneToOne) — the self-service customer
    endpoints have no target."""

    code = "customer.profile_not_linked"


class MemberAlreadyConfirmed(ConflictError):
    """Confirm called on an already-confirmed member."""

    code = "member.already_confirmed"


class MemberHasActiveSubscriptions(BadRequestError):
    """A member tried to self-cancel their membership while still holding
    active (admin-confirmed, not-cancelled, not-expired) subscriptions. They
    must wind those down first; the office can still force-cancel (which
    cascades and ends the subscriptions)."""

    code = "member.has_active_subscriptions"


class MemberAlreadyCancelled(ConflictError):
    """The membership is already cancelled."""

    code = "member.already_cancelled"


class MemberExitBeforeTransfer(BadRequestError):
    """A member's exit is dated before one of their own coop share transfers,
    given or received. Their shares would stop counting at the exit while the
    other side's only start at the transfer, leaving them held by nobody in
    the GenG member register in between. ``details.transfer_date`` is the
    latest transfer."""

    code = "member.exit_before_transfer"

    def __init__(self, *, transfer_date: str) -> None:
        super().__init__(
            f"The exit date is before a coop share transfer of this member "
            f"({transfer_date}).",
            field="effective_at",
            details={"transfer_date": transfer_date},
        )


class ConfirmationDateRequiresOnboardingMode(BadRequestError):
    """A member or coop share confirm request carried ``confirmed_at`` while the
    tenant's onboarding mode is off. Outside onboarding a confirmation is dated
    when it happens."""

    code = "member.confirmation_date_requires_onboarding_mode"

    def __init__(self) -> None:
        super().__init__(
            "A confirmation date can only be set while onboarding mode is on.",
            field="confirmed_at",
        )


class ConfirmationDateInFuture(BadRequestError):
    """A manual confirmation date lies after today."""

    code = "member.confirmation_date_in_future"

    def __init__(self) -> None:
        super().__init__(
            "The confirmation date can't be in the future.", field="confirmed_at"
        )


class ConfirmationDateAfterExit(BadRequestError):
    """A departed member is confirmed on a date after their exit date
    (``cancelled_effective_at``). Without a manual date the confirmation is
    dated today, so this is also raised when the exit date has already passed.
    ``details.exit_date`` carries the exit date."""

    code = "member.confirmation_date_after_exit"

    def __init__(self, exit_date) -> None:
        super().__init__(
            "The confirmation date can't be after the member's exit date.",
            field="confirmed_at",
            details={"exit_date": exit_date.isoformat()},
        )


class EmailActionBlockedInOnboardingMode(ConflictError):
    """An office action whose whole purpose is an email to a member (a portal
    invitation, a waiting-list spot offer) while the tenant's onboarding mode is
    on. No member emails go out in onboarding mode, so the action is refused
    before it creates a login or invitation, holds capacity or uses quota."""

    code = "onboarding_mode.email_action_blocked"

    def __init__(self) -> None:
        super().__init__(
            "This action emails the member, and no member emails are sent while "
            "onboarding mode is on. Turn off onboarding mode first."
        )


class CoopShareContractAgreementRequired(BadRequestError):
    """The tenant published a coop-share contract ("Zeichnungsvertrag") but the
    member tried to self-subscribe without affirming agreement to it."""

    code = "coop_share.contract_agreement_required"


class SubscriptionContractAgreementRequired(BadRequestError):
    """The tenant has a subscription contract ("Abo-Vertrag") in force, but the
    subscribe request didn't name the version that was accepted, or named one
    that isn't in force."""

    code = "subscription.contract_agreement_required"


class CoopShareValueNotConfigured(BadRequestError):
    """A coop-share self-subscription was attempted but the tenant has no
    configured per-share value — refuse rather than persist a 0-valued share."""

    code = "coop_share.value_not_configured"


class MemberCoopSharesOutOfRange(BadRequestError):
    """A non-trial member is being admin-confirmed (or a CoopShare for
    such a member is being changed) but the resulting total of coop
    shares would fall outside the tenant's configured
    ``min_number_coop_shares`` / ``max_number_coop_shares`` window.

    Trial members and not-yet-confirmed members are EXEMPT — the rule
    only applies once a member is committed to the Mitgliederliste
    under GenG. Office staff must adjust the coop-share rows (add /
    remove / edit amounts) until the total lands in range before they
    can confirm the member.
    """

    code = "member.coop_shares_out_of_range"

    def __init__(
        self,
        *,
        total,
        minimum=None,
        maximum=None,
        member_id: str | None = None,
    ) -> None:
        bits = [f"Total coop shares ({total}) is outside the allowed range"]
        # ``context`` selects the i18next message variant on the frontend
        # (``errors.member.coop_shares_out_of_range_<context>``) so the
        # localized text can phrase a two-sided range, a lower bound, or an
        # upper bound correctly. The English ``message`` below stays the
        # fallback for codes the frontend hasn't translated.
        if minimum is not None and maximum is not None:
            bits.append(f"[{minimum}, {maximum}]")
            context = "range"
        elif minimum is not None:
            bits.append(f"(minimum {minimum})")
            context = "min"
        elif maximum is not None:
            bits.append(f"(maximum {maximum})")
            context = "max"
        else:
            context = "none"
        if member_id:
            bits.append(f"for member {member_id}")
        super().__init__(
            " ".join(bits) + ".",
            details={
                "total": total,
                "minimum": minimum,
                "maximum": maximum,
                "member_id": member_id,
                "context": context,
            },
        )


class MemberIdentityRequired(BadRequestError):
    """A member create carried nothing that says who the row is for.

    Every Member column is nullable or defaulted, so serializer validation on
    its own accepts an empty body — and the Mitgliederliste, which is legally
    relevant, gains a row nobody can attribute afterwards. One identifying
    field is the floor rather than a name: a company member legitimately has no
    natural-person name, and an office-managed member may be on file with only
    a pickup name or an email address.
    """

    code = "member.identity_required"


class MemberNumberNotAllowedForTrial(BadRequestError):
    """A CSV import row set ``member_number`` on a row with ``is_trial=True``.

    Trial members are not Mitglieder under GenG (no Geschaeftsanteil yet), so
    they carry neither a Mitgliedsnummer nor an Eintrittsdatum — the conversion
    hook stamps both when ``is_trial`` flips to False. Accepting a number here
    would put a non-member into the Mitgliederliste numbering space and then
    silently keep it on conversion (``_post_confirm`` only generates a number
    when none is set)."""

    code = "member.number_not_allowed_for_trial"


class LockedAfterAdminConfirmation(BadRequestError):
    """Caller tried to edit a field that becomes legally fixed once
    the Member is admin-confirmed (Mitglied der Genossenschaft per
    GenG). Currently applies to ``birth_date`` (biological fact +
    GDPR-classified PII whose audit trail edits would falsify) and
    ``is_trial`` (the trial → full conversion is one-way; flipping
    back would orphan the assigned Mitgliedsnummer / Eintrittsdatum).

    Typo / historical corrections to these fields after confirmation
    are real — they just need ops intervention (DB / data migration)
    rather than a casual office PATCH so the change is conscious and
    auditable."""

    code = "member.locked_after_admin_confirmation"

    def __init__(self, field_names: list[str]) -> None:
        message = (
            "Cannot edit "
            + ", ".join(field_names)
            + " after admin confirmation. Use the ops procedure for "
            "historical correction."
        )
        super().__init__(message, details={"locked_fields": field_names})


class MemberLinkConflict(ConflictError):
    """Cannot link a JasminUser to a new Member.

    Subclass per failure mode so callers can ``except`` the right one
    (``UserInBlockedStatus``, ``UserAlreadyLinked``).
    """

    code = "member.link_conflict"


class UserInBlockedStatus(MemberLinkConflict):
    """The JasminUser is mid-flow with another application or inactive."""

    code = "member.user_in_blocked_status"


class UserAlreadyLinked(MemberLinkConflict):
    """The JasminUser is already linked to a different Member."""

    code = "member.user_already_linked"


class MemberInvitationError(BadRequestError):
    """Invitation cannot be sent for the given member."""

    code = "member.invitation_invalid"


class MemberHasNoEmail(MemberInvitationError):
    code = "member.no_email"


class MemberUserAlreadyActive(MemberInvitationError):
    code = "member.user_already_active"


class MemberEmailHeldByNonMemberLogin(MemberInvitationError):
    """The member's address already holds a login with no member profile.

    Distinct from :class:`MemberEmailAlreadyHasUser`, which names a login
    belonging to a DIFFERENT member. Here the row belongs to nobody — a staff
    account, or one still mid-invitation. Inviting into it would not create an
    account, it would take one over: the shared invitation helper reuses
    ``inactive`` / ``pending_invitation`` rows, rolling this member's name onto
    the row and replacing its roles, so the primary key and every
    ``created_by`` reference pointing at it silently changes owner.

    Attaching an existing login to a member is a separate, deliberate
    operation — ``MemberService.link_to_user``, which runs
    ``assert_user_can_be_linked``."""

    code = "member.email_held_by_non_member_login"


class MemberEmailAlreadyHasUser(MemberInvitationError):
    """Cannot invite THIS member: their email address already holds a login
    that belongs to a DIFFERENT member.

    ``Member.email`` is deliberately not unique — two members may share one
    inbox (an elderly couple with a single address). ``JasminUser.email`` is
    the ``USERNAME_FIELD`` and IS unique, so a shared inbox can carry at most
    one login. Whoever was invited first holds it; the other member is
    office-managed and simply has no self-service account.

    Raised BEFORE any user record is touched, so the existing member's account
    (name, status, open invitation) is never rewritten by an invite meant for
    their partner. ``details`` names the holder so the office sees who has it.
    """

    code = "member.email_already_has_user"

    def __init__(self, *, email: str, holder=None) -> None:
        holder_name = ""
        holder_number = None
        if holder is not None:
            holder_name = " ".join(
                bit for bit in (holder.first_name, holder.last_name) if bit
            ).strip()
            holder_number = holder.member_number
        message = (
            f"The address {email} already has a user account"
            + (f" belonging to {holder_name}" if holder_name else "")
            + (f" (#{holder_number})" if holder_number else "")
            + ". An email can hold only one login — invite that member, or "
            "give this one their own address."
        )
        # ``context`` selects the i18next variant
        # (``errors.member.email_already_has_user_<context>``) so the localized
        # text can name the holder when we know them and stay generic when we
        # don't — same mechanism as ``member.coop_shares_out_of_range``.
        if holder_name and holder_number:
            context = "named_numbered"
        elif holder_name:
            context = "named"
        else:
            context = "anonymous"
        super().__init__(
            message,
            details={
                "email": email,
                "holder_name": holder_name or None,
                "holder_member_number": holder_number,
                "holder_member_id": str(holder.id) if holder is not None else None,
                "context": context,
            },
        )


# --------------------------------------------------------------------------- #
# Consent versioning                                                          #
# --------------------------------------------------------------------------- #


class ConsentDocumentNotFound(NotFoundError):
    """No ConsentDocument exists for the requested (kind, locale) at this date."""

    code = "consent.document_not_found"


class ConsentTargetMemberUnresolved(BadRequestError):
    """A consent record could not be attributed to any Member: the payload
    carried no explicit ``member`` and the caller has no linked Member of
    their own (e.g. an office user creating a record without naming the
    member it is for)."""

    code = "consent.target_member_unresolved"


class ConsentAlreadyRevoked(ConflictError):
    """Caller tried to revoke a ConsentRecord that was already revoked."""

    code = "consent.already_revoked"


class ConsentRevokeReasonReserved(BadRequestError):
    """A withdrawal's reason is exactly the token ``ConsentService.supersede``
    stores on a consent replaced by a newer one. Kept for that case alone, so
    a withdrawal can never be read as a re-signing."""

    code = "consent.revoke_reason_reserved"


class ConsentDocumentInUse(ConflictError):
    """Caller tried to delete a ConsentDocument that has at least one
    ConsentRecord pointing at it. Documents that members have agreed
    to are append-only; publish a new version instead."""

    code = "consent.document_in_use"


class ConsentDocumentImmutable(ConflictError):
    """Caller tried to change what members consented to — ``body``, ``title``,
    ``kind``, ``locale``, ``version`` or ``valid_from`` — on a ConsentDocument
    that at least one ConsentRecord references. Consented documents are
    append-only; publish a new version instead. Drafts nobody has consented to
    yet stay editable."""

    code = "consent.document_immutable"
