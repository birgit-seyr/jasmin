"""Public self-registration service.

Self-registered users always create a Member row and start in
``account_status="pending_approval"``. Office must confirm the Member
before they can log in. The Member.confirm() override flips the user
to ``active`` (see commissioning/models/members.py).
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.authz.roles import Role
from apps.shared.deferred_email import schedule_deferred_email

from ..errors import RegistrationError
from ..models import JasminUser

logger = logging.getLogger("authentication")


_REQUIRED = ("first_name", "last_name", "email", "password")


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
    # Generic message to avoid email enumeration on this public endpoint.
    if JasminUser.objects.filter(email__iexact=email).exists():
        raise RegistrationError("Could not register with the provided details.")

    try:
        password_validation.validate_password(data["password"])
    except ValidationError as exc:
        raise RegistrationError(
            "; ".join(exc.messages),
            field="password",
            code="registration.weak_password",
        ) from exc

    try:
        user = JasminUser.objects.create_user(
            first_name=data["first_name"].strip(),
            last_name=data["last_name"].strip(),
            email=email,
            password=data["password"],
            user_language=data.get("user_language") or "en",
            roles=[Role.MEMBER],
            account_status="pending_approval",
        )
    except IntegrityError as exc:
        # Check-then-create race: a concurrent registration for the same
        # email slipped past the friendly pre-check above; the unique
        # constraint is the source of truth. Map to the same generic
        # duplicate-email error so this path leaks nothing either. Don't log
        # the address — no-recipient-PII logging policy; the event itself is
        # the signal.
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

    member = Member.objects.create(
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        email=email,
        address=(data.get("address") or "").strip() or None,
        zip_code=(data.get("zip_code") or "").strip() or None,
        city=(data.get("city") or "").strip() or None,
        country=(data.get("country") or "").strip() or None,
        note="\n\n".join(note_parts) or None,
        user=user,
        created_by=user,
    )

    # Cooperative shares — one CoopShare row, quantity = applicant's
    # requested count. Pending (admin_confirmed=False) until office
    # confirms. ``value_one_coop_share`` is snapshotted from the
    # current TenantSettings so the equity record survives later
    # value changes (GenG §31 — 10-year retention of paid-in capital).
    coop_shares_count = int(data.get("coop_shares_count") or 0)
    if coop_shares_count > 0:
        from apps.shared.tenants.models import TenantSettings

        settings = TenantSettings.get_current_settings(tenant)
        # value_one_coop_share is a whole-unit PositiveIntegerField — snapshot
        # it as-is (no rounding needed) so the equity record survives later
        # value changes (GenG §31).
        share_value = int(settings.value_one_coop_share) if settings else 100
        CoopShare.objects.create(
            member=member,
            amount_of_coop_shares=coop_shares_count,
            value_one_coop_share=share_value,
        )

    # Consent records — one per accepted document. Resolves each
    # document_id to a real ConsentDocument so a bad client can't
    # forge an arbitrary id.
    accepted = data.get("accepted_consent_documents") or {}
    consent_records_created = 0
    if isinstance(accepted, dict) and accepted:
        # Route through ConsentService.record (not a raw create) so the
        # denormalized Member consent-cache columns are synced and the
        # forensic ip_address / user_agent are captured — the public web signup
        # is exactly where that provenance matters most (GDPR-CON-3).
        from apps.commissioning.services.consent_service import ConsentService

        valid_docs = ConsentDocument.objects.filter(id__in=list(accepted.values()))
        for doc in valid_docs:
            ConsentService.record(
                member=member,
                document=doc,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            consent_records_created += 1

    # Best-effort acknowledgement email — deferred to ``on_commit`` so
    # that if anything later in this atomic block rolls back, the
    # applicant doesn't get an "application received" mail for a row
    # that never persisted (P1-3).
    member_id = member.id
    tenant_name = tenant.name
    # EML-9: the self-registered applicant chose a language at signup — render
    # the confirmation in it (captured before the on_commit closure).
    applicant_lang = (
        getattr(getattr(member, "user", None), "user_language", None) or None
    )

    schedule_deferred_email(
        slug="accounts.application_received",
        to_emails=[email],
        # Flatten to plain scalars — never hand a live ORM instance to
        # the tenant-editable email renderer (see
        # template_renderer._resolve). The shipped template uses
        # ``member.first_name``; ``applicant`` mirrors it for the
        # registry-declared preview vars.
        context={
            "tenant_name": tenant_name,
            "member": {
                "first_name": member.first_name,
                "email": member.email,
            },
            "applicant": {
                "first_name": member.first_name,
                "email": member.email,
            },
        },
        related_object_type="member",
        related_object_id=str(member_id),
        language=applicant_lang,
        logger=logger,
        log_error_event="application.email_failed",
        log_not_sent_event="application.email_not_sent",
        log_ref=f"email={email}",
    )

    logger.info(
        "register.public email=%s member=%s coop_shares=%s consents=%s",
        email,
        member.id,
        1 if coop_shares_count > 0 else 0,
        consent_records_created,
    )
    return {
        "message": "Application received. Office must approve your account before you can sign in.",
        "member_id": member.id,
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
    return (
        "[Subscription intent] "
        f"share_type_variation_id={variation_id} quantity={quantity or 1}"
    )
