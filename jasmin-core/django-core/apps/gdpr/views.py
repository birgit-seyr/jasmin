from __future__ import annotations

import logging

from django.db import connection
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import RequiresStepUp
from apps.authz.permissions import IsAdmin
from apps.shared.request_utils import client_ip
from core.serializers import ErrorResponseSerializer

from .errors import MissingRejectionReason
from .models import DeletionLog, DeletionRequest, DeletionRequestState
from .serializers import (
    AdminDecidedDeletionSerializer,
    AdminPendingDeletionListSerializer,
    DeletionLogListSerializer,
    MyDeletionStatusSerializer,
    ProcessingActivitiesSerializer,
    SubjectAccessBundleSerializer,
)
from .services import (
    GDPRService,
    send_deletion_approved_email,
    send_deletion_confirmation_email,
    send_deletion_rejected_email,
)

logger = logging.getLogger("gdpr")


@extend_schema(
    tags=["gdpr"],
    summary="Subject Access Request bundle for the current user (Art. 15)",
    responses={
        200: SubjectAccessBundleSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def gdpr_my_data_view(request: Request) -> Response:
    """Return the full Art-15 Subject Access Request bundle for the
    requesting user — every row tied to their identity (account,
    member, reseller, subscriptions, coop shares, invoices,
    email log, login history, …). See
    :class:`apps.gdpr.serializers.SubjectAccessBundleSerializer`
    for the schema; the section list lives on
    :meth:`apps.gdpr.services.GDPRService.get_subject_access_bundle`."""
    bundle = GDPRService.get_subject_access_bundle(request.user)
    serializer = SubjectAccessBundleSerializer(bundle)
    logger.info(
        "gdpr.sar_exported user=%s tenant=%s ip=%s",
        request.user.email,
        connection.schema_name,
        client_ip(request),
    )
    return Response(serializer.data)


gdpr_my_data_view.cls.throttle_scope = "gdpr_sar_export"


# ---------------------------------------------------------------------------
# Two-step deletion flow.
#
# - ``gdpr_request_deletion_view`` no longer anonymizes directly. It
#   creates a ``DeletionRequest(PENDING_EMAIL)`` and sends a 24h
#   confirmation link.
# - ``gdpr_confirm_deletion_view`` accepts the token. If the request
#   doesn't need admin approval, anonymization runs right away.
# - ``gdpr_admin_approve_deletion_view`` / ``..._reject_deletion_view``
#   are the office-side endpoints used when the admin gate is on.
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["gdpr"],
    summary="Request deletion of personal data (Art. 17) — step 1 (email confirm)",
    request=None,
    responses={
        202: inline_serializer(
            name="DeletionRequestAccepted",
            fields={
                "message": drf_serializers.CharField(),
                "request_id": drf_serializers.CharField(),
                "requires_admin_approval": drf_serializers.BooleanField(),
            },
        ),
        401: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def gdpr_request_deletion_view(request: Request) -> Response:
    """Kick off a GDPR deletion request.

    Creates a pending ``DeletionRequest`` and emails the user a 24h
    confirmation link. NEVER anonymizes immediately — that only
    happens after the user clicks the link (and, if the tenant /
    persona requires it, the office approves).
    """
    deletion_request = GDPRService.request_deletion(
        request.user, requested_ip=client_ip(request)
    )
    send_deletion_confirmation_email(request.user, deletion_request)

    logger.info(
        "gdpr.deletion_request_created user=%s request_id=%s "
        "requires_admin=%s tenant=%s ip=%s",
        request.user.email,
        deletion_request.pk,
        deletion_request.requires_admin_approval,
        connection.schema_name,
        client_ip(request),
    )
    return Response(
        {
            "message": (
                "We have sent a confirmation link to your email. "
                "Please open it within 24 hours to confirm the deletion."
            ),
            "request_id": str(deletion_request.pk),
            "requires_admin_approval": deletion_request.requires_admin_approval,
        },
        status=status.HTTP_202_ACCEPTED,
    )


gdpr_request_deletion_view.cls.throttle_scope = "gdpr_request_deletion"


@extend_schema(
    tags=["gdpr"],
    summary="Confirm a deletion request via the emailed token — step 2",
    request=None,
    parameters=[
        OpenApiParameter(
            name="token",
            location=OpenApiParameter.PATH,
            type=str,
            description="UUID token from the deletion-confirmation email.",
        )
    ],
    responses={
        200: inline_serializer(
            name="DeletionConfirmed",
            fields={
                "message": drf_serializers.CharField(),
                "state": drf_serializers.CharField(),
            },
        ),
        404: ErrorResponseSerializer,
        409: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
def gdpr_confirm_deletion_view(request: Request, token: str) -> Response:
    """Confirm a pending deletion request.

    ``AllowAny`` because the JWT may already be expired by the time
    the user opens their email — the token IS the proof of identity
    for this endpoint.

    On success the request moves to ``PENDING_ADMIN`` — the office
    reviews and completes the deletion. Confirmation never anonymizes
    synchronously.
    """
    deletion_request = GDPRService.confirm_deletion_token(token, ip=client_ip(request))

    message = (
        "Confirmation received. The office will review the request "
        "and complete the deletion shortly."
    )

    logger.warning(
        "gdpr.deletion_confirmed request_id=%s state=%s tenant=%s ip=%s",
        deletion_request.pk,
        deletion_request.state,
        connection.schema_name,
        client_ip(request),
    )
    return Response({"message": message, "state": str(deletion_request.state)})


gdpr_confirm_deletion_view.cls.throttle_scope = "gdpr_confirm_deletion"


@extend_schema(
    tags=["gdpr"],
    summary="Admin: approve a pending deletion request",
    # No request body — confirmation is the admin's action; any
    # context they want to add goes in the existing audit log.
    request=None,
    parameters=[
        OpenApiParameter(
            name="request_id",
            location=OpenApiParameter.PATH,
            type=str,
        )
    ],
    responses={
        200: inline_serializer(
            name="DeletionApproved",
            fields={
                "message": drf_serializers.CharField(),
                "state": drf_serializers.CharField(),
            },
        ),
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
        404: ErrorResponseSerializer,
        409: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAdmin, RequiresStepUp])
def gdpr_admin_approve_deletion_view(request: Request, request_id: str) -> Response:
    """Admin grants the second gate; deletion executes immediately.

    Gated by step-up auth because GDPR anonymisation is irreversible —
    a stale session left open at a café shouldn't be able to fire it
    without a fresh password re-confirmation.
    """
    deletion_request = _get_pending_request(request_id)
    deletion_request = GDPRService.admin_approve_deletion(
        deletion_request, admin_user=request.user
    )
    # Email after the service transaction has committed — the helper
    # is best-effort, so a mail failure must not roll back the executed
    # deletion. Captured ``requested_email`` survives anonymisation.
    send_deletion_approved_email(deletion_request)
    logger.warning(
        "gdpr.deletion_admin_approved request_id=%s actor=%s tenant=%s ip=%s",
        deletion_request.pk,
        request.user.email,
        connection.schema_name,
        client_ip(request),
    )
    return Response(
        {
            "message": "Deletion approved and executed.",
            "state": str(deletion_request.state),
        }
    )


@extend_schema(
    tags=["gdpr"],
    summary="Admin: reject a pending deletion request",
    request=inline_serializer(
        name="DeletionRejectBody",
        fields={"reason": drf_serializers.CharField()},
    ),
    parameters=[
        OpenApiParameter(
            name="request_id",
            location=OpenApiParameter.PATH,
            type=str,
        )
    ],
    responses={
        200: inline_serializer(
            name="DeletionRejected",
            fields={
                "message": drf_serializers.CharField(),
                "state": drf_serializers.CharField(),
            },
        ),
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
        404: ErrorResponseSerializer,
        409: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@permission_classes([IsAdmin])
def gdpr_admin_reject_deletion_view(request: Request, request_id: str) -> Response:
    """Admin denies the deletion (e.g. spotted a retention obligation,
    user phoned to cancel). The reason is required so the audit trail
    captures it."""
    deletion_request = _get_pending_request(request_id)
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        # 400 (bad input) — distinct from the 409 state errors the service
        # raises. The global handler renders the canonical {code,message}.
        raise MissingRejectionReason("A rejection reason is required.")
    deletion_request = GDPRService.admin_reject_deletion(
        deletion_request, admin_user=request.user, reason=reason
    )
    # Email after the service transaction commits — best-effort.
    send_deletion_rejected_email(deletion_request, reason=reason)
    return Response(
        {
            "message": "Deletion request rejected.",
            "state": str(deletion_request.state),
        }
    )


def _get_pending_request(request_id: str) -> DeletionRequest:
    """Fetch a DeletionRequest by id, 404 if missing. Pulled out
    because both admin endpoints need it."""
    from core.errors import NotFoundError

    try:
        return DeletionRequest.objects.get(pk=request_id)
    except DeletionRequest.DoesNotExist:
        raise NotFoundError("Deletion request not found.") from None


@extend_schema(
    tags=["gdpr"],
    summary="Most recent deletion request for the current user",
    responses={
        200: MyDeletionStatusSerializer,
        401: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def gdpr_my_deletion_status_view(request: Request) -> Response:
    """Return the user's most recent ``DeletionRequest`` so the
    profile can show "your request is pending admin review" or
    "your last request was rejected: <reason>" right above the
    Request Deletion button. Returns null fields when no request
    has ever been lodged."""
    latest = (
        DeletionRequest.objects.filter(user=request.user)
        .order_by("-requested_at")
        .first()
    )
    if latest is None:
        return Response(
            {
                "state": None,
                "requested_at": None,
                "admin_confirmed_at": None,
                "admin_rejection_reason": None,
            }
        )
    return Response(
        {
            "state": str(latest.state),
            "requested_at": latest.requested_at,
            "admin_confirmed_at": latest.admin_confirmed_at,
            "admin_rejection_reason": latest.admin_rejection_reason,
        }
    )


@extend_schema(
    tags=["gdpr"],
    summary="List pending deletion requests awaiting admin approval",
    responses={
        200: AdminPendingDeletionListSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def gdpr_admin_pending_deletions_view(request: Request) -> Response:
    """List ``DeletionRequest`` rows that have passed the email gate
    and are now waiting on an admin to approve or reject.

    Each row carries a ``blockers`` list — the retention obligations
    that would refuse an Approve right now. Empty list = ready to
    approve; non-empty = admin must resolve them first (typically by
    cancelling CoopShares or settling open invoices). Computed
    per-row via ``check_retention_blocks`` so the inbox reflects the
    current state, not whatever was true at request time.

    Returned shape per row: ``id`` (the request_id the approve/reject
    endpoints take), ``requested_email`` (captured at request time —
    survives the user FK being anonymised later), ``requested_at``,
    ``email_confirmed_at``, ``current_user_email``, ``blockers``."""
    pending_requests = list(
        DeletionRequest.objects.filter(state=DeletionRequestState.PENDING_ADMIN)
        .select_related("user")
        .order_by("requested_at")
    )
    # Compute retention blockers for every pending user in a constant number
    # of queries (one grouped COUNT per obligation), not ~5 per request.
    blockers_by_user = GDPRService.check_retention_blocks_bulk(
        [req.user for req in pending_requests if req.user_id]
    )
    pending = [
        {
            "id": req.id,
            "requested_email": req.requested_email,
            "requested_at": req.requested_at,
            "email_confirmed_at": req.email_confirmed_at,
            "current_user_email": req.user.email if req.user_id else None,
            "blockers": blockers_by_user.get(req.user_id, []) if req.user_id else [],
        }
        for req in pending_requests
    ]
    return Response({"pending": pending})


@extend_schema(
    tags=["gdpr"],
    summary="List decided deletion requests (rejected / executed / cancelled / expired)",
    parameters=[
        OpenApiParameter(
            name="limit",
            type=int,
            description="Page size — opt into pagination by passing this.",
            required=False,
        ),
        OpenApiParameter(
            name="offset",
            type=int,
            required=False,
        ),
    ],
    responses={
        # ``OptionalLimitOffsetPagination`` declares the schema as the
        # plain row list — see ``get_paginated_response_schema`` on the
        # paginator. Runtime callers that pass ``?limit=`` still get
        # ``{count, next, previous, results}``; the frontend handles
        # the envelope.
        200: AdminDecidedDeletionSerializer(many=True),
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def gdpr_admin_decided_deletions_view(request: Request) -> Response:
    """History of every deletion request that is no longer actionable —
    REJECTED, EXECUTED, CANCELLED, or EXPIRED. Most-recently-requested
    first. Paginated via the project-standard
    ``OptionalLimitOffsetPagination`` (opt-in via ``?limit=``).

    Each row carries enough to reconstruct the decision without a
    second roundtrip: who decided (``decided_by_email``), when
    (``decided_at`` = ``admin_confirmed_at`` for rejections, the
    earliest of ``executed_at`` / ``admin_confirmed_at`` for
    executions), and the office's rejection reason verbatim."""
    from core.pagination import OptionalLimitOffsetPagination

    decided_states = [
        DeletionRequestState.REJECTED,
        DeletionRequestState.EXECUTED,
        DeletionRequestState.CANCELLED,
        DeletionRequestState.EXPIRED,
    ]
    qs = (
        DeletionRequest.objects.filter(state__in=decided_states)
        .select_related("admin_confirmed_by")
        .order_by("-requested_at")
    )

    def serialize(r: DeletionRequest) -> dict:
        # For executions ``admin_confirmed_at`` is also stamped (the
        # approve step set it), but ``executed_at`` is the more
        # meaningful "decided" moment. For rejections only
        # ``admin_confirmed_at`` is set. Cancelled/expired never go
        # through admin — ``decided_at`` is None there.
        if r.state == DeletionRequestState.EXECUTED:
            decided_at = r.executed_at or r.admin_confirmed_at
        elif r.state == DeletionRequestState.REJECTED:
            decided_at = r.admin_confirmed_at
        else:
            decided_at = None
        return {
            "id": r.id,
            "state": str(r.state),
            "requested_email": r.requested_email,
            "requested_at": r.requested_at,
            "decided_at": decided_at,
            "decided_by_email": (
                r.admin_confirmed_by.email if r.admin_confirmed_by_id else None
            ),
            "rejection_reason": r.admin_rejection_reason or None,
        }

    paginator = OptionalLimitOffsetPagination()
    page = paginator.paginate_queryset(qs, request)
    if page is None:
        return Response([serialize(r) for r in qs])
    return paginator.get_paginated_response([serialize(r) for r in page])


@extend_schema(
    tags=["gdpr"],
    summary="List deletion log (admin only)",
    responses={
        200: DeletionLogListSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def gdpr_deletion_log_view(request: Request) -> Response:
    """List all GDPR deletion events (for tenant admins)."""
    logs = DeletionLog.objects.all().values(
        "id", "user_email", "deleted_at", "description"
    )
    logger.info(
        "gdpr.deletion_log_accessed actor=%s tenant=%s ip=%s",
        request.user.email,
        connection.schema_name,
        client_ip(request),
    )
    return Response({"deletions": list(logs)})


@extend_schema(
    tags=["gdpr"],
    summary=("Art. 30 Record of Processing Activities (VVT) — structured " "export"),
    description=(
        "Returns the tenant's Record of Processing Activities in the "
        "Art. 30 shape: a controller block (organisation identity), "
        "the list of joint controllers / processors the codebase "
        "relies on, the per-activity records (purpose / legal basis "
        "/ data subjects / personal data / source / recipients / "
        "third-country transfers / retention / security measures / "
        "code locations), and the Art. 32 Technical & Organisational "
        "Measures.\n\n"
        "Code-level facts come from ``apps/gdpr/vvt.py`` (in-repo "
        "constants). Tenant-specific overlays (controller name, "
        "address, contact, supervisory authority, AVV-on-file flags) "
        "come from the live ``Tenant`` row + the request body of a "
        "future PUT endpoint (not yet implemented — the prose "
        "``docs/gdpr/processing-activities.md`` is still the source "
        "for the operational fill-ins). Auditor question 'show me "
        "your VVT for tenant X' is answered by GET-ting this endpoint."
    ),
    responses={
        200: ProcessingActivitiesSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def gdpr_processing_activities_view(request: Request) -> Response:
    """Art. 30 VVT export — see decorator description for the contract."""
    from django.utils import timezone

    from . import vvt

    tenant = getattr(connection, "tenant", None)

    # Controller block: pull every field we know the tenant has on
    # ``Tenant``. legal_form / DPO / data-protection contact / supervisory
    # authority are writable on the Tenant model (the office fills them in
    # ConfigurationGDPR) and read here; empty until the tenant fills them.
    controller = {
        "organisation_name": getattr(tenant, "name", "") or "",
        "legal_form": getattr(tenant, "legal_form", "") or "",
        "registered_address": " ".join(
            filter(
                None,
                [
                    getattr(tenant, "address", "") or "",
                    " ".join(
                        filter(
                            None,
                            [
                                getattr(tenant, "zip_code", "") or "",
                                getattr(tenant, "city", "") or "",
                            ],
                        )
                    ),
                    getattr(tenant, "country", "") or "",
                ],
            )
        ).strip(),
        "contact_email": getattr(tenant, "email", "") or "",
        "contact_phone": getattr(tenant, "phone_number", "") or "",
        "data_protection_contact": getattr(tenant, "data_protection_contact", "") or "",
        "dpo": getattr(tenant, "dpo", "") or "",
        "supervisory_authority": getattr(tenant, "supervisory_authority", "") or "",
    }

    payload = {
        # Versioned so a consumer (the office UI, an external audit
        # tool) can detect schema bumps without re-deriving from the
        # prose doc.
        "schema_version": "1",
        # The prose source of truth — auditors who want narrative
        # context should read this. The endpoint just gives them the
        # structured view.
        "doc_reference": "docs/gdpr/processing-activities.md",
        "generated_at": timezone.now(),
        "controller": controller,
        "processors": vvt.PROCESSORS,
        "activities": vvt.activity_dicts(),
        "technical_organisational_measures": vvt.TOMS,
    }

    logger.info(
        "gdpr.vvt_exported actor=%s tenant=%s ip=%s",
        getattr(request.user, "email", "-"),
        connection.schema_name,
        client_ip(request),
    )
    return Response(payload)
