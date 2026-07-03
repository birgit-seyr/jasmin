"""ViewSets for the accounts app.

Kept separate from ``views.py`` (which still holds the auth-flow RPC
endpoints: login, refresh, logout, password reset, invitation accept,
self-register). The endpoints here all operate on the same "tenant
user" resource and benefit from the standard ViewSet shape — including
the ``RolePermissionsMixin`` read/write split.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.authz.permissions import IsAdmin, RolePermissionsMixin
from core.serializers import ErrorResponseSerializer

from .errors import UserNotFound, UserNotPendingInvitation
from .models import JasminUser
from .permissions import RequiresStepUp
from .serializers import (
    AdminUserCreateRequestSerializer,
    AdminUserRowSerializer,
    AdminUserUpdateRequestSerializer,
)
from .services import (
    create_user_with_invite,
    list_active_users,
    serialize_user_row,
    update_user_admin,
)


class AdminUserViewSet(RolePermissionsMixin, ViewSet):
    """Admin endpoints for managing tenant users.

    All operations require the ``admin`` role. Wired into ``/admin/users/``
    by ``apps.accounts.urls`` via ``DefaultRouter``.
    """

    read_permission = IsAdmin
    write_permission = IsAdmin

    def get_permissions(self):
        """Step-up-gate role grants. ``create`` / ``partial_update`` route into
        ``create_user_with_invite`` / ``update_user_admin``, which can assign
        ANY role (incl. ``admin`` / ``office``) — a privilege escalation a
        stolen session token alone must not be able to fire without a fresh
        password re-confirmation. Gate whenever the payload carries ``roles``
        (mirrors the super-admin ``TenantManagementViewSet.update_user_roles``
        gate); edits that leave roles untouched (name, contact, …) pass through
        unprompted. Inspected on ``request.data`` rather than via
        ``requires_step_up_for_fields`` because this is a plain ``ViewSet`` —
        it never calls ``check_object_permissions``, so an object-level gate
        would silently never fire.
        """
        perms = super().get_permissions()
        if self.action in {"create", "partial_update"} and "roles" in (
            getattr(self.request, "data", None) or {}
        ):
            perms.append(RequiresStepUp())
        return perms

    @extend_schema(
        summary="List tenant users (admin)",
        responses={
            200: AdminUserRowSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request) -> Response:
        return Response(list_active_users())

    @extend_schema(
        summary="Create a tenant user and send invitation email (admin)",
        request=AdminUserCreateRequestSerializer,
        responses={
            201: AdminUserRowSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request) -> Response:
        serializer = AdminUserCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Pass raw data: the service owns the business rules (role-combination
        # checks, member-role guard, reseller/customer coupling) and reads by
        # key; validated_data offers no benefit here.
        payload = create_user_with_invite(data=request.data, created_by=request.user)
        return Response(payload, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Update a tenant user (admin)",
        request=AdminUserUpdateRequestSerializer,
        responses={
            200: AdminUserRowSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        try:
            user = JasminUser.objects.get(id=pk)
        except JasminUser.DoesNotExist as exc:
            raise UserNotFound("User not found") from exc
        serializer = AdminUserUpdateRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # validated_data preserves the absent-vs-null membership the service
        # relies on (absent key → field untouched; null → unlink).
        payload = update_user_admin(
            user=user, data=serializer.validated_data, actor=request.user
        )
        return Response(payload)

    @extend_schema(
        summary="Re-send invitation email to a user still in pending_invitation",
        request=None,
        responses={
            200: AdminUserRowSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="resend-invitation")
    def resend_invitation(self, request: Request, pk: str | None = None) -> Response:
        from apps.shared.invitations import resend_invitation

        try:
            user = JasminUser.objects.get(id=pk)
        except JasminUser.DoesNotExist as exc:
            raise UserNotFound("User not found") from exc
        if user.account_status != "pending_invitation":
            raise UserNotPendingInvitation("User is not waiting for an invitation.")
        resend_invitation(user=user, created_by=request.user)
        return Response(serialize_user_row(user))
