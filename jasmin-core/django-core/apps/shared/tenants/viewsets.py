from __future__ import annotations

import logging
import smtplib
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from drf_spectacular.utils import (
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsAdmin, IsOffice, IsStaff, RolePermissionsMixin
from apps.shared.request_utils import client_ip
from core.serializers import ErrorResponseSerializer
from core.throttling import TenantScopedRateThrottle

from .errors import (
    CoopSharesBoundsInverted,
    EmptyNumberingPrefix,
    InvalidSettingsValue,
    NoTenantContext,
    YearNumberingLocked,
)
from .models import Tenant, TenantEmailConfig, TenantSettings
from .serializers import (
    TenantEmailConfigSerializer,
    TenantNonStaffReadSerializer,
    TenantSerializer,
    TenantSettingsSerializer,
    TenantSettingsToDictSerializer,
)

logger = logging.getLogger(__name__)

# Mapping: year-based setting field → (model import path, document type label)
YEAR_BASED_SETTING_TO_MODEL: dict[str, tuple[str, str]] = {
    "order_numbers_start_new_at_year_change": (
        "apps.commissioning.models.Order",
        "orders",
    ),
    "delivery_note_numbers_start_new_at_year_change": (
        "apps.commissioning.models.DeliveryNoteReseller",
        "delivery notes",
    ),
    "invoice_numbers_start_new_at_year_change": (
        "apps.commissioning.models.InvoiceReseller",
        "invoices",
    ),
}


# ``get_serializer_class`` branches per caller role (see its docstring) —
# declare BOTH read shapes so the generated client carries the truth: a
# member's payload has no iban/sepa/uid keys, only the staff payload does.
def _tenant_read_response(many: bool) -> PolymorphicProxySerializer:
    return PolymorphicProxySerializer(
        component_name="TenantRead",
        serializers=[TenantSerializer, TenantNonStaffReadSerializer],
        resource_type_field_name=None,
        many=many,
    )


@extend_schema_view(
    list=extend_schema(responses={200: _tenant_read_response(many=True)}),
    retrieve=extend_schema(responses={200: _tenant_read_response(many=False)}),
)
class TenantViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Per-tenant configuration endpoint.

    Frontend usage:

      * ``TenantContext`` re-fetches this **after login** to enrich
        the pre-login bootstrap data (which only carries the branding
        allowlist from ``CurrentTenantSerializer``) with operational
        fields — IBAN/BIC for invoice PDFs, contact info for PDF
        headers, the ``settings`` / ``current_settings`` overlays
        that ``getSetting(...)`` reads, etc.
      * ``ConfigurationGeneral`` / ``ConfigurationApp`` PATCH
        ``/api/tenants/tenants/<id>/`` to update branding / banking /
        contact fields. Both pages are gated to ``isAdmin`` on the
        frontend; ``write_permission = IsAdmin`` enforces the same
        server-side.

    Permissions:

      * ``read_permission = None`` → falls through to DRF's project-wide
        ``DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]``. Every
        authenticated tenant user (office, gardener, member, customer)
        needs to read this because ``getSetting(...)`` from the
        TenantContext is consumed by sidebars and member/customer
        pages alike. Tenant operational fields (IBAN on invoices,
        email on PDF headers, ...) are already visible on the documents
        these users receive — exposing them via API to the same
        logged-in user is not a wider leak.
      * ``write_permission = IsAdmin`` — only admins may change
        tenant config.
      * ``get_queryset`` scopes to the **current tenant only**, so
        even a logged-in user from one tenant cannot peek at another
        tenant's row.

    Cross-platform tenant creation + (de)activation lives in the
    super-admin app (``TenantManagementViewSet``) with its own
    ``IsSuperAdmin`` + ``SuperAdminJWTAuthentication`` stack. There is no
    hard-delete endpoint anywhere — tenant offboarding is soft-only
    (``is_active=False``); dropping a schema is intentionally not exposed
    over the API. This viewset is intentionally narrow:

      * Only ``GET`` / ``PUT`` / ``PATCH`` are allowed
        (``http_method_names`` below).

    """

    # Read falls through to IsAuthenticated (DRF default). Any logged-in
    # tenant user can read THEIR OWN tenant — see the class docstring
    # for the rationale.
    read_permission = None
    write_permission = IsAdmin

    serializer_class = TenantSerializer
    # No POST (use the super-admin endpoint to create tenants). No DELETE —
    # tenant offboarding is soft-only (set is_active=False via the super-admin
    # PATCH /tenants/<pk>/ endpoint); hard schema-drop is intentionally not
    # exposed over the API.
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_serializer_class(self):
        """Pick the narrower serializer for non-staff reads.

        Staff (office / staff / admin) → ``TenantSerializer`` with the
        full operational payload (banking, SEPA, UID, internal email,
        organic-control number, ...). These users have UI that consumes
        those fields: ``ConfigurationGeneral``, reseller PDF generation,
        packing-list headers.

        Everyone else (members, customers, gardeners without staff
        scope) → ``TenantNonStaffReadSerializer`` with branding +
        locale + GDPR-impressum + settings overlay only. None of the
        member/customer pages consume the office-only fields — they
        were riding along on ``__all__`` without a UI to render them.

        Write actions (PUT / PATCH) keep ``TenantSerializer`` because
        ``write_permission = IsAdmin`` already gates them: only admins
        get there, and admins are by definition IsStaff.
        """
        if self.action in ("list", "retrieve"):
            if not IsStaff().has_permission(self.request, self):
                return TenantNonStaffReadSerializer
        return TenantSerializer

    def get_queryset(self) -> QuerySet[Tenant]:
        # Scope to the calling tenant only. ``request.tenant`` is set by
        # ``django_tenants.middleware.TenantMainMiddleware`` from the
        # subdomain. The previous unfiltered ``Tenant.objects.all()``
        # crossed over to the public schema and listed every tenant on
        # the platform — see audit doc referenced in the class docstring.
        tenant = getattr(self.request, "tenant", None)
        if tenant is None or getattr(tenant, "schema_name", "") == "public":
            return Tenant.objects.none()
        return Tenant.objects.filter(pk=tenant.pk)


class TenantSettingsViewSet(RolePermissionsMixin, viewsets.GenericViewSet):
    # Tenant settings drive tax rates, year-numbering rules and other
    # operational config — office is the role that manages them in the UI
    # (existing tests demonstrate this expected UX). Staff at large may
    # read so the office UI can display current settings for context.
    # Year-numbering changes after documents exist are gated by a
    # Python-level check inside ``update_current_settings``.
    # Read needs IsStaff (not IsAuthenticated) because customers /
    # resellers must not see SMTP creds or tax rates; write needs
    # IsOffice because ``update_current_settings`` rewrites tenant-
    # wide pricing config.
    #
    # GenericViewSet + explicit ``list``: settings versions are written
    # ONLY through ``update_current_settings`` (close current version,
    # open new one). The previous ModelViewSet exposed detail routes
    # that 500ed on every call (``get_object`` on a sliced queryset)
    # and a bare ``create`` that bypassed the versioning logic.
    read_permission = IsOffice
    write_permission = IsOffice

    serializer_class = TenantSettingsSerializer

    # Settings whose change is high-impact enough to demand fresh step-up auth
    # in ``update_current_settings`` (mirrors MemberViewSet._SEPA_SENSITIVE_FIELDS).
    # The GDPR-deletion gate controls whether self-service member/customer
    # deletions auto-execute without admin approval; the billing/SEPA/tax fields
    # drive money collection. A stolen office session must not flip these
    # silently.
    _STEP_UP_SENSITIVE_FIELDS = (
        "require_admin_approval_for_gdpr_deletion",
        "billing_strategy",
        "billing_due_day_of_month",
        "sepa_collection_day_of_month",
        "default_tax_rate_articles",
        "default_tax_rate_crates",
        "default_tax_rate_shares",
    )

    def get_queryset(self) -> QuerySet[TenantSettings]:
        # Tenant is resolved from the subdomain by TenantMainMiddleware — no
        # query-param plumbing needed (and no chance of one tenant asking for
        # another's settings).
        tenant = getattr(self.request, "tenant", None)
        if tenant is None or getattr(tenant, "schema_name", "") == "public":
            return TenantSettings.objects.none()

        return TenantSettings.objects.filter(
            Q(valid_until__gt=timezone.now()) | Q(valid_until__isnull=True),
            tenant=tenant.id,
            valid_from__lte=timezone.now(),
        ).order_by("-valid_from")

    @extend_schema(responses={200: TenantSettingsSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the current settings version as a one-element array
        (empty array when the tenant has no settings row yet) — the
        shape the frontend has always consumed."""
        instance = self.get_queryset().first()
        data = [self.get_serializer(instance).data] if instance else []
        return Response(data)

    @extend_schema(
        request=inline_serializer(
            name="UpdateCurrentSettingsRequest",
            fields={
                "settings": drf_serializers.DictField(
                    child=drf_serializers.JSONField(),
                    help_text="Key-value pairs of settings to update",
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="UpdateCurrentSettingsResponse",
                fields={"settings": TenantSettingsToDictSerializer()},
            ),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["put"], url_path="update_current_settings")
    def update_current_settings(self, request: Request) -> Response:
        """Update current settings for the calling tenant by closing the
        current version and creating a new one. The tenant is taken from
        ``request.tenant`` (set by TenantMainMiddleware from the subdomain)."""
        tenant = getattr(request, "tenant", None)
        if tenant is None or getattr(tenant, "schema_name", "") == "public":
            raise NoTenantContext("No tenant context")

        now = timezone.now()

        # Apply received data (excluding system fields)
        new_settings_data: dict[str, Any] = request.data.get("settings", {})
        system_fields = {"id", "tenant", "valid_from", "valid_until", "created_at"}

        # Serialize concurrent PUTs: read the open row UNDER A LOCK inside one
        # transaction and run EVERY validation below against that locked row —
        # a snapshot read taken before the lock could validate against a
        # version a concurrent PUT is about to replace. The partial-unique
        # constraint (tenantsettings_one_current_per_tenant) is the hard
        # backstop; the lock turns a would-be IntegrityError on the loser into
        # clean serialization (it waits, then versions off the winner's row).
        with transaction.atomic():
            current_settings = (
                TenantSettings.objects.select_for_update()
                .filter(tenant=tenant, valid_until__isnull=True)
                .order_by("-valid_from", "-created_at", "-id")
                .first()
            )

            changed_sensitive = self._enforce_step_up_for_sensitive_changes(
                request, current_settings, new_settings_data
            )

            self._validate_numbering_prefixes(new_settings_data)
            self._validate_year_numbering_locks(current_settings, new_settings_data)
            self._validate_coop_shares_bounds(current_settings, new_settings_data)

            # Close the current version and create the new one — still under
            # the same lock the validations above ran against.
            new_settings = self._version_and_save_settings(
                tenant, current_settings, new_settings_data, now, system_fields
            )

        if changed_sensitive:
            logger.info(
                "tenant_settings.sensitive_changed actor=%s tenant=%s ip=%s changes=%s",
                getattr(request.user, "id", "-"),
                getattr(tenant, "schema_name", "-"),
                client_ip(request),
                "; ".join(
                    f"{field}:{old}->{new}"
                    for field, (old, new) in sorted(changed_sensitive.items())
                ),
            )

        return Response({"settings": new_settings.to_dict()})

    def _enforce_step_up_for_sensitive_changes(
        self,
        request: Request,
        current_settings: TenantSettings | None,
        new_settings_data: dict[str, Any],
    ) -> dict[str, tuple[str, str]]:
        """Detect changes to step-up-sensitive fields and gate them.

        Weakening the GDPR self-service-deletion gate, or changing the
        billing strategy / SEPA collection day / tax rates, is a
        high-impact config change a stolen office session must not make
        silently. Gate those specific fields behind fresh step-up auth —
        only when a value actually changes (so a PATCH echoing the
        unchanged value doesn't prompt) — and return the changes so the
        caller can record an audit line after the save, since
        TenantSettings is deliberately not auditlog-registered.
        """

        def _norm(val: object) -> str:
            return str(val).strip() if val is not None else ""

        changed_sensitive: dict[str, tuple[str, str]] = {}
        for sensitive_field in self._STEP_UP_SENSITIVE_FIELDS:
            if sensitive_field not in new_settings_data:
                continue
            if current_settings is not None:
                old_value: Any = getattr(current_settings, sensitive_field, None)
            else:
                old_value = TenantSettings._meta.get_field(
                    sensitive_field
                ).get_default()
            new_value = new_settings_data[sensitive_field]
            if _norm(new_value) != _norm(old_value):
                changed_sensitive[sensitive_field] = (
                    _norm(old_value),
                    _norm(new_value),
                )

        if changed_sensitive:
            from apps.accounts.permissions import RequiresStepUp

            # Raises StepUpRequired (the canonical ``auth.step_up_required``
            # code the frontend modal matches) when the access token carries
            # no fresh step-up claim. Fail before any version is written.
            RequiresStepUp().has_permission(request, self)

        return changed_sensitive

    @staticmethod
    def _validate_numbering_prefixes(new_settings_data: dict[str, Any]) -> None:
        """Refuse to blank a legal-document numbering prefix.

        Numbering prefixes are legal-document labels — refuse to blank
        them. This endpoint setattr's raw values and save()s without the
        serializer, so the serializer's allow_blank=False never fires; a
        cleared correction prefix would otherwise make stornos render as
        bare 1, 2, 3… while invoices keep their "RE-" label.
        """
        for prefix_field in (
            "invoice_number_prefix",
            "correction_invoice_number_prefix",
            "order_number_prefix",
            "delivery_note_number_prefix",
        ):
            if prefix_field in new_settings_data:
                value = new_settings_data[prefix_field]
                if value is None or str(value).strip() == "":
                    raise EmptyNumberingPrefix(
                        f"'{prefix_field}' cannot be empty — document "
                        "numbers must carry a prefix.",
                        field=prefix_field,
                    )

    @staticmethod
    def _validate_year_numbering_locks(
        current_settings: TenantSettings | None,
        new_settings_data: dict[str, Any],
    ) -> None:
        """Reject changing a year-based numbering setting once documents exist."""
        for setting_field, (
            model_path,
            label,
        ) in YEAR_BASED_SETTING_TO_MODEL.items():
            if setting_field not in new_settings_data:
                continue
            current_value = (
                getattr(current_settings, setting_field) if current_settings else False
            )
            new_value = new_settings_data[setting_field]
            if new_value != current_value:
                from django.utils.module_loading import import_string

                model_class = import_string(model_path)
                if model_class.objects.exists():
                    raise YearNumberingLocked(
                        f"The setting '{setting_field}' cannot be changed "
                        f"because {label} already exist.",
                        field=setting_field,
                    )

    @staticmethod
    def _validate_coop_shares_bounds(
        current_settings: TenantSettings | None,
        new_settings_data: dict[str, Any],
    ) -> None:
        """Reject an inverted coop-share window (min > max).

        No member total can satisfy it, and it would soft-brick every
        non-trial coop-share save and admin confirmation for the tenant.
        This endpoint setattr's + save()s without the serializer, so there
        is no other guard here.
        """

        def _bound(field: str) -> int | None:
            raw = new_settings_data.get(field, getattr(current_settings, field, None))
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        min_shares = _bound("min_number_coop_shares")
        max_shares = _bound("max_number_coop_shares")
        if (
            min_shares is not None
            and max_shares is not None
            and min_shares > max_shares
        ):
            raise CoopSharesBoundsInverted(
                "min_number_coop_shares cannot exceed max_number_coop_shares.",
                field="min_number_coop_shares",
            )

    @staticmethod
    def _version_and_save_settings(
        tenant: Tenant,
        current_settings: TenantSettings | None,
        new_settings_data: dict[str, Any],
        now: Any,
        system_fields: set[str],
    ) -> TenantSettings:
        """Close the open version, apply the changes, validate, and persist.

        Must run under the same lock / transaction the validations above ran
        against.
        """
        if current_settings:
            current_settings.valid_until = now
            current_settings.save(update_fields=["valid_until"])

            new_settings = current_settings.copy()
            new_settings.valid_from = now
            new_settings.valid_until = None
        else:
            new_settings = TenantSettings(
                tenant=tenant,
                valid_from=now,
                valid_until=None,
            )

        changed_fields = set()
        for key, value in new_settings_data.items():
            if key not in system_fields and hasattr(new_settings, key):
                setattr(new_settings, key, value)
                changed_fields.add(key)

        # This is the ONLY write path for TenantSettings and it setattr's
        # raw values (the serializer never validates them), so enforce the
        # model field validators here — e.g. billing_due_day_of_month /
        # sepa_collection_day_of_month (1-28), season_start_week (1-53).
        # Without this an out-of-range day persists and later crashes
        # charge-schedule generation (period_start.replace(day=0)).
        #
        # Validate ONLY the fields this request changed: a whole-object
        # full_clean would re-validate untouched legacy columns (e.g. a row
        # that predates a stricter validator) and wrongly reject a valid
        # edit. Uniqueness is enforced by the partial unique constraint, so
        # validate_unique is skipped too.
        concrete_field_names = {f.name for f in new_settings._meta.fields}
        exclude_from_clean = list(concrete_field_names - changed_fields)
        try:
            new_settings.full_clean(exclude=exclude_from_clean, validate_unique=False)
        except DjangoValidationError as exc:
            error_by_field = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else {"__all__": exc.messages}
            )
            offending_field = next(iter(error_by_field), None)
            message = (
                "; ".join(error_by_field.get(offending_field, []))
                if offending_field
                else "Invalid settings value."
            )
            raise InvalidSettingsValue(
                message,
                field=offending_field if offending_field != "__all__" else None,
            ) from exc

        new_settings.save()
        return new_settings

    @extend_schema(
        responses={
            200: inline_serializer(
                name="LockedSettingsResponse",
                fields={
                    "locked_settings": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                    ),
                },
            ),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"], url_path="locked_settings")
    def locked_settings(self, request: Request) -> Response:
        """Return year-based numbering settings that cannot be changed
        because documents already exist for the calling tenant.

        Permission note: ``RolePermissionsMixin`` routes every ``@action``
        — regardless of HTTP method — through ``write_permission``. So
        this GET is gated by ``IsOffice``, NOT ``IsStaff`` (which only
        covers ``list`` / ``retrieve``). That matches the intent: only
        office configures these flags, so only office needs to know
        which ones are locked. If a future use case needs IsStaff (or
        broader) read access without the office gate, add this action
        name to ``public_read_actions`` or split it onto a method-aware
        mixin.
        """
        tenant = getattr(request, "tenant", None)
        if tenant is None or getattr(tenant, "schema_name", "") == "public":
            raise NoTenantContext("No tenant context")

        locked: list[str] = []
        for setting_field, (model_path, _label) in YEAR_BASED_SETTING_TO_MODEL.items():
            from django.utils.module_loading import import_string

            model_class = import_string(model_path)
            if model_class.objects.exists():
                locked.append(setting_field)

        return Response({"locked_settings": locked})


class EmailConfigTestSendThrottle(TenantScopedRateThrottle):
    """Scope-bound throttle for the ``test_email`` action.

    Attached via ``@action(throttle_classes=[...])`` so the scope
    applies only to the test-send action, not the rest of the
    viewset's endpoints (which would otherwise share the rate
    budget). The scope name matches
    ``DEFAULT_THROTTLE_RATES["email_test_send"]`` and is shared with
    the notification-template test-send — both are "send a test
    email" capabilities, so one combined budget per user is the
    point, not an accident.
    """

    scope = "email_test_send"


class TenantEmailConfigViewSet(RolePermissionsMixin, viewsets.GenericViewSet):
    """
    Manage the tenant's email sending configuration.
    Credentials are write-only — submitted once, encrypted at rest, never returned.

    Office-only on both read and write: SMTP credentials are sensitive
    even when individual password fields are encrypted, and the ``test/``
    @action sends an email to any caller-supplied address (spam vector
    if open to every authenticated tenant user).

    The config is a per-tenant singleton, so the surface is deliberately
    collection-level only: ``list`` (returns THE config object, not an
    array), ``save/`` and ``test/``. A ModelViewSet here previously
    exposed ``{id}`` detail routes whose pk was ignored and a POST
    ``create`` that could never succeed (``tenant`` is read-only +
    NOT NULL → guaranteed IntegrityError).
    """

    read_permission = IsOffice
    write_permission = IsOffice

    serializer_class = TenantEmailConfigSerializer

    def get_queryset(self) -> QuerySet[TenantEmailConfig]:
        tenant = getattr(self.request, "tenant", None)
        if not tenant or tenant.schema_name == "public":
            return TenantEmailConfig.objects.none()
        return TenantEmailConfig.objects.filter(tenant=tenant)

    def get_object(self) -> TenantEmailConfig:
        """Always operate on the current tenant's config (get-or-create)."""
        tenant = self.request.tenant
        config, _ = TenantEmailConfig.objects.get_or_create(
            tenant=tenant,
            defaults={"from_email": tenant.email or "", "from_name": tenant.name},
        )
        return config

    @extend_schema(
        # Explicit single-object response: spectacular's list-action
        # default would declare ``TenantEmailConfig[]`` while the view
        # returns one object.
        responses={
            200: TenantEmailConfigSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Return the single email config for the current tenant."""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @extend_schema(
        request=TenantEmailConfigSerializer,
        responses={
            200: TenantEmailConfigSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["put", "patch"], url_path="save")
    def save_config(self, request: Request) -> Response:
        """PUT/PATCH the singleton email config without requiring a pk in the URL."""
        instance = self.get_object()
        partial = request.method == "PATCH"
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(
        request=inline_serializer(
            name="TestEmailRequest",
            fields={
                "to_email": drf_serializers.EmailField(
                    help_text=(
                        "Address to send the test email to. Must be the "
                        "requesting user's own email or the tenant contact "
                        "email."
                    )
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="TestEmailResponse",
                fields={"detail": drf_serializers.CharField()},
            ),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            429: ErrorResponseSerializer,
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="test",
        throttle_classes=[EmailConfigTestSendThrottle],
    )
    def test_email(self, request: Request) -> Response:
        """Send a test email to verify the configuration works."""
        from .errors import (
            EmailConfigNotSetUp,
            TestEmailRecipientMissing,
            TestEmailRecipientNotAllowed,
            TestEmailSendFailed,
        )

        to_email = (request.data.get("to_email") or "").strip()
        if not to_email:
            raise TestEmailRecipientMissing("to_email is required")

        config = self.get_object()
        if not config.from_email:
            raise EmailConfigNotSetUp("Email config is not set up yet")

        # A compromised office account must not be able to use the
        # tenant's SMTP as a spam relay: test sends only go to the
        # requesting user's own email or the tenant's contact address.
        # ``from_email`` / ``reply_to_email`` are deliberately NOT in
        # this set — they are writable by the same office role via
        # ``save_config``, so allowing them would reduce the lock to
        # a two-request bypass (PATCH reply_to, then POST test).
        # ``tenant.email`` requires IsAdmin to change, so it stays.
        allowed_recipients = {
            address.strip().lower()
            for address in (
                request.user.email,
                getattr(config.tenant, "email", None),
            )
            if address
        }
        if to_email.lower() not in allowed_recipients:
            logger.warning(
                "email_config.test_recipient_rejected tenant=%s actor=%s recipient=%s",
                config.tenant_id,
                request.user.pk,
                to_email,
            )
            raise TestEmailRecipientNotAllowed(
                "Test emails can only be sent to your own account email "
                "or the tenant contact email."
            )

        logger.info(
            "email_config.test_send tenant=%s actor=%s recipient=%s",
            config.tenant_id,
            request.user.pk,
            to_email,
        )

        from .email_service import EmailService

        # Route the test send through ``EmailService.send_email`` so
        # it gets a proper EmailLog row (recipient + subject + status
        # + sent_at). A direct-EmailMessage path would bypass EmailLog,
        # leaving tenants asking "did my test go out?" with no row to
        # query.
        #
        # ``purpose="test:smtp"`` distinguishes it from real sends.
        # The body comes from the registered ``tenants.smtp_test``
        # slug + template — same machinery as every other slug, so
        # tenants can customise the wording in the email-templates UI
        # if they want (it only affects their own future test sends).
        tenant_name = getattr(getattr(config, "tenant", None), "name", "")
        try:
            ok = EmailService().send_email(
                slug="tenants.smtp_test",
                to_emails=[to_email],
                context={"tenant_name": tenant_name},
                purpose="test:smtp",
                related_object_type="tenant_email_config",
                related_object_id=str(config.pk),
            )
        except (smtplib.SMTPException, ConnectionError, OSError, ValueError) as exc:
            # "Send a test email" endpoint — we want to surface whatever
            # SMTP / connection / config error the tenant hit, not crash
            # the request. Narrow to the realistic family of send-time
            # failures so genuine code bugs still surface as a 500.
            logger.error(f"Test email failed for tenant {config.tenant_id}: {exc}")
            raise TestEmailSendFailed(f"Failed to send test email: {exc}") from exc

        if not ok:
            # ``send_email`` returns False on tenant-config / template
            # / SMTP failures it already logged + stamped on the
            # EmailLog row. The EmailLog row carries the specific
            # error string for ops.
            raise TestEmailSendFailed(
                "Failed to send test email — see EmailLog for details."
            )

        config.is_verified = True
        config.save(update_fields=["is_verified"])

        return Response({"detail": f"Test email sent to {to_email}"})
