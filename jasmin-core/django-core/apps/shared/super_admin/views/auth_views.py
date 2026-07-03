from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.conf import settings
from django_tenants.utils import schema_context
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.shared.auth_cookies import (
    clear_super_admin_refresh_cookie,
    get_super_admin_refresh_token,
    set_super_admin_refresh_cookie,
)
from apps.shared.request_utils import client_ip
from apps.shared.tenants.models import Tenant
from core.serializers import ErrorResponseSerializer

from ..errors import (
    NotSuperAdminToken,
    RefreshTokenInvalid,
    RefreshTokenMissing,
    SuperAdminAccountDisabled,
    SuperAdminAccountLocked,
    SuperAdminInvalidCredentials,
    SuperAdminMissingCredentials,
)
from ..lockout import is_locked, register_failure, reset_failures
from ..models import SuperAdmin, SuperAdminBlacklistedToken
from ..permissions import IsSuperAdmin
from ..serializers import SessionTenantSerializer, SessionUserSerializer
from .authentication import SuperAdminJWTAuthentication

logger = logging.getLogger("super_admin")

# Claims preserved across an access-token rotation. Mirrors the
# ``_CARRY_CLAIMS`` in ``apps/accounts/services/step_up_service.py``
# — the super-admin step-up endpoint keeps the public-schema set
# (``is_super_admin`` / ``schema`` / ``user_role`` / identity claims)
# because they're what ``IsSuperAdmin`` and downstream views read.
_STEP_UP_CARRY_CLAIMS = (
    "user_id",
    "email",
    "is_super_admin",
    "schema",
    "user_role",
)


class SuperAdminRefreshToken(RefreshToken):
    """RefreshToken variant that uses our own public-schema blacklist.

    The simplejwt blacklist tables live in tenant schemas (their FK to
    AUTH_USER_MODEL = accounts.JasminUser is tenant-scoped), so we ship a
    minimal SuperAdminBlacklistedToken model and check against that.
    """

    def check_blacklist(self) -> None:  # noqa: D401  (override)
        with schema_context("public"):
            jti = self.payload.get("jti")
            if jti and SuperAdminBlacklistedToken.objects.filter(jti=jti).exists():
                from rest_framework_simplejwt.exceptions import TokenError

                raise TokenError("Token is blacklisted")


