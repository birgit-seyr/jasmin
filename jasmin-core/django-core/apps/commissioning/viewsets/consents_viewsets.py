"""HTTP layer for ConsentDocument + ConsentRecord.

Two viewsets:

  - ``ConsentDocumentViewSet`` — documents are tenant-wide reference
    data. Anyone authenticated can read (the registration UI needs
    the current privacy/SEPA text); only office staff may write.

  - ``ConsentRecordViewSet`` — per-member event log. Members may list
    + create their own records; staff may see any member's. The
    revoke action is exposed as a custom detail action and routes
    through ``ConsentService`` so the Member cache stays in sync.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import ProtectedError
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.errors import PrivilegeRequired
from apps.authz.permissions import (
    IsOffice,
    IsOfficeOrMember,
    RolePermissionsMixin,
    has_any_role,
)
from apps.authz.roles import Role
from apps.shared.request_utils import client_ip
from core.serializers import ErrorResponseSerializer

from ..errors import (
    ConsentDocumentInUse,
    ConsentDocumentNotFound,
    ConsentTargetMemberUnresolved,
    MemberNotFound,
)
from ..models import ConsentDocument, ConsentKind, ConsentRecord, Member
from ..scoping import enforce_privileged, own_member_id, scope_to_member
from ..serializers import (
    ConsentDocumentSerializer,
    ConsentRecordCreateSerializer,
    ConsentRecordRevokeSerializer,
    ConsentRecordSerializer,
    CurrentConsentDocumentQuerySerializer,
)
from ..services import ConsentService
from ..utils.query_params import validate_query_params

logger = logging.getLogger(__name__)


class ConsentDocumentViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """CRUD over consent documents. Reads are PUBLIC — the registration
    wizard is anonymous and needs to display the privacy / SEPA /
    withdrawal text to prospective members before they sign up. Writes
    (publishing a new version) stay office-only.

    ``public_read_actions`` includes ``current`` on top of the default
    ``list`` / ``retrieve`` because the mixin only treats those two as
    reads — without listing ``current`` the wizard would still 403 on
    the document fetch.
    """

    write_permission = IsOffice
    # ``download_pdf`` is a public read like ``retrieve``: the PDF is the same
    # policy text (no member data — the consent event lives on ConsentRecord).
    public_read_actions = frozenset({"list", "retrieve", "current", "download_pdf"})
    serializer_class = ConsentDocumentSerializer
    queryset = ConsentDocument.objects.all()

    def perform_create(self, serializer: Any) -> None:
        document = serializer.save()
        # Render + store the immutable PDF at creation (body is append-only).
        # Best-effort: a render hiccup must not fail publishing the document —
        # ``download_pdf`` regenerates lazily via ensure_pdf if it's missing.
        try:
            document.ensure_pdf()
        except Exception:
            logger.exception("consent.pdf.render_failed doc=%s", document.pk)

    @extend_schema(
        summary="Download the rendered PDF of this consent document version",
        responses={200: OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"])
    def download_pdf(self, request: Request, pk: str | None = None) -> FileResponse:
        document = self.get_object()
        # Idempotent: serves the stored PDF, rendering it once if this older row
        # predates the feature (lazy backfill).
        document.ensure_pdf()
        return FileResponse(
            document.pdf.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=document.pdf_filename,
        )

    @extend_schema(
        responses={
            204: None,
            # ``ConsentDocumentInUse``.
            409: ErrorResponseSerializer,
        },
    )
    def destroy(self, request, *args, **kwargs):
        """Translate ``ProtectedError`` (raised by Django when a row
        is referenced via an on_delete=PROTECT FK) into a clean
        409 with the project's error format. The serializer's
        ``can_be_deleted`` field tells the UI not to offer the
        delete button in the first place — this catch is the
        belt-and-suspenders server-side enforcement.
        """
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            raise ConsentDocumentInUse(
                "This consent document has at least one member consent "
                "attached. Publish a new version instead of deleting."
            ) from exc

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="kind",
                description="Filter by ConsentKind",
                required=False,
                type=str,
                enum=[c[0] for c in ConsentKind.choices],
            ),
            OpenApiParameter(
                name="locale",
                description="Filter by locale (e.g. 'de', 'en')",
                required=False,
                type=str,
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = ConsentDocument.objects.all()
        params = validate_query_params(self.request, optional=["kind", "locale"])
        kind = params["kind"]
        locale = params["locale"]
        if kind:
            qs = qs.filter(kind=kind)
        if locale:
            qs = qs.filter(locale=locale)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="kind",
                description="ConsentKind to look up (required)",
                required=True,
                type=str,
                enum=[c[0] for c in ConsentKind.choices],
            ),
            OpenApiParameter(
                name="locale",
                description="Locale (default 'de')",
                required=False,
                type=str,
            ),
        ],
        responses={
            200: ConsentDocumentSerializer,
            # ``ConsentDocumentNotFound`` — no active document for (kind, locale).
            404: ErrorResponseSerializer,
        },
    )
    @action(detail=False, methods=["get"])
    def current(self, request: Request) -> Response:
        """Return the document currently in force for ``(kind, locale)``.

        This is what a registration form should call to render the
        "I agree to ..." section: the body it gets back is what the
        user sees, and the ``id`` it sends back via POST /consents/
        is what gets recorded as proof.
        """
        params = CurrentConsentDocumentQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        # Raises ConsentDocumentNotFound → 404 via exception handler
        doc = ConsentService.get_current_document(
            kind=params.validated_data["kind"],
            locale=params.validated_data.get("locale", "de"),
        )
        return Response(ConsentDocumentSerializer(doc).data)


class ConsentRecordViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Per-member consent event log.

    ``list`` and ``retrieve`` are scoped — a member-role user only
    ever sees their own consents. Office staff bypass the scope.
    ``create`` always records the consent against the *caller's*
    Member (no spoofing); office staff can pass an explicit
    ``member`` to record on someone else's behalf.
    """

    read_permission = IsOfficeOrMember
    write_permission = IsOfficeOrMember
    serializer_class = ConsentRecordSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="member",
                description=(
                    "Filter by member id. Office staff only — members are "
                    "always scoped to their own consents server-side."
                ),
                required=False,
                type=str,
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = ConsentRecord.objects.select_related("document", "member").all()
        # Optional ?member=<id> filter (staff only — members see only
        # themselves via scope_to_member below).
        member_id = validate_query_params(self.request, optional=["member"])["member"]
        if member_id:
            qs = qs.filter(member_id=member_id)
        # Members may only see/touch their own consents; staff bypass.
        return scope_to_member(qs, self.request, path="member_id")

    @extend_schema(
        request=ConsentRecordCreateSerializer,
        responses={
            201: ConsentRecordSerializer,
            # ``ConsentTargetMemberUnresolved`` — no member could be inferred.
            400: ErrorResponseSerializer,
            # ``PrivilegeRequired`` — non-staff recording on behalf of others.
            403: ErrorResponseSerializer,
            # ``ConsentDocumentNotFound`` / ``MemberNotFound`` — collection
            # POST, no auto-404.
            404: ErrorResponseSerializer,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = ConsentRecordCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            document = ConsentDocument.objects.get(
                pk=payload.validated_data["document_id"]
            )
        except ConsentDocument.DoesNotExist as exc:
            raise ConsentDocumentNotFound(
                f"ConsentDocument {payload.validated_data['document_id']!r} not found."
            ) from exc

        # Determine which Member this consent is for: either the
        # caller (member-role) or an explicit ``member`` override
        # (office-only — refuse to honour for non-staff).
        target_member_id = request.data.get("member") or own_member_id(request)
        if target_member_id is None:
            raise ConsentTargetMemberUnresolved(
                "No target Member could be inferred from the request."
            )
        # Spoof check: a member-role caller MAY include their own
        # member id in the payload, but never anyone else's. Office
        # and admin bypass this — they legitimately record consents
        # on behalf of members during paper-based onboarding.
        if (
            request.data.get("member")
            and str(request.data["member"]) != str(own_member_id(request))
            and not has_any_role(request, Role.OFFICE, Role.ADMIN)
        ):
            raise PrivilegeRequired(
                "Only office staff may record consent on behalf of others."
            )

        try:
            member = Member.objects.get(pk=target_member_id)
        except Member.DoesNotExist as exc:
            raise MemberNotFound(f"Member {target_member_id!r} not found.") from exc

        record = ConsentService.record(
            member=member,
            document=document,
            ip_address=client_ip(request) or None,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return Response(
            ConsentRecordSerializer(record).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        description=(
            "Office only. Consent records are an append-only legal / GDPR "
            "audit trail — members withdraw consent via the soft ``revoke`` "
            "action (which stamps ``revoked_at`` and preserves the row), never "
            "by hard-deleting it. Letting the data subject erase the record "
            "would defeat the GenG/DSGVO proof-of-consent obligation."
        ),
        responses={204: None, 403: ErrorResponseSerializer},
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        enforce_privileged(request, "Only office staff may delete consent records.")
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        request=ConsentRecordRevokeSerializer,
        responses={
            200: ConsentRecordSerializer,
            # ``ConsentAlreadyRevoked``.
            409: ErrorResponseSerializer,
        },
    )
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        """Withdraw a previously-given consent (DSGVO Art. 7(3))."""
        record = self.get_object()  # honours scope_to_member
        payload = ConsentRecordRevokeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        updated = ConsentService.revoke(
            record,
            reason=payload.validated_data.get("reason", ""),
            revoked_by=request.user if request.user.is_authenticated else None,
        )
        return Response(ConsentRecordSerializer(updated).data)
