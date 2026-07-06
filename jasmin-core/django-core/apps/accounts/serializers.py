"""Serializers for the accounts app.

Used primarily for OpenAPI schema generation via ``drf-spectacular``.
The views themselves return plain ``Response`` payloads built from
service-layer functions.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.shared.languages import LanguageChoices


class UserProfileUpdateRequestSerializer(serializers.Serializer):
    """Request body for ``PATCH /api/auth/<user_id>/``."""

    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    user_language = serializers.ChoiceField(
        choices=LanguageChoices.choices, required=False
    )


class UserProfileResponseSerializer(serializers.Serializer):
    """Response body for ``PATCH /api/auth/<user_id>/``."""

    # JasminModel.id is a 12-char nanoid STRING — never IntegerField.
    id = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    user_language = serializers.CharField()


# --------------------------------------------------------------------------- #
# Login / refresh / logout                                                    #
# --------------------------------------------------------------------------- #


class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    # Friendly Captcha solution. Required at the service layer when
    # ``FRIENDLY_CAPTCHA_ENABLED=True``; absent (or ignored) when the
    # feature flag is off. Optional in the schema so the contract
    # stays stable across flag flips.
    frc_captcha_solution = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )

    def validate_email(self, value: str) -> str:
        # Normalize so django-axes keys ONE lockout bucket per account: the DB
        # lookup is ``email__iexact``, so ``Foo@x`` and ``foo@x`` are the same
        # user, and axes keys on the credential string handed to
        # ``authenticate()`` — without normalization, case-variation sidesteps
        # the (username, ip) lockout entirely.
        return value.strip().lower()


class LoginUserSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    user_language = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    permissions = serializers.ListField(child=serializers.CharField())
    member_id = serializers.CharField(allow_null=True, required=False)
    reseller_id = serializers.CharField(allow_null=True, required=False)


class LoginTenantSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    schema_name = serializers.CharField()


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = LoginUserSerializer()
    tenant = LoginTenantSerializer()


class RefreshResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    tenant = LoginTenantSerializer(required=False)


class MessageResponseSerializer(serializers.Serializer):
    """Generic ``{"message": "..."}`` payload used by several views."""

    message = serializers.CharField()


# --------------------------------------------------------------------------- #
# Step-up authentication                                                      #
# --------------------------------------------------------------------------- #


class StepUpRequestSerializer(serializers.Serializer):
    """Body for ``POST /api/auth/step-up/``.

    The TOTP code is optional in the schema so the contract stays
    stable across the ``STEP_UP_REQUIRES_TOTP`` flag; the backend
    rejects when the flag is on and the code is missing/wrong.
    """

    password = serializers.CharField(write_only=True)
    totp_code = serializers.CharField(required=False, allow_blank=True, write_only=True)


class StepUpResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    # Mirrors ``StepUpRequired.details.ttl_seconds`` so the frontend
    # can render "valid for N min" without hard-coding the value.
    ttl_seconds = serializers.IntegerField()


# --------------------------------------------------------------------------- #
# Two-factor auth                                                             #
# --------------------------------------------------------------------------- #


class TwoFactorChallengeResponseSerializer(serializers.Serializer):
    """Returned by ``/api/auth/login/`` when the user has 2FA active.

    Frontend posts ``challenge_token`` back to ``/api/auth/2fa/verify/``
    together with the 6-digit code to obtain a real access + refresh
    token. Contains no ``access`` field — that's the whole point.
    """

    requires_2fa = serializers.BooleanField()
    challenge_token = serializers.CharField()


class TwoFactorStatusResponseSerializer(serializers.Serializer):
    enrolled = serializers.BooleanField()
    enrolled_at = serializers.DateTimeField(allow_null=True)
    recovery_codes_remaining = serializers.IntegerField()


class TwoFactorEnrolStartResponseSerializer(serializers.Serializer):
    secret = serializers.CharField(
        help_text="Base32-encoded secret. Shown as plaintext for users who "
        "can't scan the QR code."
    )
    provisioning_uri = serializers.CharField(
        help_text="``otpauth://`` URI. Render as QR client-side."
    )


class TwoFactorCodeRequestSerializer(serializers.Serializer):
    code = serializers.CharField()


class TwoFactorVerifyRequestSerializer(serializers.Serializer):
    challenge_token = serializers.CharField()
    code = serializers.CharField()


class TwoFactorRecoveryCodesResponseSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())


# --------------------------------------------------------------------------- #
# Invitation accept / verify                                                  #
# --------------------------------------------------------------------------- #


class InvitationVerifyResponseSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    tenant_name = serializers.CharField(allow_blank=True)


class InvitationAcceptRequestSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)


# --------------------------------------------------------------------------- #
# Password reset                                                              #
# --------------------------------------------------------------------------- #


class PasswordResetRequestRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    frc_captcha_solution = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )


class PasswordResetConfirmRequestSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)
    frc_captcha_solution = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )


# --------------------------------------------------------------------------- #
# Public self-registration                                                    #
# --------------------------------------------------------------------------- #


class PublicRegisterRequestSerializer(serializers.Serializer):
    """Payload for ``POST /api/auth/register/``.

    The accounts service accepts arbitrary additional member-application
    fields, so this serializer is intentionally permissive. New fields
    listed here are explicit so drf-spectacular / orval pick them up.
    """

    # No password here: the applicant never sets one during the wizard. The
    # account is created without a usable password and an ``accounts.invitation``
    # (set-password) link is emailed on success — see ``registration_service``.
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    # Optional address fields.
    address = serializers.CharField(required=False, allow_blank=True)
    zip_code = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)

    # Number of cooperative shares the applicant wants. Creates a single
    # CoopShare row with this quantity in pending (admin_confirmed=False)
    # state — office reviews when confirming the Member.
    coop_shares_count = serializers.IntegerField(required=False, min_value=0)

    # Subscription intent. We can't create a real Subscription here
    # because it needs FKs (payment_cycle, default_delivery_station_day)
    # the wizard doesn't collect — office completes that during confirm.
    # The service stashes these as a structured note on the Member so
    # they show up on the admin detail page.
    share_type_variation_id = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(required=False, min_value=1)
    # Intent extras from the public "new subscription" modal: the applicant's
    # preferred delivery station-day + (solidarity) price. Recorded as intent
    # on the Member note for the office to finalise — NOT used to create a real
    # Subscription here (that needs office-set FKs).
    default_delivery_station_day = serializers.CharField(
        required=False, allow_blank=True
    )
    price_per_delivery = serializers.CharField(required=False, allow_blank=True)
    payment_cycle = serializers.CharField(required=False, allow_blank=True)
    # Trial (Probe-Abo) registration: creates a trial Member (no coop shares)
    # and records a trial subscription intent bounded by valid_from/valid_until.
    is_trial = serializers.BooleanField(required=False, default=False)
    valid_from = serializers.CharField(required=False, allow_blank=True)
    valid_until = serializers.CharField(required=False, allow_blank=True)

    # Map of consent kind -> ConsentDocument id the user agreed to.
    # Creates one ConsentRecord per entry in the same transaction.
    accepted_consent_documents = serializers.DictField(
        child=serializers.CharField(),
        required=False,
    )

    # Free-text note from the applicant — appended to the Member note
    # the office reviews during confirmation.
    message = serializers.CharField(required=False, allow_blank=True)

    # Preferred UI language for the created user.
    user_language = serializers.ChoiceField(
        choices=LanguageChoices.choices, required=False
    )

    # Honeypot. The frontend renders this as a hidden field that real
    # users can't see (visually hidden + tabIndex=-1 + autocomplete=off).
    # Naive form-scraping bots fill in every field they find — if this
    # comes back non-empty, the request is silently discarded by the
    # service. Name is innocuous ("website") so bots find it
    # plausible to fill. Real callers should always send an empty
    # string or omit the field.
    website = serializers.CharField(required=False, allow_blank=True, default="")

    # Friendly Captcha solution. Pairs with the honeypot for layered
    # protection — honeypot catches naive scrapers, FC catches
    # humans-with-scripts. Required at the service layer when
    # ``FRIENDLY_CAPTCHA_ENABLED=True``.
    frc_captcha_solution = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )


class PublicRegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField(required=False)
    member_id = serializers.CharField(required=False)
    # Nanoid string when present; null on the honeypot path.
    user_id = serializers.CharField(required=False, allow_null=True)
    coop_shares_created = serializers.IntegerField(required=False)
    consent_records_created = serializers.IntegerField(required=False)


class RegisterSendCodeRequestSerializer(serializers.Serializer):
    """Payload for ``POST /api/auth/register/send_code/`` — request an
    email-ownership verification code (step "confirm email" of the wizard)."""

    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    frc_captcha_solution = serializers.CharField(
        required=False, allow_blank=True, write_only=True
    )


class RegisterSendCodeResponseSerializer(serializers.Serializer):
    # Deliberately generic — always the same body whether or not a code was
    # actually sent (anti-enumeration).
    message = serializers.CharField()


class RegisterVerifyCodeRequestSerializer(serializers.Serializer):
    """Payload for ``POST /api/auth/register/verify_code/`` — submit the code
    that was emailed."""

    email = serializers.EmailField()
    code = serializers.CharField()


class RegisterVerifyCodeResponseSerializer(serializers.Serializer):
    verified = serializers.BooleanField()


# --------------------------------------------------------------------------- #
# Admin user management                                                       #
# --------------------------------------------------------------------------- #


class AdminUserRowSerializer(serializers.Serializer):
    """One row in ``GET /api/auth/admin/users/`` and the response payload of
    create / update / resend-invitation."""

    id = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    roles = serializers.ListField(child=serializers.CharField())
    user_language = serializers.CharField(allow_null=True)
    account_status = serializers.CharField()
    is_active = serializers.BooleanField()
    date_joined = serializers.DateTimeField(allow_null=True)
    last_login = serializers.DateTimeField(allow_null=True)
    activated_at = serializers.DateTimeField(allow_null=True)
    inactivated_at = serializers.DateTimeField(allow_null=True)
    invitation_expires_at = serializers.DateTimeField(allow_null=True)
    is_invitation_expired = serializers.BooleanField()
    reseller_id = serializers.CharField(allow_null=True)


class AdminUserCreateRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField(), required=False)
    user_language = serializers.ChoiceField(
        choices=LanguageChoices.choices, required=False, allow_null=True
    )
    reseller_id = serializers.CharField(required=False, allow_null=True)


class AdminUserUpdateRequestSerializer(serializers.Serializer):
    """All fields optional — PATCH semantics."""

    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    user_language = serializers.ChoiceField(
        choices=LanguageChoices.choices, required=False, allow_null=True
    )
    roles = serializers.ListField(child=serializers.CharField(), required=False)
    account_status = serializers.ChoiceField(
        choices=("active", "inactive"), required=False
    )
    # Handled by ``update_user_admin`` (unlink/relink the reseller);
    # null unlinks. Mirrors AdminUserCreateRequestSerializer.
    reseller_id = serializers.CharField(required=False, allow_null=True)