def _blacklist_super_admin_token(payload: dict, *, reason: str) -> None:
    """Insert the token's JTI into the public-schema blacklist."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    expires_at = datetime.fromtimestamp(int(exp), tz=UTC)
    with schema_context("public"):
        SuperAdminBlacklistedToken.objects.get_or_create(
            jti=jti,
            defaults={"expires_at": expires_at, "reason": reason},
        )


def _build_super_admin_session_response(user: SuperAdmin) -> Response:
    """Issue a super-admin session: access token in body + refresh cookie."""
    claims = {
        "user_id": user.id,
        "email": user.email,
        "is_super_admin": True,
        "schema": "public",
        "user_role": "super_admin",
    }

    refresh = SuperAdminRefreshToken()
    for key, value in claims.items():
        refresh[key] = value

    access = AccessToken()
    for key, value in claims.items():
        access[key] = value

    # Prefetch domains in one query instead of an exists()+first() pair per
    # tenant (mirrors the already-correct TenantManagementViewSet.list).
    tenants = Tenant.objects.prefetch_related("domains")
    tenant_list = []
    for tenant in tenants:
        domains = list(tenant.domains.all())
        tenant_list.append(
            {
                "id": tenant.id,
                "name": tenant.name,
                "schema_name": tenant.schema_name,
                "domain": domains[0].domain if domains else None,
            }
        )

    response = Response(
        {
            "access": str(access),
            "user": {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "permissions": ["super_admin"],
            },
            "tenants": tenant_list,
            "is_super_admin": True,
        },
        status=status.HTTP_200_OK,
    )
    set_super_admin_refresh_cookie(response, str(refresh))
    return response


@extend_schema(
    tags=["super-admin"],
    summary="Super admin login",
    request=inline_serializer(
        name="SuperAdminLoginRequest",
        fields={
            "email": drf_serializers.EmailField(),
            "password": drf_serializers.CharField(),
        },
    ),
    responses={
        200: inline_serializer(
            name="SuperAdminLoginResponse",
            fields={
                "access": drf_serializers.CharField(),
                "user": SessionUserSerializer(),
                "tenants": SessionTenantSerializer(many=True),
                "is_super_admin": drf_serializers.BooleanField(),
            },
        ),
        400: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def super_admin_login_view(request: Request) -> Response:
    """Authenticate super admin user and return JWT tokens."""
    email: str | None = request.data.get("email")
    password: str | None = request.data.get("password")

    if not email or not password:
        raise SuperAdminMissingCredentials("Email and password are required")

    # Per-account brute-force lock (checked before any DB/password work so a
    # locked account is refused regardless of source IP — the per-IP throttle
    # alone can't stop a distributed guessing attack on this credential).
    if is_locked(email):
        logger.warning(
            "superadmin.login.locked user=%s ip=%s reason=too_many_failures",
            email,
            client_ip(request),
        )
        raise SuperAdminAccountLocked(
            "Too many failed attempts; this account is temporarily locked"
        )

    with schema_context("public"):
        try:
            user = SuperAdmin.objects.get(email=email)
        except SuperAdmin.DoesNotExist:
            register_failure(email)
            logger.warning(
                "superadmin.login.failed user=%s ip=%s reason=user_not_found",
                email,
                client_ip(request),
            )
            raise SuperAdminInvalidCredentials("Invalid credentials") from None

        if not user.check_password(password):
            register_failure(email)
            logger.warning(
                "superadmin.login.failed user=%s ip=%s reason=invalid_password",
                email,
                client_ip(request),
            )
            raise SuperAdminInvalidCredentials("Invalid credentials")

        if not user.is_active:
            logger.warning(
                "superadmin.login.blocked user=%s ip=%s reason=inactive",
                email,
                client_ip(request),
            )
            raise SuperAdminAccountDisabled("Account is disabled")

        reset_failures(email)
        logger.info(
            "superadmin.login.success user=%s ip=%s",
            user.email,
            client_ip(request),
        )
        return _build_super_admin_session_response(user)


# DRF reads ``throttle_scope`` off the wrapped view CLASS, not the function
# (see the tenant login view for the same idiom). Anti-brute-force on the
# highest-privilege login — keyed by IP (unauthenticated).
super_admin_login_view.cls.throttle_scope = "super_admin_login"


@extend_schema(
    tags=["super-admin"],
    summary="Super admin logout",
    description=(
        "No request body — the refresh token travels in the HttpOnly "
        "cookie, never in the payload."
    ),
    request=None,
    responses={
        200: inline_serializer(
            name="SuperAdminLogoutResponse",
            fields={"message": drf_serializers.CharField()},
        ),
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def super_admin_logout_view(request: Request) -> Response:
    """Logout super admin by blacklisting the refresh token and clearing cookie.

    AllowAny on purpose: if the access token has expired, the user must still
    be able to invalidate the refresh token. The refresh token is read from
    the HttpOnly cookie.
    """
    refresh_token: str | None = get_super_admin_refresh_token(request)

    response = Response(
        {"message": "Successfully logged out"}, status=status.HTTP_200_OK
    )
    clear_super_admin_refresh_cookie(response)

    if not refresh_token:
        return response

    try:
        token = SuperAdminRefreshToken(refresh_token)
    except TokenError:
        logger.warning(
            "superadmin.logout.failed ip=%s reason=invalid_token",
            client_ip(request),
        )
        return response

    _blacklist_super_admin_token(token.payload, reason="logout")

    logger.info(
        "superadmin.logout.success user=%s ip=%s",
        token.payload.get("email", "-"),
        client_ip(request),
    )
    return response


@extend_schema(
    tags=["super-admin"],
    summary="Refresh super admin JWT access token",
    description=(
        "No request body — the refresh token travels in the HttpOnly "
        "cookie, never in the payload."
    ),
    request=None,
    responses={
        200: inline_serializer(
            name="SuperAdminRefreshResponse",
            fields={
                "access": drf_serializers.CharField(),
                "is_super_admin": drf_serializers.BooleanField(),
                "schema": drf_serializers.CharField(),
            },
        ),
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def super_admin_token_refresh_view(request: Request) -> Response:
    """Refresh super admin JWT access token (cookie-based, with rotation)."""
    refresh_token: str | None = get_super_admin_refresh_token(request)
    if not refresh_token:
        raise RefreshTokenMissing("Refresh token is required")

    try:
        token = SuperAdminRefreshToken(refresh_token)
    except TokenError:
        logger.warning(
            "superadmin.refresh.failed ip=%s reason=invalid_or_expired",
            client_ip(request),
        )
        raise RefreshTokenInvalid("Invalid or expired refresh token") from None

    if not token.get("is_super_admin", False):
        logger.warning(
            "superadmin.refresh.failed ip=%s reason=not_superadmin_token",
            client_ip(request),
        )
        raise NotSuperAdminToken("Invalid token: not a super admin token")

    # Re-mint off the refresh token's identity, NOT just its claims: a
    # super-admin deactivated or deleted after login must not be able to
    # renew their session. Trusting only the ``is_super_admin`` claim let a
    # disabled account keep full platform access for the refresh lifetime.
    with schema_context("public"):
        account = SuperAdmin.objects.filter(id=token.get("user_id")).first()
    if account is None or not account.is_active:
        logger.warning(
            "superadmin.refresh.failed ip=%s reason=account_missing_or_inactive",
            client_ip(request),
        )
        raise RefreshTokenInvalid("Invalid or expired refresh token")

    access_token = token.access_token
    access_token["is_super_admin"] = True
    access_token["schema"] = "public"
    access_token["user_role"] = "super_admin"

    # Refresh-token rotation: blacklist the old jti, then mint a new refresh.
    new_refresh = None
    if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
        if settings.SIMPLE_JWT.get("BLACKLIST_AFTER_ROTATION"):
            _blacklist_super_admin_token(token.payload, reason="rotation")
        token.set_jti()
        token.set_exp()
        token.set_iat()
        new_refresh = token

    response = Response(
        {"access": str(access_token), "is_super_admin": True, "schema": "public"},
        status=status.HTTP_200_OK,
    )
    if new_refresh is not None:
        set_super_admin_refresh_cookie(response, str(new_refresh))
    return response


# --------------------------------------------------------------------------- #
# Step-up authentication (super-admin variant)                                #
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["super-admin"],
    summary="Step-up authentication for super-admin destructive endpoints",
    description=(
        "Re-verifies the super-admin's password and returns a new access "
        "token carrying ``step_up_verified_at``. Mirrors the tenant-side "
        "``/api/auth/step-up/`` endpoint; the two are siblings because "
        "super-admin tokens are minted by a separate JWT path and the "
        "tenant endpoint runs under tenant authentication. The frontend "
        "interceptor calls whichever endpoint matches the current host."
    ),
    request=inline_serializer(
        name="SuperAdminStepUpRequest",
        fields={
            "password": drf_serializers.CharField(),
        },
    ),
    responses={
        200: inline_serializer(
            name="SuperAdminStepUpResponse",
            fields={
                "access": drf_serializers.CharField(),
                "ttl_seconds": drf_serializers.IntegerField(),
            },
        ),
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def super_admin_step_up_view(request: Request) -> Response:
    """Issue a fresh super-admin access token with the step-up claim."""
    import time

    from apps.accounts.errors import InvalidCredentials

    user = request.user
    password = request.data.get("password") or ""
    if not password or not user.check_password(password):
        logger.warning(
            "superadmin.step_up.verify_failed user=%s",
            getattr(user, "email", "-"),
        )
        raise InvalidCredentials("Incorrect password.")

    current_payload = (
        getattr(request.auth, "payload", None) if request.auth else None
    ) or {}
    access = AccessToken()
    for claim in _STEP_UP_CARRY_CLAIMS:
        if claim in current_payload:
            access[claim] = current_payload[claim]
    access["step_up_verified_at"] = int(time.time())

    logger.info(
        "superadmin.step_up.verified user=%s ttl=%ss",
        getattr(user, "email", "-"),
        settings.STEP_UP_TTL_SECONDS,
    )
    return Response(
        {"access": str(access), "ttl_seconds": settings.STEP_UP_TTL_SECONDS},
        status=status.HTTP_200_OK,
    )


# Re-confirming the super-admin password is the same brute-force surface as
# logging in — share the strict scope (keyed by super-admin pk here, since
# the request is authenticated).
super_admin_step_up_view.cls.throttle_scope = "super_admin_login"
