"""HTTP layer for the accounts app. Thin views — business logic lives
in ``apps/accounts/services/``.

Errors raised by services (``apps.accounts.errors``) are translated to
HTTP responses by ``core.exception_handler``. Views only ``try/except``
when they need to enrich a log line with request-scoped context
(IP, tenant, email) that the handler does not have.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from drf_spectacular.utils import (
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.shared.auth_cookies import (
    clear_tenant_refresh_cookie,
    get_tenant_refresh_token,
    set_tenant_refresh_cookie,
)
from apps.shared.deferred_email import schedule_deferred_email
from apps.shared.request_utils import client_ip
from core.serializers import ErrorResponseSerializer

from ..errors import (
    AuthError,
    InvalidCredentials,
    InvitationInvalid,
    ProfilePermissionDenied,
    RefreshTokenMissing,
    RegistrationCodeInvalid,
    RegistrationError,
    TenantMissing,
)
from ..models import JasminUser
from ..serializers import (
    InvitationAcceptRequestSerializer,
    InvitationVerifyResponseSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    MessageResponseSerializer,
    PasswordResetConfirmRequestSerializer,
    PasswordResetRequestRequestSerializer,
    PublicRegisterRequestSerializer,
    PublicRegisterResponseSerializer,
    RefreshResponseSerializer,
    RegisterSendCodeRequestSerializer,
    RegisterSendCodeResponseSerializer,
    RegisterVerifyCodeRequestSerializer,
    RegisterVerifyCodeResponseSerializer,
    StepUpRequestSerializer,
    StepUpResponseSerializer,
    TwoFactorChallengeResponseSerializer,
    UserProfileResponseSerializer,
    UserProfileUpdateRequestSerializer,
)
from ..services import (
    TwoFactorChallenge,
    authenticate_for_tenant,
    blacklist_refresh,
    email_verification_service,
    refresh_access_token,
    register_public_applicant,
    revoke_all_sessions,
    update_user_profile,
    verify_and_issue_step_up_token,
    verify_captcha,
)

logger = logging.getLogger("authentication")


# --------------------------------------------------------------------------- #
# Login / refresh / logout                                                     #
# --------------------------------------------------------------------------- #


@extend_schema(
    summary="User login",
    request=LoginRequestSerializer,
    responses={
        200: OpenApiResponse(
            # oneOf union so the generated client carries BOTH shapes
            # instead of the challenge living only in prose.
            response=PolymorphicProxySerializer(
                component_name="LoginOrChallengeResponse",
                serializers=[
                    LoginResponseSerializer,
                    TwoFactorChallengeResponseSerializer,
                ],
                resource_type_field_name=None,
            ),
            description=(
                "Two response shapes share status 200: full ``LoginResponse`` "
                "when 2FA is OFF or unconfigured, and "
                "``TwoFactorChallengeResponse`` ({requires_2fa: true, "
                "challenge_token}) when the user has an active TOTP device. "
                "Frontend must branch on ``requires_2fa``."
            ),
        ),
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def user_login_view(request):
    serializer = LoginRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    email = data["email"]
    password = data["password"]
    tenant = getattr(request, "tenant", None)
    if not tenant:
        raise TenantMissing("Tenant not found")

    # Friendly Captcha — no-op when FRIENDLY_CAPTCHA_ENABLED is off.
    verify_captcha(data.get("frc_captcha_solution"), scope="login")

    try:
        result = authenticate_for_tenant(
            request=request, email=email, password=password, tenant=tenant
        )
    except AuthError as exc:
        # Security-relevant logging needs request-scoped context (IP, tenant,
        # email) that the global handler doesn't have. Log here, then re-raise
        # so the handler builds the canonical response.
        logger.warning(
            "login.blocked user=%s tenant=%s ip=%s reason=%s",
            email,
            tenant.schema_name,
            client_ip(request),
            exc.message,
        )
        raise

    if isinstance(result, TwoFactorChallenge):
        logger.info(
            "login.challenge_issued user=%s tenant=%s ip=%s",
            result.user.email,
            tenant.schema_name,
            client_ip(request),
        )
        # No refresh cookie set — the user is NOT yet logged in.
        return Response(
            {
                "requires_2fa": True,
                "challenge_token": result.challenge_token,
            },
            status=status.HTTP_200_OK,
        )

    user = result.user
    logger.info(
        "login.success user=%s tenant=%s ip=%s",
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


def _login_payload(*, result, tenant) -> dict:
    """Shared by the login view and the post-2FA-verify view."""
    user = result.user
    return {
        "access": result.access,
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "user_language": getattr(user, "user_language", "en"),
            "roles": user.roles or ["member"],
            "permissions": result.permissions,
            "member_id": result.member_id,
            "reseller_id": result.reseller_id,
        },
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "schema_name": tenant.schema_name,
        },
    }


user_login_view.cls.throttle_scope = "login"


@extend_schema(
    summary="Refresh JWT access token",
    request=None,
    responses={
        200: RefreshResponseSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def user_token_refresh_view(request):
    refresh_token = get_tenant_refresh_token(request)
    if not refresh_token:
        raise RefreshTokenMissing("Refresh token is required")
    tenant = getattr(request, "tenant", None)
    schema_name = tenant.schema_name if tenant else None

    try:
        result = refresh_access_token(
            refresh_token=refresh_token,
            tenant_schema=schema_name,
            tenant_name=tenant.name if tenant else None,
        )
    except AuthError as exc:
        logger.warning(
            "refresh.failed reason=%s ip=%s", exc.message, client_ip(request)
        )
        raise

    response_data = {"access": result["access"]}
    if tenant:
        response_data["tenant"] = {
            "id": tenant.id,
            "name": tenant.name,
            "schema_name": tenant.schema_name,
        }
    response = Response(response_data, status=status.HTTP_200_OK)
    if result["refresh"]:
        set_tenant_refresh_cookie(response, result["refresh"])
    return response


@extend_schema(
    summary="User logout",
    request=None,
    responses={200: MessageResponseSerializer},
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def user_logout_view(request):
    user_pk = request.user.pk if request.user.is_authenticated else "-"
    refresh_token = get_tenant_refresh_token(request)
    response = Response(
        {"message": "Successfully logged out"}, status=status.HTTP_200_OK
    )
    clear_tenant_refresh_cookie(response)
    if refresh_token:
        blacklist_refresh(refresh_token)
    logger.info("logout.success user=%s", user_pk)
    return response


@extend_schema(
    summary="Log out of all sessions (this device and every other)",
    description=(
        "Revokes every refresh token for the authenticated user — this browser "
        "and every other device/session. Use after a suspected compromise. "
        "Already-issued access tokens keep working until they expire "
        "(short-lived); no new session can be minted from an old refresh token."
    ),
    request=None,
    responses={200: MessageResponseSerializer, 401: ErrorResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_logout_all_view(request):
    revoke_all_sessions(request.user)
    response = Response(
        {"message": "Logged out of all sessions"}, status=status.HTTP_200_OK
    )
    # Clear THIS browser's cookie too so it doesn't keep presenting a now-dead
    # refresh token on the next request.
    clear_tenant_refresh_cookie(response)
    logger.info("logout_all.success user=%s", request.user.pk)
    return response


# --------------------------------------------------------------------------- #
# Profile                                                                      #
# --------------------------------------------------------------------------- #


@extend_schema(
    summary="Update user profile",
    request=UserProfileUpdateRequestSerializer,
    responses={
        200: UserProfileResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def user_profile_update_view(request, user_id):
    if request.user.id != user_id:
        raise ProfilePermissionDenied("Permission denied")
    user = request.user
    serializer = UserProfileUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    fields = update_user_profile(user=user, data=serializer.validated_data)
    logger.info(
        "profile.updated user=%s ip=%s fields=%s",
        user.email,
        client_ip(request),
        fields,
    )
    return Response(
        {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "user_language": getattr(user, "user_language", "en"),
        },
        status=status.HTTP_200_OK,
    )


# --------------------------------------------------------------------------- #
# Invitation accept / verify                                                   #
# --------------------------------------------------------------------------- #


@extend_schema(
    summary="Pre-flight: verify an invitation token",
    responses={
        200: InvitationVerifyResponseSerializer,
        404: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def invitation_verify_view(request, token):
    from apps.shared.invitations import get_invitation

    invitation = get_invitation(token)
    if invitation is None:
        raise InvitationInvalid("This invitation link is invalid or expired.")
    tenant = getattr(request, "tenant", None)
    return Response(
        {
            "email": invitation.email,
            "first_name": invitation.user.first_name if invitation.user else "",
            "tenant_name": getattr(tenant, "name", "") or "",
        }
    )


@extend_schema(
    summary="Accept an invitation: set password and activate the account",
    request=InvitationAcceptRequestSerializer,
    responses={
        200: MessageResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def invitation_accept_view(request):
    from apps.shared.invitations import accept_invitation

    serializer = InvitationAcceptRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Django's ValidationError raised by accept_invitation() is translated
    # to a 400 by core.exception_handler.
    accept_invitation(
        token=serializer.validated_data["token"],
        password=serializer.validated_data["password"],
    )
    return Response({"message": "Password set. You can now sign in."})


# Both invitation endpoints are ``AllowAny`` and hit the DB with a
# caller-supplied token — throttle the grind. ScopedRateThrottle reads
# ``throttle_scope`` off the wrapped view class (see the login view for
# the same pattern).
invitation_verify_view.cls.throttle_scope = "invitation"
invitation_accept_view.cls.throttle_scope = "invitation"


# --------------------------------------------------------------------------- #
# Password reset (forgot-password flow)                                       #
# --------------------------------------------------------------------------- #


@extend_schema(
    summary="Request a password-reset email",
    description=(
        "Sends a single-use, time-limited reset link to the address if it "
        "matches an active account. Always returns 200 to prevent "
        "user-enumeration."
    ),
    request=PasswordResetRequestRequestSerializer,
    responses={
        200: MessageResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def password_reset_request_view(request):
    from ..services import request_password_reset

    serializer = PasswordResetRequestRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # Friendly Captcha — gated behind a flag, no-op when disabled.
    # Placed BEFORE the email lookup so a bot can't even confirm the
    # endpoint accepted its payload without solving the challenge.
    verify_captcha(
        data.get("frc_captcha_solution"),
        scope="password_reset_request",
    )
    email = data["email"].strip()
    request_password_reset(email=email)
    # Same response on hit and miss — do not leak which addresses exist.
    return Response(
        {
            "message": (
                "If an account exists for that email, a reset link is on its way."
            )
        }
    )


# DRF reads ``throttle_scope`` off the CBV class, not the function:
# ``@api_view`` builds a ``WrappedAPIView`` subclass of ``APIView`` and
# copies a fixed set of attributes from the function at decoration
# time — anything set on the function AFTER decoration is invisible to
# DRF's dispatch. Setting ``view_fn.cls.throttle_scope = ...`` lands
# on the WrappedAPIView class, which is what ``ScopedRateThrottle``
# reads via ``getattr(view_instance, 'throttle_scope', None)``.
password_reset_request_view.cls.throttle_scope = "password_reset"


@extend_schema(
    summary="Confirm a password reset",
    request=PasswordResetConfirmRequestSerializer,
    responses={
        200: MessageResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def password_reset_confirm_view(request):
    from ..services import confirm_password_reset

    serializer = PasswordResetConfirmRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    verify_captcha(
        data.get("frc_captcha_solution"),
        scope="password_reset_confirm",
    )
    confirm_password_reset(
        uid=data["uid"], token=data["token"], password=data["password"]
    )
    return Response({"message": "Password updated. You can now sign in."})


password_reset_confirm_view.cls.throttle_scope = "password_reset"


# --------------------------------------------------------------------------- #
# Step-up authentication                                                       #
# --------------------------------------------------------------------------- #


@extend_schema(
    summary="Step-up authentication — issue a fresh access token for sudo mode",
    description=(
        "Re-verifies the caller's password (and TOTP code when "
        "``STEP_UP_REQUIRES_TOTP`` is on) and returns a new access "
        "token carrying ``step_up_verified_at``. The frontend swaps "
        "the access token in and retries the original destructive "
        "request. The new token's TTL for step-up purposes is "
        "``STEP_UP_TTL_SECONDS`` (default 300); the JWT itself still "
        "expires at the normal access-token lifetime."
    ),
    request=StepUpRequestSerializer,
    responses={
        200: StepUpResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def step_up_view(request: Request) -> Response:
    """Issue a fresh access token with the step-up claim set."""
    serializer = StepUpRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    password = serializer.validated_data["password"]
    totp_code = serializer.validated_data.get("totp_code") or None
    payload = getattr(request.auth, "payload", None) if request.auth else None
    try:
        access = verify_and_issue_step_up_token(
            user=request.user,
            password=password,
            totp_code=totp_code,
            current_access_payload=payload,
        )
    except InvalidCredentials:
        # Step-up deliberately bypasses ``authenticate()`` (it doesn't want
        # the login flow's is_active / 2FA forks), so django-axes never sees
        # these failures. Feed the same signal axes hooks for login so a
        # wrong-password grind locks the (username, ip) pair exactly as
        # repeated login failures do — closing the lockout-bypass hole.
        user_login_failed.send(
            sender=request.user.__class__,
            credentials={"username": getattr(request.user, "email", "")},
            request=request,
        )
        raise
    return Response({"access": access, "ttl_seconds": settings.STEP_UP_TTL_SECONDS})


# Dedicated strict scope (keyed per user, since the request is
# authenticated) — NOT the generous ``login`` bucket. Re-validating a
# password is the same brute-force surface as logging in; pairing the
# tighter rate with the axes signal above means wrong passwords both
# throttle AND count toward account lockout.
step_up_view.cls.throttle_scope = "step_up"


# --------------------------------------------------------------------------- #
# Public self-registration                                                     #
# --------------------------------------------------------------------------- #


def _reject_public_schema(request) -> object:
    """Guard shared by the registration endpoints: registration only makes
    sense on a tenant host, never the public/platform schema."""
    tenant = getattr(request, "tenant", None)
    if tenant is None or getattr(tenant, "schema_name", None) == "public":
        raise RegistrationError(
            "Registration is not available on this host.",
            code="registration.host_disabled",
        )
    return tenant


@extend_schema(
    summary="Request a registration email-verification code",
    description=(
        "Step 'confirm email' of the public registration wizard: emails a "
        "short numeric code to prove the applicant controls the address. "
        "Always returns the same generic body (anti-enumeration); a code is "
        "only actually sent when the address isn't already an account."
    ),
    request=RegisterSendCodeRequestSerializer,
    responses={
        200: RegisterSendCodeResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register_send_code_view(request):
    tenant = _reject_public_schema(request)
    serializer = RegisterSendCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Captcha gates the FIRST anonymous touch of the wizard; the later
    # verify_code + register steps are gated by the code / verified marker.
    verify_captcha(request.data.get("frc_captcha_solution"), scope="register")
    email = serializer.validated_data["email"]
    first_name = serializer.validated_data.get("first_name") or ""
    # Anti-enumeration: identical response whether or not we send. Skip the
    # send when the address already has an account (an existing user shouldn't
    # get a "verify your new registration" code they never asked for).
    if not JasminUser.objects.filter(email__iexact=email).exists():
        code = email_verification_service.generate_and_store_code(email)
        schedule_deferred_email(
            slug="accounts.email_verification_code",
            to_emails=[email],
            context={
                "tenant_name": tenant.name,
                "first_name": first_name,
                "code": code,
            },
            related_object_type="registration",
            related_object_id=email,
            logger=logger,
            log_error_event="registration.code_email_failed",
            log_not_sent_event="registration.code_email_not_sent",
            log_ref=f"email={email}",
        )
    return Response(
        {"message": "If the address is valid, a verification code has been sent."},
        status=status.HTTP_200_OK,
    )


register_send_code_view.cls.throttle_scope = "register"


@extend_schema(
    summary="Verify a registration email-verification code",
    request=RegisterVerifyCodeRequestSerializer,
    responses={
        200: RegisterVerifyCodeResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register_verify_code_view(request):
    _reject_public_schema(request)
    serializer = RegisterVerifyCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data["email"]
    if not email_verification_service.verify_code(
        email, serializer.validated_data["code"]
    ):
        raise RegistrationCodeInvalid(
            "The verification code is invalid or has expired."
        )
    return Response({"verified": True}, status=status.HTTP_200_OK)


register_verify_code_view.cls.throttle_scope = "register"


@extend_schema(
    summary="Public self-registration with membership application",
    description=(
        "Final step of the public registration wizard. Requires the email to "
        "have been verified first (``register/verify_code/``). Creates a "
        "JasminUser WITHOUT a usable password plus a Member row "
        "(``admin_confirmed=False``) and emails an ``accounts.invitation`` "
        "set-password link. Office confirms the member separately."
    ),
    request=PublicRegisterRequestSerializer,
    responses={
        201: PublicRegisterResponseSerializer,
        400: ErrorResponseSerializer,
        429: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def public_register_view(request):
    # See ``settings.REST_FRAMEWORK.DEFAULT_THROTTLE_RATES.register`` +
    # the ``.cls.throttle_scope = ...`` assignment below the def.
    tenant = _reject_public_schema(request)
    # No captcha here: reaching this endpoint requires a verified-email
    # marker, which is only minted after ``send_code`` (captcha-gated) +
    # ``verify_code``. The email-verification requirement is enforced inside
    # ``register_public_applicant``. The honeypot check runs there too.
    serializer = PublicRegisterRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Pass VALIDATED data (not raw request.data) so field types are coerced —
    # e.g. a string ``is_trial: "false"`` becomes a real bool instead of the
    # truthy string that would flip a full membership into a trial.
    result = register_public_applicant(
        data=serializer.validated_data,
        tenant=tenant,
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    return Response(result, status=status.HTTP_201_CREATED)


public_register_view.cls.throttle_scope = "register"


# --------------------------------------------------------------------------- #
# Admin: list / create / update / resend                                       #
# --------------------------------------------------------------------------- #
# These endpoints now live in ``apps.accounts.viewsets.AdminUserViewSet`` —
# grouped on the standard /admin/users/ resource via DefaultRouter.
