"""Tenant-facing support-ticket API (staff/office only).

Runs in the tenant request context. Although the model lives in the PUBLIC
schema, django-tenants keeps ``public`` in the search_path, so reads/writes
resolve to the shared table transparently (same as ``ActionRateLog``). The
``get_queryset`` tenant filter is the ENTIRE cross-tenant boundary — every read
path (list / retrieve / reply) must route through it.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import mail_admins
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin, has_any_role
from apps.authz.roles import Role

from .errors import TicketReplyEmpty
from .models import AuthorKind, SupportTicket, SupportTicketMessage, TicketStatus
from .serializers import (
    SupportTicketCreateSerializer,
    SupportTicketDetailSerializer,
    SupportTicketListSerializer,
    SupportTicketReplyRequestSerializer,
)


class SupportTicketViewSet(
    RolePermissionsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    # Any internal role may open + reply to a ticket; members/customers can't.
    read_permission = IsStaff
    write_permission = IsStaff

    def get_serializer_class(self):
        if self.action == "list":
            return SupportTicketListSerializer
        if self.action == "create":
            return SupportTicketCreateSerializer
        return SupportTicketDetailSerializer

    def get_throttles(self):
        # Anti-abuse: an authenticated/stolen staff token could loop create →
        # flood the public table AND email-bomb the platform admin over live
        # SMTP. Reads are unthrottled.
        if self.action == "create":
            self.throttle_scope = "support_ticket_create"
        elif self.action == "reply":
            self.throttle_scope = "support_ticket_reply"
        else:
            self.throttle_scope = None
        return super().get_throttles()

    def get_queryset(self):
        # drf-spectacular introspects with no tenant context.
        if getattr(self, "swagger_fake_view", False):
            return SupportTicket.objects.none()
        schema = self.request.tenant.schema_name
        qs = SupportTicket.objects.filter(tenant_schema=schema)
        # Visibility: office/admin triage every ticket in the tenant; other
        # staff roles see only their own ("My tickets").
        if not has_any_role(self.request, Role.OFFICE, Role.ADMIN):
            qs = qs.filter(creator_id=str(self.request.user.id))
        return qs.prefetch_related("messages")

    @extend_schema(
        request=SupportTicketCreateSerializer,
        responses=SupportTicketDetailSerializer,
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = self._create_ticket(serializer)
        # Return the full thread (incl. the first message) — CreateModelMixin's
        # default would re-serialize the WRITE serializer, which has no thread.
        return Response(SupportTicketDetailSerializer(ticket).data, status=201)

    def _create_ticket(self, serializer) -> SupportTicket:
        request = self.request
        user = request.user
        schema = request.tenant.schema_name
        # ``description`` is write-only → becomes the first message, not a column.
        description = serializer.validated_data.pop("description")
        with transaction.atomic():
            ticket = serializer.save(
                tenant_schema=schema,
                creator_id=str(user.id),
                creator_name=user.name,
                creator_email=(user.email or ""),
                creator_roles=list(user.roles or []),
                status=TicketStatus.OPEN,
            )
            SupportTicketMessage.objects.create(
                ticket=ticket,
                author_kind=AuthorKind.STAFF,
                author_id=str(user.id),
                author_name=user.name,
                body=description,
            )
        self._notify_admin(ticket, user, schema)
        return ticket

    @staticmethod
    def _notify_admin(ticket: SupportTicket, user, schema: str) -> None:
        # Prod only. Under pytest DEBUG defaults True, so this no-ops in tests;
        # the dedicated email test flips DEBUG=False and mocks mail_admins.
        # Minimal body — NEVER the free-text description (could quote member PII).
        if settings.DEBUG:
            return
        # Collapse internal whitespace/newlines: a subject with a "\n" would make
        # Django build a multi-line Subject header → BadHeaderError (a ValueError,
        # NOT swallowed by fail_silently) → 500 after the ticket already committed.
        safe_subject = " ".join(ticket.subject.split())
        subject = f"[jasmin support] {schema}: {safe_subject}"[:200]
        body = (
            f"New support ticket on tenant '{schema}'.\n"
            f"From: {user.name} <{user.email}> "
            f"(roles={list(user.roles or [])})\n"
            f"Priority: {ticket.priority}\n"
            f"Open the super-admin support page to read the details."
        )
        transaction.on_commit(lambda: mail_admins(subject, body, fail_silently=True))

    @extend_schema(
        request=SupportTicketReplyRequestSerializer,
        responses=SupportTicketDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        # get_object() filters through get_queryset() → cross-tenant / not-mine
        # pk yields 404, never 403 (no existence disclosure).
        ticket = self.get_object()
        req = SupportTicketReplyRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        body = req.validated_data["body"].strip()
        if not body:
            raise TicketReplyEmpty("Reply body must not be empty.")
        with transaction.atomic():
            SupportTicketMessage.objects.create(
                ticket=ticket,
                author_kind=AuthorKind.STAFF,
                author_id=str(request.user.id),
                author_name=request.user.name,
                body=body,
            )
            ticket.save(update_fields=["updated_at"])
        # Re-fetch: get_object() prefetched ``messages``, so the just-created
        # reply isn't in that cached instance's message list.
        fresh = SupportTicket.objects.prefetch_related("messages").get(pk=ticket.pk)
        return Response(SupportTicketDetailSerializer(fresh).data)
