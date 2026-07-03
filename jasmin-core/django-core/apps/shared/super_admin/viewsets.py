"""ViewSets for the super-admin (platform) API.

The function-based views in ``tenant_management_views.py`` are kept only
for the cross-schema authentication helper (``SuperAdminJWTAuthentication``)
and the auth-flow / backup RPC endpoints. All tenant CRUD + nested
operations on a tenant (users, resellers, role updates) live here on
``TenantManagementViewSet``.

URL surface (registered in ``urls.py`` via ``DefaultRouter``):

    GET    /tenants/
    POST   /tenants/
    GET    /tenants/<pk>/
    PATCH  /tenants/<pk>/
    GET    /tenants/<pk>/users/
    GET    /tenants/<pk>/resellers/
    POST   /tenants/<pk>/create-admin/
    POST   /tenants/<pk>/create-user/
    PATCH  /tenants/<pk>/users/<user_id>/roles/
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import (
    DatabaseError,
    IntegrityError,
    OperationalError,
    ProgrammingError,
    transaction,
)
from django.db.models import Prefetch
from django_tenants.utils import schema_context
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.authz.roles import VALID_ROLES
from apps.shared.request_utils import client_ip
from apps.shared.tenants.errors import SchemaAlreadyExists
from apps.shared.tenants.models import Domain, Tenant
from core.errors import BadRequestError, NotFoundError
from core.serializers import ErrorResponseSerializer

from .errors import (
    DomainInUse,
    InvalidRoles,
    LastAdminProtected,
    ResellerAlreadyLinked,
    ResellerNotFound,
    TenantNotFound,
    TenantProvisioningFailed,
    TenantSchemaMissing,
    TenantUserNotFound,
    UserEmailExists,
)
from .models import OpsChecklistItem, OpsChecklistRun
from .permissions import IsSuperAdmin
from .serializers import (
    CreateTenantAdminRequestSerializer,
    CreateTenantAdminResponseSerializer,
    CreateTenantRequestSerializer,
    CreateTenantResponseSerializer,
    CreateTenantUserRequestSerializer,
    CreateTenantUserResponseSerializer,
    OpsChecklistItemSerializer,
    OpsChecklistMarkDoneRequestSerializer,
    ResellerListItemSerializer,
    RunRotationResponseSerializer,
    TenantDetailResponseSerializer,
    TenantListItemSerializer,
    TenantUserListResponseSerializer,
    UpdateTenantRequestSerializer,
    UpdateTenantResponseSerializer,
    UpdateUserRolesRequestSerializer,
    UpdateUserRolesResponseSerializer,
)
from .services.rotation import (
    DISPATCHABLE_KINDS,
    UnknownRotationKind,
    rotate,
)
from .views.authentication import SuperAdminJWTAuthentication

logger = logging.getLogger("super_admin")


@contextmanager
def _tenant_schema_or_409(tenant):
    """Enter the tenant's schema, translating a missing/dropped schema (a Tenant
    row whose Postgres schema is gone — a partially-cleaned orphan, or a manual
    DROP) into a clean 409 instead of an unhandled 500. Mirrors the
    ``(OperationalError, ProgrammingError)`` guard the ``list`` action already
    uses; a genuine ``DoesNotExist`` still propagates (→ 404)."""
    try:
        with schema_context(tenant.schema_name):
            yield
    except (OperationalError, ProgrammingError) as exc:
        raise TenantSchemaMissing(
            f"Tenant '{tenant.schema_name}' has no schema (inconsistent state)"
        ) from exc


class TenantManagementViewSet(ViewSet):
    """Super-admin tenant management.

    All operations require a super-admin JWT (see
    ``SuperAdminJWTAuthentication``). Tenant rows live in the ``public``
    schema; per-tenant operations (users, resellers) switch into the
    target tenant's schema via ``schema_context``.
    """

    authentication_classes = [SuperAdminJWTAuthentication]
    permission_classes = [IsSuperAdmin]

    # Step-up gate on irreversible actions. Each one mutates or mints privilege
    # inside a tenant — ``create`` provisions a new tenant with a first admin
    # user, ``update_user_roles`` escalates an existing user (member → office /
    # admin), and ``create_admin`` / ``create_user`` plant a brand-new
    # admin-capable account (persistent backdoor access). A stolen super-admin
    # session must not fire any of them without a fresh password re-confirmation.
    # Keep the set small and named so an audit can list "gated by step-up" at a
    # glance. ``partial_update`` is gated conditionally (see get_permissions) —
    # only when it flips the ``is_active`` kill-switch.
    _STEP_UP_ACTIONS = frozenset(
        {"create", "update_user_roles", "create_admin", "create_user"}
    )

    def get_permissions(self):
        from apps.accounts.permissions import RequiresStepUp

        perms = super().get_permissions()
        if self.action in self._STEP_UP_ACTIONS:
            perms.append(RequiresStepUp())
        # Deactivating / reactivating a tenant (the is_active kill-switch) is a
        # high-blast-radius mutation a stolen session must not fire un-confirmed;
        # name/description edits via partial_update stay ungated.
        elif self.action == "partial_update" and "is_active" in (
            getattr(self.request, "data", None) or {}
        ):
            perms.append(RequiresStepUp())
        return perms

    # ── List / Create / Retrieve / Update ────────────────────────────────────

    @extend_schema(
        tags=["super-admin"],
        summary="List all tenants",
        parameters=[
            OpenApiParameter(
                name="include_user_count",
                type=OpenApiTypes.BOOL,
                required=False,
                description=(
                    "Whether to compute each tenant's user count (default "
                    "true). Counting is structurally cross-schema — a "
                    "search_path switch + COUNT per tenant — so callers that "
                    "only need the tenant roster can pass false for a cheap "
                    "list; user_count is then null."
                ),
            ),
        ],
        responses={
            200: TenantListItemSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request) -> Response:
        # Allowlist (default on): only explicit truthy tokens enable the
        # expensive per-tenant COUNT. A garbage value falls to False instead
        # of silently triggering the count (the old denylist's footgun).
        include_user_count = request.query_params.get(
            "include_user_count", "true"
        ).strip().lower() in ("true", "1", "yes", "on")

        with schema_context("public"):
            # Prefetch domains in one query instead of a per-tenant
            # exists()+first() pair against the same reverse relation.
            # Exclude the ``public`` schema row — it's the platform schema,
            # not a manageable tenant, and must never surface in the tenant
            # roster (no detail page, no deactivate toggle, not in the count).
            tenants = (
                Tenant.objects.exclude(schema_name="public")
                .prefetch_related("domains")
                .order_by("-created_at")
            )

            tenant_list = []
            for tenant in tenants:
                domains = list(tenant.domains.all())
                domain = domains[0].domain if domains else None

                user_count = None
                if include_user_count:
                    # The per-tenant search_path switch + COUNT is unavoidable
                    # cross-schema work; gated behind the flag so the default
                    # dashboard view keeps exact counts while a roster-only
                    # caller can skip it.
                    user_count = 0
                    try:
                        with schema_context(tenant.schema_name):
                            from apps.accounts.models import JasminUser

                            user_count = JasminUser.objects.count()
                    except (OperationalError, ProgrammingError):
                        # Schema doesn't exist yet or accounts table missing
                        # — leave ``user_count`` at 0 and continue.
                        pass

                tenant_list.append(
                    {
                        "id": tenant.id,
                        "schema_name": tenant.schema_name,
                        "name": tenant.name,
                        "domain": domain,
                        "created_on": tenant.created_at,
                        "is_active": tenant.is_active,
                        "user_count": user_count,
                    }
                )

            return Response(tenant_list, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["super-admin"],
        summary="Create new tenant",
        request=CreateTenantRequestSerializer,
        responses={
            201: CreateTenantResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            500: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request) -> Response:
        serializer = CreateTenantRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        schema_name = data["schema_name"]
        name = data["name"]
        domain = data["domain"]
        tenant_language = data.get("tenant_language", "")
        admin_email = data["admin_email"]
        admin_password = data["admin_password"]
        admin_first_name = data.get("admin_first_name", "")
        admin_last_name = data.get("admin_last_name", "")

        with schema_context("public"):
            if Tenant.objects.filter(schema_name=schema_name).exists():
                raise SchemaAlreadyExists(
                    f"Tenant with schema '{schema_name}' already exists"
                )

            if Domain.objects.filter(domain=domain).exists():
                raise DomainInUse(f"Domain '{domain}' is already in use")

        from apps.shared.tenants.services import TenantService

        service = TenantService()
        try:
            result = service.provision_tenant(
                schema_name=schema_name,
                name=name,
                domain=domain,
                tenant_language=tenant_language,
                admin_email=admin_email,
                admin_password=admin_password,
                admin_first_name=admin_first_name,
                admin_last_name=admin_last_name,
            )
        except IntegrityError as exc:
            # TOCTOU: a concurrent create won the race past the public-schema
            # pre-check above; the unique constraint is the source of truth.
            # Map to the precise 400 instead of the generic 500 (and the
            # self-cleaning provision already dropped any orphan schema).
            # Disambiguate by the violated constraint's NAME from the driver
            # diagnostics (stable, locale-independent); the message text is
            # only the fallback when the backend exposes no diagnostics.
            diagnostics = getattr(exc.__cause__, "diag", None)
            constraint_name = (
                getattr(diagnostics, "constraint_name", "") or ""
            ).lower()
            if "domain" in (constraint_name or str(exc).lower()):
                raise DomainInUse(f"Domain '{domain}' is already in use") from exc
            raise SchemaAlreadyExists(
                f"Tenant with schema '{schema_name}' already exists"
            ) from exc
        except (
            DatabaseError,
            DjangoValidationError,
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
        ) as exc:
            # Tenant provisioning is a multi-step operation spanning
            # schema creation, migrations, fixture loading, and admin-user
            # creation — narrow but inclusive catch for the realistic
            # failure families. Anything else (programmer bug) propagates
            # to DRF's exception handler.
            logger.error(
                "tenant.create_failed actor=%s schema=%s ip=%s error=%s",
                getattr(request.user, "id", "-"),
                schema_name,
                client_ip(request),
                exc,
            )
            # Generic client message on purpose — str(exc) may contain
            # SQL fragments / file paths; the full exception is in the
            # log line above.
            raise TenantProvisioningFailed("Tenant provisioning failed") from exc

        tenant = result["tenant"]
        logger.info(
            "tenant.created actor=%s schema=%s domain=%s admin_email=%s ip=%s",
            getattr(request.user, "id", "-"),
            tenant.schema_name,
            domain,
            admin_email,
            client_ip(request),
        )
        return Response(
            {
                "id": tenant.id,
                "schema_name": tenant.schema_name,
                "name": tenant.name,
                "domain": domain,
                "created_on": tenant.created_at,
                "admin_email": admin_email,
                "message": "Tenant created successfully with admin user",
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["super-admin"],
        summary="Get tenant details",
        responses={
            200: TenantDetailResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        try:
            with schema_context("public"):
                # The ``public`` schema is the platform, not a tenant — it has
                # no detail page; treat it as not-found here.
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)
                domains = tenant.domains.all()

                return Response(
                    {
                        "id": tenant.id,
                        "schema_name": tenant.schema_name,
                        "name": tenant.name,
                        "description": tenant.description,
                        "tenant_language": tenant.tenant_language,
                        "domains": [
                            {"domain": d.domain, "is_primary": d.is_primary}
                            for d in domains
                        ],
                        "created_on": tenant.created_at,
                        "is_active": tenant.is_active,
                    },
                    status=status.HTTP_200_OK,
                )

        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    @extend_schema(
        tags=["super-admin"],
        summary="Update tenant",
        request=UpdateTenantRequestSerializer,
        responses={
            200: UpdateTenantResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        # Validate FIRST (outside the try) so a 400 isn't masked as a 404.
        # ``partial=True`` keeps the present-keys-only semantics the
        # ``in validated`` checks below rely on.
        serializer = UpdateTenantRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        try:
            with schema_context("public"):
                # The ``public`` schema is the platform, not a manageable
                # tenant — never let it be renamed or (de)activated here.
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

                if "name" in validated:
                    tenant.name = validated["name"]
                if "description" in validated:
                    tenant.description = validated["description"]
                if "is_active" in validated:
                    tenant.is_active = validated["is_active"]

                tenant.save()

                logger.info(
                    "tenant.updated actor=%s schema=%s ip=%s fields=%s",
                    getattr(request.user, "id", "-"),
                    tenant.schema_name,
                    client_ip(request),
                    sorted(
                        set(validated.keys()) & {"name", "description", "is_active"}
                    ),
                )

                return Response(
                    {
                        "id": tenant.id,
                        "schema_name": tenant.schema_name,
                        "name": tenant.name,
                        "message": "Tenant updated successfully",
                    },
                    status=status.HTTP_200_OK,
                )

        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    # ── Nested resources ─────────────────────────────────────────────────────

    @extend_schema(
        tags=["super-admin"],
        summary="List users of a tenant",
        responses={
            200: TenantUserListResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["get"])
    def users(self, request: Request, pk: str | None = None) -> Response:
        try:
            with schema_context("public"):
                # ``public`` is the platform schema, never a manageable
                # tenant — don't let a known public id reach the nested
                # actions (e.g. creating a user in the public schema).
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

            with _tenant_schema_or_409(tenant):
                from apps.accounts.models import JasminUser

                users = JasminUser.objects.all().order_by("last_name", "first_name")

                def serialize_user(u: Any) -> dict[str, Any]:
                    return {
                        "id": u.id,
                        "first_name": u.first_name,
                        "last_name": u.last_name,
                        "email": u.email,
                        "roles": u.roles or [],
                        "is_active": u.is_active,
                        "account_status": u.account_status,
                        "date_joined": u.date_joined,
                        "last_login": u.last_login,
                    }

                admin_users = [
                    serialize_user(u) for u in users if "admin" in (u.roles or [])
                ]
                other_users = [
                    serialize_user(u) for u in users if "admin" not in (u.roles or [])
                ]

                return Response(
                    {"admin_users": admin_users, "other_users": other_users},
                    status=status.HTTP_200_OK,
                )

        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    @extend_schema(
        tags=["super-admin"],
        summary="List resellers of a tenant",
        responses={
            200: ResellerListItemSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["get"])
    def resellers(self, request: Request, pk: str | None = None) -> Response:
        try:
            with schema_context("public"):
                # ``public`` is the platform schema, never a manageable
                # tenant — don't let a known public id reach the nested
                # actions (e.g. creating a user in the public schema).
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

            with _tenant_schema_or_409(tenant):
                from apps.commissioning.models import Reseller

                resellers = Reseller.objects.filter(
                    is_reseller=True, is_active_reseller=True
                ).order_by("name_for_member_pages", "customer_number")
                data = [
                    {
                        "id": str(r.id),
                        "customer_number": r.customer_number,
                        "filial_number": r.filial_number,
                        "name_for_member_pages": r.name_for_member_pages,
                        "linked_user_id": (
                            str(r.linked_user_id) if r.linked_user_id else None
                        ),
                        "display": (
                            r.name_for_member_pages
                            or f"Reseller #{r.customer_number or r.id}"
                        ),
                    }
                    for r in resellers
                ]
                return Response(data, status=status.HTTP_200_OK)
        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    @extend_schema(
        tags=["super-admin"],
        summary="Create admin user for a tenant",
        request=CreateTenantAdminRequestSerializer,
        responses={
            201: CreateTenantAdminResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="create-admin")
    def create_admin(self, request: Request, pk: str | None = None) -> Response:
        serializer = CreateTenantAdminRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        first_name = serializer.validated_data["first_name"]
        last_name = serializer.validated_data["last_name"]
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            with schema_context("public"):
                # ``public`` is the platform schema, never a manageable
                # tenant — don't let a known public id reach the nested
                # actions (e.g. creating a user in the public schema).
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

            with _tenant_schema_or_409(tenant):
                from apps.accounts.models import JasminUser

                if JasminUser.objects.filter(email=email).exists():
                    raise UserEmailExists(
                        f"User with email '{email}' already exists in this tenant"
                    )

                try:
                    user = JasminUser.objects.create_user(
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        password=password,
                        is_active=True,
                        account_status="active",
                        roles=["admin"],
                    )
                except IntegrityError as exc:
                    # TOCTOU: a concurrent create won the race past the .exists()
                    # pre-check above. The unique email/username constraint is the
                    # source of truth — map to the precise 400, not a generic 500.
                    raise UserEmailExists(
                        f"User with email '{email}' already exists in this tenant"
                    ) from exc

                logger.info(
                    "tenant.admin_created actor=%s tenant=%s target_user=%s "
                    "target_email=%s ip=%s",
                    getattr(request.user, "id", "-"),
                    tenant.schema_name,
                    user.id,
                    email,
                    client_ip(request),
                )

                return Response(
                    {
                        "id": user.id,
                        "email": user.email,
                        "message": f"Admin user created for tenant '{tenant.name}'",
                    },
                    status=status.HTTP_201_CREATED,
                )

        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    @extend_schema(
        tags=["super-admin"],
        summary="Create user for a tenant with custom roles",
        request=CreateTenantUserRequestSerializer,
        responses={
            201: CreateTenantUserResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="create-user")
    def create_user(self, request: Request, pk: str | None = None) -> Response:
        serializer = CreateTenantUserRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        first_name = data["first_name"]
        last_name = data["last_name"]
        email = data["email"]
        password = data["password"]
        roles = data.get("roles", [])
        reseller_id = data.get("reseller_id") or None

        if reseller_id and "customer" not in roles:
            raise InvalidRoles(
                "reseller_id can only be set when 'customer' is in roles"
            )

        from apps.authz.roles import validate_role_combination

        combo_err = validate_role_combination(roles)
        if combo_err:
            raise InvalidRoles(combo_err)

        try:
            with schema_context("public"):
                # ``public`` is the platform schema, never a manageable
                # tenant — don't let a known public id reach the nested
                # actions (e.g. creating a user in the public schema).
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

            with _tenant_schema_or_409(tenant):
                from apps.accounts.models import JasminUser

                if JasminUser.objects.filter(email=email).exists():
                    raise UserEmailExists(
                        f"User with email '{email}' already exists in this tenant"
                    )

                invalid_roles = set(roles) - VALID_ROLES
                if invalid_roles:
                    raise InvalidRoles(
                        f"Invalid roles: {', '.join(sorted(invalid_roles))}"
                    )

                # Atomic so a reseller-link failure (ResellerNotFound /
                # ResellerAlreadyLinked) rolls back the just-created privileged
                # user instead of leaving an orphaned, login-capable account
                # that also blocks the corrective retry (UserEmailExists).
                # Requests run in autocommit (no ATOMIC_REQUESTS), so this is
                # required — mirrors create_user_with_invite's @transaction.atomic.
                with transaction.atomic():
                    user = JasminUser.objects.create_user(
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        password=password,
                        is_active=True,
                        account_status="active",
                        roles=roles,
                    )

                    linked_reseller_id = None
                    if reseller_id:
                        from apps.commissioning.models import Reseller

                        try:
                            reseller = Reseller.objects.get(id=reseller_id)
                        except Reseller.DoesNotExist:
                            raise ResellerNotFound(
                                f"Reseller '{reseller_id}' not found"
                            ) from None
                        if reseller.linked_user_id and str(
                            reseller.linked_user_id
                        ) != str(user.id):
                            raise ResellerAlreadyLinked(
                                "This reseller is already linked to another user"
                            )
                        reseller.linked_user = user
                        reseller.save(update_fields=["linked_user"])
                        linked_reseller_id = str(reseller.id)

                logger.info(
                    "tenant.user_created actor=%s tenant=%s target_user=%s "
                    "target_email=%s roles=%s ip=%s",
                    getattr(request.user, "id", "-"),
                    tenant.schema_name,
                    user.id,
                    email,
                    sorted(roles),
                    client_ip(request),
                )

                return Response(
                    {
                        "id": user.id,
                        "email": user.email,
                        "roles": user.roles or [],
                        "reseller_id": linked_reseller_id,
                        "message": f"User created for tenant '{tenant.name}'",
                    },
                    status=status.HTTP_201_CREATED,
                )

        except IntegrityError as exc:
            # TOCTOU: a concurrent create won the race past the .exists()
            # pre-check. Caught on the OUTER try (not inside the atomic, where
            # the connection is already broken) and mapped to the precise 400.
            raise UserEmailExists(
                f"User with email '{email}' already exists in this tenant"
            ) from exc
        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None

    @extend_schema(
        tags=["super-admin"],
        summary="Update roles of a tenant user",
        request=UpdateUserRolesRequestSerializer,
        responses={
            200: UpdateUserRolesResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path="users/(?P<user_id>[^/.]+)/roles",
    )
    def update_user_roles(
        self,
        request: Request,
        pk: str | None = None,
        user_id: str | None = None,
    ) -> Response:
        serializer = UpdateUserRolesRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        roles = serializer.validated_data["roles"]
        force = serializer.validated_data.get("force", False)

        from apps.authz.roles import Role, validate_role_combination
        from core.db_locks import acquire_advisory_xact_lock

        # Reject unknown roles (mirrors create_user + the in-tenant
        # update_user_admin) — a typo'd role must be a 400, never silently
        # filtered into a different effective role set.
        invalid_roles = set(roles) - VALID_ROLES
        if invalid_roles:
            raise InvalidRoles(f"Invalid roles: {', '.join(sorted(invalid_roles))}")
        combo_err = validate_role_combination(roles)
        if combo_err:
            raise InvalidRoles(combo_err)

        from apps.accounts.models import JasminUser

        try:
            with schema_context("public"):
                # ``public`` is the platform schema, never a manageable
                # tenant — don't let a known public id reach the nested
                # actions (e.g. creating a user in the public schema).
                tenant = Tenant.objects.exclude(schema_name="public").get(id=pk)

            # Atomic so the role change + reseller unlink are all-or-nothing
            # (no role/reseller-link desync on a partial failure).
            with _tenant_schema_or_409(tenant), transaction.atomic():
                user = JasminUser.objects.get(id=user_id)
                previous_roles = list(user.roles or [])

                # Last-admin protection (mirrors the in-tenant guard): refuse to
                # demote the tenant's final active admin into an administrator-
                # less state. The advisory lock serialises concurrent admin-role
                # mutations so two requests demoting different admins can't both
                # pass under READ COMMITTED and zero the admin set.
                removing_admin = (
                    Role.ADMIN in previous_roles and Role.ADMIN not in roles
                )
                if removing_admin and not force:
                    acquire_advisory_xact_lock("admin_role:mutation")
                    another_active_admin_exists = (
                        JasminUser.objects.filter(
                            roles__contains=[Role.ADMIN], is_active=True
                        )
                        .exclude(pk=user.pk)
                        .exists()
                    )
                    if not another_active_admin_exists:
                        raise LastAdminProtected(
                            "Cannot remove the 'admin' role from the tenant's "
                            "last active admin. Pass force=true to override."
                        )

                user.roles = roles
                user.save(update_fields=["roles"])

                # Drop reseller link if 'customer' is no longer in roles.
                if "customer" not in roles:
                    from apps.commissioning.models import Reseller

                    Reseller.objects.filter(linked_user=user).update(linked_user=None)

                logger.info(
                    "user.roles_changed actor=%s tenant=%s target_user=%s "
                    "target_email=%s before=%s after=%s ip=%s",
                    getattr(request.user, "id", "-"),
                    tenant.schema_name,
                    user.id,
                    user.email,
                    sorted(previous_roles),
                    sorted(roles),
                    client_ip(request),
                )

                return Response(
                    {
                        "id": user.id,
                        "roles": user.roles,
                        "message": f"Roles updated for user '{user.email}'",
                    },
                    status=status.HTTP_200_OK,
                )

        except Tenant.DoesNotExist:
            raise TenantNotFound("Tenant not found") from None
        except JasminUser.DoesNotExist:
            raise TenantUserNotFound("User not found in this tenant") from None


def _serialize_item(item: OpsChecklistItem) -> dict[str, Any]:
    # Prefer the prefetched, pre-ordered runs (list view) so we resolve the
    # last run + its ``completed_by`` without a per-row query; fall back to the
    # property for callers that didn't prefetch (``mark_done`` returns a single
    # freshly-fetched item). Resolve ONCE and thread it into next_due/overdue.
    ordered = getattr(item, "_ordered_runs", None)
    last = (ordered[0] if ordered else None) if ordered is not None else item.last_run
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "description": item.description,
        "interval_days": item.interval_days,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "last_run": (
            {
                "id": last.id,
                "completed_at": last.completed_at,
                "completed_by_email": (
                    last.completed_by.email if last.completed_by else None
                ),
                "notes": last.notes,
            }
            if last is not None
            else None
        ),
        "next_due_at": item.next_due_at_for(last),
        "is_overdue": item.is_overdue_for(last),
    }


"""Super-admin endpoints for the operational checklist.

