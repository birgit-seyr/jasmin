"""DRF API for tenant-editable email templates.

Endpoints (all under ``/api/notifications/email-templates/``, mounted in
``apps/notifications/urls.py``):

    GET    .../                       List every template (with default
                                      vs. customized status, variables).
    GET    .../<slug>/                Retrieve a single template (current
                                      effective subject/body).
    PATCH  .../<slug>/                Update subject/body — sets
                                      ``is_customized=True``.
    POST   .../<slug>/reset/          Drop the override; revert to the
                                      shipped default.
    POST   .../<slug>/test_send/      Send a real email to the requesting
                                      user (or a passed recipient).

Authorization: only ``IsAdmin`` (tenant admins). The endpoints work in
the active tenant schema, so each tenant's overrides stay isolated.
"""

from __future__ import annotations

import logging
from typing import Any

from django.template.loader import render_to_string
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsAdmin, IsOffice, RolePermissionsMixin
from apps.shared.query_params import validate_choice_param
from core.errors import NotFoundError
from core.pagination import OptionalLimitOffsetPagination
from core.serializers import ErrorResponseSerializer
from core.throttling import TenantScopedRateThrottle

from .errors import (
    EmailDispatchFailed,
    EmailTemplateNotFound,
    TestSendNoRecipient,
)
from .models import BackgroundJob, EmailLog, EmailTemplate
from .registry import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    EmailTemplateSpec,
    all_specs,
    get_spec,
    normalize_language,
    template_path,
)
from .serializers import (
    BackgroundJobSerializer,
    EmailLogSerializer,
    EmailTemplateDetailSerializer,
    EmailTemplateListItemSerializer,
    EmailTemplateTestSendResponseSerializer,
    EmailTemplateUpdateSerializer,
    TestSendSerializer,
)

logger = logging.getLogger(__name__)


class EmailTestSendThrottle(TenantScopedRateThrottle):
    """Scope-bound throttle for the per-template ``test_send`` action.

    DRF's ``ScopedRateThrottle`` keys off ``view.throttle_scope`` for
    function views; on viewset actions we attach a custom throttle
    class via ``@action(throttle_classes=[...])`` so the action
    scope doesn't apply to the rest of the viewset's endpoints
    (which would otherwise share the rate budget). The scope name
    matches ``DEFAULT_THROTTLE_RATES["email_test_send"]``.
    """

    scope = "email_test_send"


