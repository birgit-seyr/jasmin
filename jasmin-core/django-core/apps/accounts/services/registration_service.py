"""Public self-registration service.

Self-registered users always create a Member row and start in
``account_status="pending_approval"``. Office must confirm the Member
before they can log in. The Member.confirm() override flips the user
to ``active`` (see commissioning/models/members.py).
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.authz.roles import Role

from ..errors import RegistrationEmailNotVerified, RegistrationError
from ..models import JasminUser
from . import email_verification_service

logger = logging.getLogger("authentication")


_REQUIRED = ("first_name", "last_name", "email")


def _assert_required_consents(accepted: dict, *, coop_shares_count: int, as_of) -> None:
    """Reject a public registration that omits a mandatory, currently-published
    consent — the server-side counterpart to the authenticated self-service
    gates (e.g. ``MyCoopShareSubscribeView``'s COOP_CONTRACT check). A kind is
    required only when the tenant has a CURRENT document for it (nothing to
    accept otherwise); the cooperative contract is required only when the
    applicant requests equity. Each accepted id must resolve to a current
    document of that kind — a forged / stale / kind-mismatched id doesn't count.
    """
    from django.db.models import Q

    from apps.commissioning.models import ConsentDocument
    from apps.commissioning.models.choices import ConsentKind

    required = [ConsentKind.PRIVACY, ConsentKind.WITHDRAWAL]
    if coop_shares_count > 0:
        required.append(ConsentKind.COOP_CONTRACT)

    def _current(**kw):
        return ConsentDocument.objects.filter(valid_from__lte=as_of, **kw).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=as_of)
        )

    missing = []
    for kind in required:
        if not _current(kind=kind).exists():
            continue  # tenant hasn't published this policy — nothing to accept
        doc_id = accepted.get(kind)
        if not doc_id or not _current(id=doc_id, kind=kind).exists():
            missing.append(str(kind.label))
    if missing:
        raise RegistrationError(
            "The following agreements must be accepted to register: "
            + ", ".join(sorted(missing)),
            field="accepted_consent_documents",
        )


@transaction.atomic
def register_public_applicant(
    *, data: dict[str, Any], tenant, ip_address: str | None = None, user_agent: str = ""
) -> dict:
    from apps.commissioning.models import (
        ConsentDocument,
        CoopShare,
        Member,
    )

    # Honeypot — see ``PublicRegisterRequestSerializer.website``.
    # A non-empty ``website`` is the bot tell. Return a fake-success
    # response so the bot moves on and stops retrying instead of
    # adapting; do NOT raise (raising would tell the bot the field is
    # rejected, prompting them to drop it on the next attempt).
    if str(data.get("website", "")).strip():
        logger.info("registration.honeypot_triggered tenant=%s", tenant.schema_name)
        return {
            "message": "Registration received. Please check your email.",
            "member_id": None,
            "user_id": None,
            "coop_shares_created": 0,
        }

    missing = [f for f in _REQUIRED if not str(data.get(f, "")).strip()]
    if missing:
        raise RegistrationError(f"Missing required fields: {', '.join(missing)}")

    email = data["email"].strip().lower()
    # The address MUST have completed the code check first (see
    # ``register/verify_code/``). This is what makes it safe to email a
    # set-password link below — the address is proven to be the applicant's.
    if not email_verification_service.is_email_verified(email):
        raise RegistrationEmailNotVerified(
            "Please verify your email address before completing registration."
        )

    # Generic message to avoid email enumeration on this public endpoint.
    if JasminUser.objects.filter(email__iexact=email).exists():
        raise RegistrationError("Could not register with the provided details.")

    # Server-side consent gate: a raw API caller must not be able to create a
    # member — or request cooperative equity — without the mandatory versioned
    # consents on record. The wizard enforces this in the UI, but the server
    # must too (GDPR Art. 7 / GenG audit trail). Reject BEFORE creating the user
    # / sending the set-password email. Compute the equity intent once so the
    # same value gates consent AND the CoopShare row below.
    from django.utils import timezone

    as_of = timezone.now().date()
    accepted = data.get("accepted_consent_documents")
    accepted = accepted if isinstance(accepted, dict) else {}
    is_trial = bool(data.get("is_trial"))
    coop_shares_count = 0 if is_trial else int(data.get("coop_shares_count") or 0)
    _assert_required_consents(
        accepted, coop_shares_count=coop_shares_count, as_of=as_of
    )

    # Create the account WITHOUT a usable password and email a set-password
    # (``accounts.invitation``) link. The applicant sets their password from
    # that link — never during the wizard. ``create_user_with_invitation``
    # handles the unusable-password user, the one-time token and the email.
    from apps.shared.invitations import create_user_with_invitation

    try:
        user, _invitation = create_user_with_invitation(
            email=email,
            first_name=data["first_name"].strip(),
            last_name=data["last_name"].strip(),
            roles=[Role.MEMBER],
            user_language=data.get("user_language") or "en",
        )
    except (IntegrityError, ValidationError) as exc:
        # Check-then-create race, or the address became an active account
        # between verify_code and here. Same generic error either way — leak
        # nothing about which.
        logger.info("registration.duplicate_email_race")
        raise RegistrationError(
            "Could not register with the provided details."
        ) from exc

    # Build the Member.note from any free-form ``message`` plus a
    # subscription-intent block so office sees the applicant's wizard
    # choices when reviewing. We don't create a real Subscription here
    # because it needs FKs (payment_cycle, default_delivery_station_day)
    # the wizard doesn't gather — office completes that on confirm.
    note_parts: list[str] = []
    if data.get("message"):
        note_parts.append(str(data["message"]).strip())
    intent = _format_subscription_intent(data)
    if intent:
        note_parts.append(intent)

    # The interactive office create path (MemberViewSet.create) is volume-capped;
    # self-registration mints a Member too, so cap it on the same weekly budget.
    # This whole flow is atomic, so a refusal rolls back the just-created user as
    # well. (User creation is separately capped inside create_user_with_invitation.)
    from apps.shared.tenants.models import RateLimitedAction
    from apps.shared.tenants.rate_limits import enforce_action_quota

    enforce_action_quota(RateLimitedAction.MEMBER_CREATION, actor=user)

    # Trial (Probe-Abo) registration: a trial member subscribes no cooperative
    # shares (they aren't a Genosse yet); the office converts the trial to a
    # full membership later. ``is_trial`` / ``coop_shares_count`` were computed
    # above for the consent gate — reuse them.
    member = Member.objects.create(
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        email=email,
        address=(data.get("address") or "").strip() or None,
        zip_code=(data.get("zip_code") or "").strip() or None,
        city=(data.get("city") or "").strip() or None,
        country=(data.get("country") or "").strip() or None,
        note="\n\n".join(note_parts) or None,
        is_trial=is_trial,
        user=user,
        created_by=user,
    )

    # Cooperative shares — one CoopShare row, quantity = applicant's
    # requested count. Pending (admin_confirmed=False) until office
    # confirms. ``value_one_coop_share`` is snapshotted from the
    # current TenantSettings so the equity record survives later
    # value changes (GenG §31 — 10-year retention of paid-in capital).
    # Trial members subscribe no coop shares (``coop_shares_count`` computed
    # above already forces 0 for trials).
    if coop_shares_count > 0:
        from apps.shared.tenants.models import TenantSettings

        settings = TenantSettings.get_current_settings(tenant)
        # value_one_coop_share is a whole-unit PositiveIntegerField — snapshot
        # it as-is (no rounding needed) so the equity record survives later
        # value changes (GenG §31).
        share_value = int(settings.value_one_coop_share) if settings else 100
        # Cap at the tenant maximum — a raw caller could post an absurd count
        # past the UI's bound. (The GenG MINIMUM is enforced at office confirm
        # via ``CoopShareService.assert_member_total_within_bounds``.)
        max_shares = int(settings.max_number_coop_shares) if settings else 100
        if coop_shares_count > max_shares:
            raise RegistrationError(
                "The number of cooperative shares exceeds the maximum.",
                field="coop_shares_count",
            )
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=coop_shares_count,
            value_one_coop_share=share_value,
        )

    # Consent records — one per accepted document. Each posted id is resolved
    # to a real ConsentDocument that is (a) of the claimed kind and (b) CURRENT
    # (within its valid_from/valid_until window) — so a forged id, a
    # kind-mismatched id, or a superseded (stale-tab) version is skipped rather
    # than recorded as valid consent.
    # ``accepted`` was normalised to a dict above (and the required subset
    # already enforced by ``_assert_required_consents``).
    consent_records_created = 0
    if accepted:
        # Route through ConsentService.record (not a raw create) so the
        # denormalized Member consent-cache columns are synced and the
        # forensic ip_address / user_agent are captured — the public web signup
        # is exactly where that provenance matters most (GDPR-CON-3).
        from django.db.models import Q
        from django.utils import timezone

        from apps.commissioning.services.consent_service import ConsentService

        today = timezone.now().date()
        for kind, doc_id in accepted.items():
            doc = (
                ConsentDocument.objects.filter(
                    id=doc_id, kind=kind, valid_from__lte=today
                )
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
                .first()
            )
            if doc is None:
                continue
            ConsentService.record(
                member=member,
                document=doc,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            consent_records_created += 1

    # The set-password (``accounts.invitation``) email already went out via
    # ``create_user_with_invitation``. Consume the verified marker so this one
    # email verification can't be replayed for a second registration — but only
    # AFTER the transaction commits, so a rollback doesn't strand the applicant
    # (marker gone yet no account created ⇒ retry would 400 "not verified").
    transaction.on_commit(lambda: email_verification_service.clear_verified(email))

    logger.info(
        "register.public email=%s member=%s coop_shares=%s consents=%s",
        email,
        member.id,
        1 if coop_shares_count > 0 else 0,
        consent_records_created,
    )
    return {
        "message": (
            "Registration received. Check your email for a link to set your "
            "password. The office will review your membership."
        ),
        "member_id": member.id,
        "user_id": user.id,
        "coop_shares_created": 1 if coop_shares_count > 0 else 0,
        "consent_records_created": consent_records_created,
    }


def _format_subscription_intent(data: dict[str, Any]) -> str:
    """Render the wizard's subscription choice as a structured note line.

    Returns an empty string when the applicant didn't pick a variation.
    Format is deliberately greppable (``[Subscription intent]``) so
    office tooling can later parse / surface it.
    """
    variation_id = (data.get("share_type_variation_id") or "").strip()
    quantity = data.get("quantity")
    if not variation_id:
        return ""
    label = (
        "[Trial subscription intent]"
        if data.get("is_trial")
        else "[Subscription intent]"
    )
    parts = [
        label,
        f"share_type_variation_id={variation_id}",
        f"quantity={quantity or 1}",
    ]
    station = str(data.get("default_delivery_station_day") or "").strip()
    if station:
        parts.append(f"default_delivery_station_day={station}")
    price = data.get("price_per_delivery")
    if price not in (None, ""):
        parts.append(f"price_per_delivery={price}")
    payment_cycle = str(data.get("payment_cycle") or "").strip()
    if payment_cycle:
        parts.append(f"payment_cycle={payment_cycle}")
    valid_from = str(data.get("valid_from") or "").strip()
    if valid_from:
        parts.append(f"valid_from={valid_from}")
    valid_until = str(data.get("valid_until") or "").strip()
    if valid_until:
        parts.append(f"valid_until={valid_until}")
    return " ".join(parts)