URL surface (registered via ``DefaultRouter`` in ``urls.py``):

    GET   /ops-checklist/                       — list every item
    POST  /ops-checklist/<pk>/mark-done/        — append a run, returns the
                                                  refreshed item
    POST  /ops-checklist/<pk>/run-rotation/     — dispatch a rotation by the
                                                  item's ``kind``. Returns
                                                  generated secret +
                                                  instructions for the
                                                  operator. NEVER logs the
                                                  generated secret value;
                                                  only the rotation event.

Marking an item done is the user-driven mutation; ``run-rotation`` is
the more involved one — see ``apps/shared/super_admin/services/rotation.py``
for the per-kind implementations.

Items + their seed data live in the migration; nothing here creates /
deletes items at runtime. Add new ones via a new migration or a
future admin form.
"""


class OpsChecklistViewSet(ViewSet):
    """Super-admin ops checklist."""

    authentication_classes = [SuperAdminJWTAuthentication]
    permission_classes = [IsSuperAdmin]

    # Step-up gate on the destructive action. ``run_rotation`` dispatches
    # secret / DB-password / Bunny-token regeneration and the mass
    # email-credential clear (``rotate_email_creds`` wipes every tenant's
    # stored SMTP password + flips is_verified=False platform-wide). That's
    # exactly the blast radius a stolen super-admin session must NOT be able
    # to fire without a fresh password re-confirmation — same gate as
    # ``super_admin_trigger_backup_view`` and ``TenantManagementViewSet``.
    _STEP_UP_ACTIONS = frozenset({"run_rotation"})

    def get_permissions(self):
        from apps.accounts.permissions import RequiresStepUp

        perms = super().get_permissions()
        if self.action in self._STEP_UP_ACTIONS:
            perms.append(RequiresStepUp())
        return perms

    @extend_schema(
        tags=["super-admin"],
        responses={
            200: OpsChecklistItemSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
        description=(
            "List every operational checklist item with its computed "
            "``next_due_at`` and ``is_overdue`` flag. Use ``mark-done`` "
            "to append a completion."
        ),
    )
    def list(self, request: Request) -> Response:
        # Prefetch each item's runs newest-first into ``_ordered_runs`` with
        # ``completed_by`` joined, so ``_serialize_item`` reads last-run +
        # next-due + overdue from memory — one query for all runs instead of
        # ~4 per row.
        items = OpsChecklistItem.objects.prefetch_related(
            Prefetch(
                "runs",
                queryset=OpsChecklistRun.objects.order_by(
                    "-completed_at"
                ).select_related("completed_by"),
                to_attr="_ordered_runs",
            )
        ).all()
        return Response([_serialize_item(i) for i in items])

    @extend_schema(
        tags=["super-admin"],
        request=OpsChecklistMarkDoneRequestSerializer,
        responses={
            200: OpsChecklistItemSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        description=(
            "Append an ``OpsChecklistRun`` for this item. The run records "
            "the calling super-admin, the timestamp, and any notes you "
            "want to keep for future-you. Returns the refreshed item with "
            "the new ``last_run`` + recomputed ``next_due_at``."
        ),
    )
    @action(detail=True, methods=["post"], url_path="mark-done")
    def mark_done(self, request: Request, pk: str | None = None) -> Response:
        item = OpsChecklistItem.objects.filter(pk=pk).first()
        if item is None:
            raise NotFoundError("Checklist item not found.")

        serializer = OpsChecklistMarkDoneRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notes = serializer.validated_data["notes"].strip()
        run = OpsChecklistRun.objects.create(
            item=item,
            completed_by=request.user if request.user.is_authenticated else None,
            notes=notes,
        )
        logger.info(
            "ops.checklist.marked_done item=%s actor=%s run=%s",
            item.kind,
            getattr(request.user, "email", "?"),
            run.id,
        )
        item.refresh_from_db()
        return Response(_serialize_item(item))

    @extend_schema(
        tags=["super-admin"],
        request=inline_serializer(
            name="RunRotationRequest",
            fields={
                "dry_run": drf_serializers.BooleanField(required=False, default=False),
            },
        ),
        responses={
            200: RunRotationResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
        description=(
            "Dispatch the rotation matching this item's ``kind``. The four "
            "supported kinds are ``rotate_django_secret``, "
            "``rotate_db_password``, ``rotate_bunny_token``, "
            "``rotate_email_creds``. The fifth declared rotation, "
            "``rotate_field_encryption``, has its own dedicated management "
            "command (chunked over many rows) and is NOT served here.\n\n"
            "Returns a body shaped:\n\n"
            "    {\n"
            '        "kind": "rotate_django_secret",\n'
            '        "generated_secret": "abc...xyz",  # may be null\n'
            '        "instructions": "1. Copy the key...",\n'
            '        "items_affected": 0,\n'
            '        "extras": {...}\n'
            "    }\n\n"
            "The ``generated_secret`` is returned exactly once — the caller "
            "MUST show it to the operator + drop it. We never log the "
            "value, only the rotation event."
        ),
    )
    @action(detail=True, methods=["post"], url_path="run-rotation")
    def run_rotation(self, request: Request, pk: str | None = None) -> Response:
        item = OpsChecklistItem.objects.filter(pk=pk).first()
        if item is None:
            raise NotFoundError("Checklist item not found.")
        if item.kind not in DISPATCHABLE_KINDS:
            raise BadRequestError(
                f"This checklist item's kind ({item.kind!r}) is "
                "not a runnable rotation. Use mark-done instead, "
                "or run the dedicated management command for "
                "kinds like rotate_field_encryption."
            )

        # ``dry_run`` only matters for ``rotate_email_creds``; the
        # secret-generators are side-effect-free anyway.
        dry_run = bool(request.data.get("dry_run", False))

        try:
            result = rotate(item.kind, dry_run=dry_run)
        except UnknownRotationKind:
            # ``DISPATCHABLE_KINDS`` guard above should have caught this;
            # belt-and-suspenders.
            raise BadRequestError(f"Unknown rotation kind: {item.kind!r}") from None

        # Event-only logging — NEVER include ``result.generated_secret``
        # in any log line. We're rotating because the old credential is
        # compromised or stale; leaking the new one into a log file
        # would defeat the rotation.
        logger.info(
            "ops.rotation.executed kind=%s actor=%s dry_run=%s items_affected=%s",
            item.kind,
            getattr(request.user, "email", "?"),
            dry_run,
            result.items_affected,
        )
        return Response(
            {
                "kind": result.kind,
                "generated_secret": result.generated_secret,
                "instructions": result.instructions,
                "items_affected": result.items_affected,
                "extras": result.extras,
            }
        )