# Shared OpenAPI parameter for the ``?language=`` query string. Declared
# here so drf-spectacular surfaces it on every endpoint and orval bakes it
# into the generated client signature.
LANGUAGE_PARAM = OpenApiParameter(
    name="language",
    type=str,
    required=False,
    description="Two-letter language code. Defaults to 'en'.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tenant_language() -> str:
    """Return the current tenant's main language, or DEFAULT_LANGUAGE.

    Uses ``connection.tenant`` (django-tenants) which is set on every
    request in a tenant schema. Falls back gracefully when not running
    inside a tenant context (e.g. during tests).
    """
    try:
        from django.db import connection

        tenant = getattr(connection, "tenant", None)
        raw = getattr(tenant, "tenant_language", None)
        lang = normalize_language(raw)
        logger.info(
            "email_templates: tenant=%s tenant_language=%r resolved=%r",
            getattr(tenant, "schema_name", "?"),
            raw,
            lang,
        )
        if lang:
            return lang
    except (AttributeError, ValueError, TypeError):
        # Tenant context is missing / mis-shaped (test setup, public
        # schema, etc.) — fall back to DEFAULT_LANGUAGE. Any other
        # exception is a real bug worth crashing on.
        logger.exception("email_templates: failed to resolve tenant language")
    return DEFAULT_LANGUAGE


def _resolve_language(request: Request) -> str:
    """Pick the language from ``?language=`` or fall back to tenant default."""
    explicit = normalize_language(request.query_params.get("language"))
    if explicit:
        return explicit
    return _tenant_language()


def _read_default(spec: EmailTemplateSpec, language: str) -> tuple[str, str]:
    """Read the shipped default ``.<lang>.html`` / ``.<lang>.txt`` raw.

    Falls back to the default language file if the requested language
    isn't shipped.
    """
    from django.template import TemplateDoesNotExist, TemplateSyntaxError

    def _read(ext: str) -> str:
        for lang in (language, DEFAULT_LANGUAGE):
            path = template_path(spec.default_template, lang, ext)
            try:
                return render_to_string(path, {})
            except TemplateDoesNotExist:
                logger.info("email_templates: missing %s, trying fallback", path)
                continue
            except (TemplateSyntaxError, ValueError, TypeError, OSError):
                # A real syntax/render error — log loudly so we don't
                # silently fall back to the wrong language.
                logger.exception(
                    "email_templates: render error for %s — falling back", path
                )
                continue
        return ""

    return _read("html"), _read("txt")


def _serialize_detail(
    spec: EmailTemplateSpec,
    override: EmailTemplate | None,
    language: str,
) -> dict[str, Any]:
    default_html, default_text = _read_default(spec, language)
    is_customized = bool(override and override.is_customized)
    # Language-aware default subject — mirror EmailService._resolve_template so
    # the editor shows the English default when ?language=en, not always German.
    default_subject = (
        spec.default_subject_en
        if language == "en" and spec.default_subject_en
        else spec.default_subject
    )
    return {
        "slug": spec.slug,
        "label": spec.label,
        "description": spec.description,
        "language": language,
        "available_languages": list(SUPPORTED_LANGUAGES),
        "subject": (
            override.subject if is_customized and override.subject else default_subject
        ),
        "body_html": (override.body_html if is_customized else default_html),
        "body_text": (override.body_text if is_customized else default_text),
        "default_subject": default_subject,
        "default_body_html": default_html,
        "default_body_text": default_text,
        "is_customized": is_customized,
        "updated_at": override.updated_at if override else None,
        "variables": [
            {"name": v.name, "label": v.label, "description": v.description}
            for v in spec.variables
        ],
    }


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------


class EmailTemplateViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """Tenant admin CRUD for email templates."""

    read_permission = IsAdmin
    write_permission = IsAdmin
    lookup_field = "slug"
    lookup_value_regex = r"[\w.]+"

    @extend_schema(
        operation_id="notifications_email_templates_list",
        tags=["notifications"],
        responses={
            200: EmailTemplateListItemSerializer(many=True),
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def list(self, request: Request) -> Response:
        overrides = EmailTemplate.objects.all()
        # Group customized languages per slug.
        custom_by_slug: dict[str, list[str]] = {}
        latest_update: dict[str, Any] = {}
        for ov in overrides:
            if ov.is_customized:
                custom_by_slug.setdefault(ov.slug, []).append(ov.language)
            prev = latest_update.get(ov.slug)
            if prev is None or (ov.updated_at and ov.updated_at > prev):
                latest_update[ov.slug] = ov.updated_at
        items = []
        for spec in all_specs():
            slug = spec.slug
            items.append(
                {
                    "slug": slug,
                    "label": spec.label,
                    "description": spec.description,
                    "category": spec.category,
                    "available_languages": list(SUPPORTED_LANGUAGES),
                    "customized_languages": sorted(custom_by_slug.get(slug, [])),
                    "updated_at": latest_update.get(slug),
                }
            )
        return Response(items)

    @extend_schema(
        operation_id="notifications_email_templates_retrieve",
        tags=["notifications"],
        parameters=[LANGUAGE_PARAM],
        responses={
            200: EmailTemplateDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request: Request, slug: str) -> Response:
        try:
            spec = get_spec(slug)
        except KeyError as exc:
            raise EmailTemplateNotFound(
                f"Email template '{slug}' does not exist."
            ) from exc
        language = _resolve_language(request)
        override = EmailTemplate.objects.filter(slug=slug, language=language).first()
        return Response(_serialize_detail(spec, override, language))

    @extend_schema(
        operation_id="notifications_email_templates_partial_update",
        tags=["notifications"],
        parameters=[LANGUAGE_PARAM],
        request=EmailTemplateUpdateSerializer,
        responses={
            200: EmailTemplateDetailSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def partial_update(self, request: Request, slug: str) -> Response:
        try:
            spec = get_spec(slug)
        except KeyError as exc:
            raise EmailTemplateNotFound(
                f"Email template '{slug}' does not exist."
            ) from exc
        ser = EmailTemplateUpdateSerializer(
            data=request.data, partial=True, context={"spec": spec}
        )
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        language = _resolve_language(request)

        override, _ = EmailTemplate.objects.get_or_create(slug=slug, language=language)
        if "subject" in data:
            override.subject = data["subject"]
        if "body_html" in data:
            override.body_html = data["body_html"]
        if "body_text" in data:
            override.body_text = data["body_text"]
        override.is_customized = True
        override.updated_by = request.user if request.user.is_authenticated else None
        override.save()
        return Response(_serialize_detail(spec, override, language))

    @extend_schema(
        operation_id="notifications_email_templates_reset",
        tags=["notifications"],
        parameters=[LANGUAGE_PARAM],
        request=None,
        responses={
            200: EmailTemplateDetailSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def reset(self, request: Request, slug: str) -> Response:
        """Discard the tenant override for the requested language."""
        try:
            spec = get_spec(slug)
        except KeyError as exc:
            raise EmailTemplateNotFound(
                f"Email template '{slug}' does not exist."
            ) from exc
        language = _resolve_language(request)
        EmailTemplate.objects.filter(slug=slug, language=language).delete()
        return Response(_serialize_detail(spec, None, language))

    @extend_schema(
        operation_id="notifications_email_templates_test_send",
        tags=["notifications"],
        parameters=[LANGUAGE_PARAM],
        request=TestSendSerializer,
        responses={
            200: EmailTemplateTestSendResponseSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
            502: ErrorResponseSerializer,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="test_send",
        throttle_classes=[EmailTestSendThrottle],
    )
    def test_send(self, request: Request, slug: str) -> Response:
        """Send a real email to the requesting user (or a custom recipient)
        using the current saved template + sample context."""
        try:
            spec = get_spec(slug)
        except KeyError as exc:
            raise EmailTemplateNotFound(
                f"Email template '{slug}' does not exist."
            ) from exc

        ser = TestSendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        recipient = ser.validated_data.get("recipient") or request.user.email
        if not recipient:
            raise TestSendNoRecipient("No recipient available.")

        from apps.shared.tenants.email_service import EmailService

        ok = EmailService().send_email(
            slug=slug,
            to_emails=[recipient],
            context=dict(spec.sample),
            purpose=f"test:{slug}",
            language=_resolve_language(request),
        )
        if not ok:
            raise EmailDispatchFailed("Failed to send test email — check server logs.")
        return Response({"detail": f"Test email sent to {recipient}."})


class BackgroundJobViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """Polling endpoint for ``BackgroundJob`` rows.

    Read-only; rows are created by the views that enqueue work and
    updated by Huey workers. Office staff can poll any job in their
    tenant — finer-grained "only the job I started" filtering is
    deliberate non-MVP (the table is tenant-scoped, so cross-tenant
    leakage is impossible at the schema level).
    """

    read_permission = IsOffice
    write_permission = IsOffice
    lookup_field = "pk"

    @extend_schema(
        operation_id="notifications_jobs_retrieve",
        tags=["notifications"],
        responses={
            200: BackgroundJobSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        try:
            job = BackgroundJob.objects.get(pk=pk)
        except (BackgroundJob.DoesNotExist, ValueError) as exc:
            # ``ValueError`` covers the case where ``pk`` isn't a valid
            # UUID — return a clean 404 either way; we don't want to
            # leak the "exists vs malformed" distinction.
            raise NotFoundError("Job not found") from exc
        return Response(BackgroundJobSerializer(job).data)


class EmailLogViewSet(RolePermissionsMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only audit log of every outbound email in this tenant.

    Supports filter params:
      * ``recipient`` — case-insensitive partial match
      * ``purpose``   — exact slug (e.g. ``commissioning.invoice``)
      * ``status``    — exact status choice (sent, failed, bounced, …)
    """

    read_permission = IsOffice
    write_permission = IsOffice
    serializer_class = EmailLogSerializer
    pagination_class = OptionalLimitOffsetPagination

    @extend_schema(
        tags=["notifications"],
        parameters=[
            OpenApiParameter(name="recipient", type=str, required=False),
            OpenApiParameter(name="purpose", type=str, required=False),
            OpenApiParameter(name="status", type=str, required=False),
        ],
        responses={200: EmailLogSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EmailLog.objects.none()

        queryset = EmailLog.objects.all()

        recipient = self.request.query_params.get("recipient")
        purpose = self.request.query_params.get("purpose")
        status_param = self.request.query_params.get("status")

        if recipient:
            queryset = queryset.filter(recipient__icontains=recipient)
        if purpose:
            # ``purpose`` is a free-form CharField (no choices) — passthrough.
            queryset = queryset.filter(purpose=purpose)
        if status_param:
            valid_statuses = {value for value, _label in EmailLog.STATUS_CHOICES}
            validate_choice_param(status_param, valid_statuses, "status")
            queryset = queryset.filter(status=status_param)

        return queryset
