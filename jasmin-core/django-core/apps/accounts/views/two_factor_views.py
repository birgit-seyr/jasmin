"""HTTP layer for two-factor auth.

Six endpoints under ``/api/auth/two-factor/``:

    GET    status/                         Read the user's current state.
    POST   enroll-start/                   Mint a pending TOTPDevice + return
                                           the QR provisioning URI.
    POST   enroll-confirm/                 Verify the first code, activate the
                                           device, return recovery codes.
    POST   verify/                         Second step of login — exchange
                                           (challenge_token, code) for a real
                                           access + refresh JWT.
    POST   disable/                        Tear down TOTP + recovery devices.
                                           Requires a valid current code.
    POST   recovery-codes/regenerate/      Mint a fresh batch of recovery
                                           codes. Requires a TOTP code (not a
                                           recovery code — that path would
                                           let a thief lock out the owner).

Errors raised by the service layer
(``apps.accounts.errors.TwoFactor*``) become the canonical JSON response
via ``core.exception_handler``. Views just orchestrate.
"""

from __future__ import annotations

import logging

from django.contrib.auth.signals import user_login_failed
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.shared.auth_cookies import set_tenant_refresh_cookie
from apps.shared.request_utils import client_ip
from core.serializers import ErrorResponseSerializer

from ..errors import AuthError, TenantMissing
from ..serializers import (
    LoginResponseSerializer,
    MessageResponseSerializer,
    TwoFactorCodeRequestSerializer,
    TwoFactorEnrolStartResponseSerializer,
    TwoFactorRecoveryCodesResponseSerializer,
    TwoFactorStatusResponseSerializer,
    TwoFactorVerifyRequestSerializer,
)
from ..services import issue_post_two_factor_tokens, two_factor_service
from .auth_views import _login_payload

logger = logging.getLogger("authentication")


def _resolve_enrolling_user(request):
    """The user to enrol. A logged-in caller (voluntary enrolment from the
    profile page) uses their session; a caller blocked at login by the
    role-mandated-2FA gate presents the ``enrolment_token`` issued on that
    path instead — so the gate can't deadlock (those users have no session
    yet). Raises ``AuthError`` when neither is present."""
    if getattr(request, "user", None) and request.user.is_authenticated:
        return request.user
    token = (request.data.get("enrolment_token") or "").strip()
    if not token:
        raise AuthError("Authentication or an enrolment token is required.")
    tenant = getattr(request, "tenant", None)
    if not tenant:
        raise TenantMissing("Tenant not found")
    return two_factor_service.consume_enrolment_token(
        enrolment=token, tenant_schema=tenant.schema_name
    )


# --------------------------------------------------------------------------- #
# Status                                                                      #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Read 2FA status for the current user",
    responses={
        200: TwoFactorStatusResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def two_factor_status_view(request):
    state = two_factor_service.status_for_user(request.user)
    return Response(
        {
            "enrolled": state.enrolled,
            "enrolled_at": state.enrolled_at,
            "recovery_codes_remaining": state.recovery_codes_remaining,
        }
    )


# --------------------------------------------------------------------------- #
# Enrolment                                                                   #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Begin 2FA enrolment — returns the provisioning URI / QR data",
    request=None,
    responses={
        200: TwoFactorEnrolStartResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def two_factor_enroll_start_view(request):
    # AllowAny + manual resolution so a user blocked at login by the
    # role-mandated-2FA gate (no session) can enrol via their enrolment_token;
    # a logged-in user still enrols via their session. See _resolve_enrolling_user.
    user = _resolve_enrolling_user(request)
    tenant = getattr(request, "tenant", None)
    if not tenant:
        raise TenantMissing("Tenant not found")
    issuer = f"Jasmin — {tenant.name}" if tenant.name else "Jasmin"
    start = two_factor_service.start_enrollment(user=user, issuer=issuer)
    return Response(
        {"secret": start.secret, "provisioning_uri": start.provisioning_uri}
    )


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Confirm enrolment by submitting the first TOTP code",
    request=TwoFactorCodeRequestSerializer,
    responses={
        200: TwoFactorRecoveryCodesResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def two_factor_enroll_confirm_view(request):
    # AllowAny + manual resolution — same enrolment-token path as enroll-start.
    user = _resolve_enrolling_user(request)
    # is_valid gates ``code``; the enrolment_token resolved above is an
    # undeclared key, so it is read from request.data (not validated_data).
    serializer = TwoFactorCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    code = serializer.validated_data["code"].strip()
    result = two_factor_service.confirm_enrollment(user=user, code=code)
    return Response({"recovery_codes": result.recovery_codes})


# --------------------------------------------------------------------------- #
# Verify (login second step)                                                  #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Exchange a login challenge token + code for real JWTs",
    request=TwoFactorVerifyRequestSerializer,
    responses={
        200: LoginResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def two_factor_verify_view(request):
    serializer = TwoFactorVerifyRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    challenge_token = serializer.validated_data["challenge_token"].strip()
    code = serializer.validated_data["code"].strip()
    tenant = getattr(request, "tenant", None)
    if not tenant:
        raise TenantMissing("Tenant not found")

    user = None
    try:
        user = two_factor_service.consume_challenge_token(
            challenge=challenge_token, tenant_schema=tenant.schema_name
        )
        two_factor_service.verify_code(user=user, code=code)
    except AuthError as exc:
        logger.warning(
            "2fa.verify_failed tenant=%s ip=%s reason=%s",
            tenant.schema_name,
            client_ip(request),
            exc.message,
        )
        # Feed django-axes so repeated bad 2FA codes lock the account exactly
        # like login failures do — 2FA verify bypasses ``authenticate()``, so
        # axes never sees these otherwise. Only when the challenge resolved a
        # user: a bad/expired challenge token isn't a code-guessing attempt.
        if user is not None:
            user_login_failed.send(
                sender=user.__class__,
                credentials={"username": getattr(user, "email", "")},
                request=request,
            )
        raise

    result = issue_post_two_factor_tokens(user=user, tenant=tenant)
    logger.info(
        "login.success_2fa user=%s tenant=%s ip=%s",
        user.email,
        tenant.schema_name,
        client_ip(request),
    )
    response = Response(
        _login_payload(result=result, tenant=tenant),
        status=status.HTTP_200_OK,
    )
    set_tenant_refresh_cookie(response, result.refresh)
    return response


# Login throttle scope so /verify/ shares the same per-IP bucket as
# /login/ — stops the second step from being brute-forced independently.
two_factor_verify_view.cls.throttle_scope = "login"


# --------------------------------------------------------------------------- #
# Disable                                                                     #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Disable 2FA (requires a current TOTP or recovery code)",
    request=TwoFactorCodeRequestSerializer,
    responses={
        200: MessageResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def two_factor_disable_view(request):
    serializer = TwoFactorCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    code = serializer.validated_data["code"].strip()
    two_factor_service.disable(user=request.user, code=code)
    return Response({"message": "Two-factor auth disabled."})


# --------------------------------------------------------------------------- #
# Regenerate recovery codes                                                   #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["Auth — Two-factor"],
    summary="Mint a fresh batch of recovery codes (requires TOTP code)",
    request=TwoFactorCodeRequestSerializer,
    responses={
        200: TwoFactorRecoveryCodesResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def two_factor_regenerate_recovery_codes_view(request):
    serializer = TwoFactorCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    code = serializer.validated_data["code"].strip()
    codes = two_factor_service.regenerate_recovery_codes(user=request.user, code=code)
    return Response({"recovery_codes": codes})
