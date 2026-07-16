"""Support-ticket models — PUBLIC schema (this app is a SHARED_APP).

A single ``public.support_ticket`` table holds every tenant's tickets so the
super-admin can aggregate them in one indexed query. Mirrors the
``ActionRateLog`` precedent (apps/shared/tenants/models.py): the tenant is keyed
by its ``schema_name`` STRING, NOT an FK to ``Tenant`` — a public→Tenant FK adds
a commit-time constraint a schema-only ``FakeTenant`` (background
``schema_context`` work) and pytest ``transaction=True`` flushes can't satisfy,
and there is nothing referentially to enforce. The author is a tenant-schema
``JasminUser`` (STR pk in another schema), so no cross-schema FK is possible; we
snapshot id/name/email/roles instead.
"""

from __future__ import annotations

from django.db import models

from apps.shared.tenants.models import ID_LENGTH, JasminModel


class TicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class TicketPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"


class AuthorKind(models.TextChoices):
    STAFF = "staff", "Staff"
    SUPER_ADMIN = "super_admin", "Super admin"


class SupportTicket(JasminModel):
    # Tenant.schema_name (a Postgres identifier, ≤63 chars). NOT an FK — see
    # the module docstring.
    tenant_schema = models.CharField(max_length=63, db_index=True)
    subject = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=10,
        choices=TicketPriority.choices,
        default=TicketPriority.NORMAL,
    )
    # Creator snapshot (tenant-schema JasminUser; no cross-schema FK possible).
    creator_id = models.CharField(max_length=ID_LENGTH)
    creator_name = models.CharField(max_length=255, blank=True, default="")
    creator_email = models.CharField(max_length=254, blank=True, default="")
    creator_roles = models.JSONField(default=list, blank=True)
    # Allowlisted, size-capped client context (page_path / user_agent /
    # app_version / viewport / locale). Sanitized in
    # ``SupportTicketCreateSerializer.validate_context`` — query strings are
    # stripped so signed ``?st=`` media tokens / ids never land in public.
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["tenant_schema", "-created_at"]
        indexes = [
            # Serves the tenant list query filter(tenant_schema=…).order_by(-created_at)
            models.Index(
                fields=["tenant_schema", "-created_at"],
                name="support_ticket_tenant_idx",
            ),
            # Serves the super-admin ?status= filter.
            models.Index(fields=["status"], name="support_ticket_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_schema}:{self.subject[:40]}"


class SupportTicketMessage(JasminModel):
    # Intra-app FK (both public) → safe. The ticket's FIRST message is the
    # original description, so the thread is uniform.
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author_kind = models.CharField(max_length=12, choices=AuthorKind.choices)
    # JasminUser id (staff) or SuperAdmin id — snapshot, no cross-schema FK.
    author_id = models.CharField(max_length=ID_LENGTH, blank=True, default="")
    author_name = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.author_kind}@{self.created_at:%Y-%m-%d %H:%M}"
