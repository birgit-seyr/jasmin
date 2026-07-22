"""Super-admin (platform) view of every tenant's support tickets.

Runs on the PUBLIC schema behind ``SuperAdminJWTAuthentication`` + ``IsSuperAdmin``
(and, at the gateway, the ``/api/super-admin/`` IP allowlist). Mirrors
``TenantManagementViewSet``: a plain ``ViewSet`` whose bodies wrap public
reads/writes in ``schema_context("public")``. Excluded from ``schema.yml`` (it's
on ``public_urls``), so the platform SPA consumes it via raw axios.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.shared.request_utils import client_ip
from apps.shared.super_admin.permissions import IsSuperAdmin
from apps.shared.super_admin.views.authentication import SuperAdminJWTAuthentication
from apps.shared.tenants.models import Tenant

from .errors import InvalidTicketStatus, TicketNotFound, TicketReplyEmpty
from .models import AuthorKind, SupportTicket, SupportTicketMessage, TicketStatus
from .serializers import (
    SupportTicketAdminDetailSerializer,
    SupportTicketAdminListSerializer,
    SupportTicketReplyRequestSerializer,
    SupportTicketSetStatusRequestSerializer,
)

logger = logging.getLogger("super_admin")


class _SupportAdminPagination(LimitOffsetPagination):
    # A default_limit is required or paginate_queryset() no-ops (and .count is
    # never set). The platform page loads a window and pages, not full history.
    default_limit = 50
    max_limit = 200


class SupportTicketAdminViewSet(ViewSet):
    # BOTH set explicitly — the DRF default would fall back to
    # IsAuthenticated + TenantBoundJWTAuthentication (the wrong principal).
    authentication_classes = [SuperAdminJWTAuthentication]
    permission_classes = [IsSuperAdmin]

    @staticmethod
    def _tenant_names() -> dict:
        # One query for the whole page → no per-row N+1.
        return dict(Tenant.objects.values_list("schema_name", "name"))

    def _get_ticket(self, pk):
        try:
            return SupportTicket.objects.get(pk=pk)
        except SupportTicket.DoesNotExist as exc:
            raise TicketNotFound("Support ticket not found.") from exc

    @extend_schema(responses=SupportTicketAdminListSerializer(many=True))
    def list(self, request):
        with schema_context("public"):
            qs = SupportTicket.objects.all()
            status_param = request.query_params.get("status")
            if status_param:
                if status_param not in TicketStatus.values:
                    raise InvalidTicketStatus(f"Unknown status '{status_param}'.")
                qs = qs.filter(status=status_param)
            tenant_param = request.query_params.get("tenant_schema")
            if tenant_param:
                qs = qs.filter(tenant_schema=tenant_param)
            qs = qs.order_by("tenant_schema", "-created_at")
            paginator = _SupportAdminPagination()
            page = paginator.paginate_queryset(qs, request, view=self)
            data = SupportTicketAdminListSerializer(
                page, many=True, context={"tenant_names": self._tenant_names()}
            ).data
            return paginator.get_paginated_response(data)

    @extend_schema(responses=SupportTicketAdminDetailSerializer)
    def retrieve(self, request, pk=None):
        with schema_context("public"):
            ticket = (
                SupportTicket.objects.prefetch_related("messages").filter(pk=pk).first()
            )
            if ticket is None:
                raise TicketNotFound("Support ticket not found.")
            return Response(
                SupportTicketAdminDetailSerializer(
                    ticket, context={"tenant_names": self._tenant_names()}
                ).data
            )

    @extend_schema(
        request=SupportTicketReplyRequestSerializer,
        responses=SupportTicketAdminDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        req = SupportTicketReplyRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        body = req.validated_data["body"].strip()
        if not body:
            raise TicketReplyEmpty("Reply body must not be empty.")
        with schema_context("public"):
            ticket = self._get_ticket(pk)
            author_name = (
                f"{request.user.first_name} {request.user.last_name}".strip()
                or request.user.email
            )
            with transaction.atomic():
                SupportTicketMessage.objects.create(
                    ticket=ticket,
                    author_kind=AuthorKind.SUPER_ADMIN,
                    author_id=str(request.user.id),
                    author_name=author_name,
                    body=body,
                )
                ticket.save(update_fields=["updated_at"])
            logger.info(
                "support.reply actor=%s ip=%s tenant=%s ticket=%s",
                request.user.id,
                client_ip(request),
                ticket.tenant_schema,
                ticket.id,
            )
            return Response(
                SupportTicketAdminDetailSerializer(
                    ticket, context={"tenant_names": self._tenant_names()}
                ).data
            )

    @extend_schema(
        request=SupportTicketSetStatusRequestSerializer,
        responses=SupportTicketAdminDetailSerializer,
    )
    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        req = SupportTicketSetStatusRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        new_status = req.validated_data["status"]
        with schema_context("public"):
            ticket = self._get_ticket(pk)
            old_status = ticket.status
            ticket.status = new_status
            if new_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                ticket.resolved_at = ticket.resolved_at or timezone.now()
            else:
                ticket.resolved_at = None
            ticket.save(update_fields=["status", "resolved_at", "updated_at"])
            logger.info(
                "support.set_status actor=%s ip=%s tenant=%s ticket=%s %s->%s",
                request.user.id,
                client_ip(request),
                ticket.tenant_schema,
                ticket.id,
                old_status,
                new_status,
            )
            return Response(
                SupportTicketAdminDetailSerializer(
                    ticket, context={"tenant_names": self._tenant_names()}
                ).data
            )
