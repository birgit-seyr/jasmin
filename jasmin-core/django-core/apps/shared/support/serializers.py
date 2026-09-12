"""DRF serializers for support tickets.

Serializer module → import DRF plainly (per the repo convention). Identity /
status / tenant fields are stamped SERVER-SIDE in the viewset and are never in a
writable serializer's ``fields`` list.
"""

from __future__ import annotations

import json

from rest_framework import serializers

from .models import SupportTicket, SupportTicketMessage, TicketStatus

# Only these context keys are persisted; everything else the client sends is
# dropped. Query strings are stripped from values so signed ``?st=`` media
# tokens / member ids / reset tokens can't land in the public schema.
_CONTEXT_ALLOWED_KEYS = frozenset(
    {"page_path", "user_agent", "app_version", "viewport", "locale"}
)
_CONTEXT_MAX_BYTES = 4096
_CONTEXT_VALUE_MAX = 512


def sanitize_context(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, raw in value.items():
        if key not in _CONTEXT_ALLOWED_KEYS or not isinstance(raw, str):
            continue
        # Strip query string + fragment, then hard-cap the length.
        stripped = raw.split("?", 1)[0].split("#", 1)[0]
        cleaned[key] = stripped[:_CONTEXT_VALUE_MAX]
    # Byte-cap backstop: if the (already trimmed) blob is still oversized, drop it.
    if len(json.dumps(cleaned)) > _CONTEXT_MAX_BYTES:
        return {}
    return cleaned


class SupportTicketMessageSerializer(serializers.ModelSerializer):
    # ``author_id`` is deliberately NOT exposed: neither frontend uses it, and
    # for a super-admin reply it would leak the platform SuperAdmin's internal
    # pk to tenant staff. Display uses author_name + author_kind only.
    class Meta:
        model = SupportTicketMessage
        fields = ["id", "author_kind", "author_name", "body", "created_at"]
        read_only_fields = fields


class SupportTicketListSerializer(serializers.ModelSerializer):
    # ``tenant_schema`` deliberately NOT exposed to tenant clients (implicit).
    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "status",
            "priority",
            "creator_id",
            "creator_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SupportTicketDetailSerializer(serializers.ModelSerializer):
    messages = SupportTicketMessageSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "status",
            "priority",
            "creator_id",
            "creator_name",
            "context",
            "created_at",
            "updated_at",
            "resolved_at",
            "messages",
        ]
        read_only_fields = fields


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    # The description becomes the ticket's first message (write-only, popped in
    # the viewset before ``save()``).
    description = serializers.CharField(write_only=True)

    class Meta:
        model = SupportTicket
        # EXPLICIT allowlist — never ``__all__``. tenant_schema / creator_* /
        # status are stamped server-side and must stay unwritable.
        fields = ["subject", "priority", "context", "description"]

    def validate_context(self, value):
        return sanitize_context(value)


class SupportTicketReplyRequestSerializer(serializers.Serializer):
    # allow_blank + no trim so the viewset's own ``strip()`` check owns the
    # "empty reply" rule and emits the stable ``support.reply_empty`` code
    # (a plain CharField would trim + reject first, as ``validation_error``).
    body = serializers.CharField(allow_blank=True, trim_whitespace=False)


# ---- Super-admin serializers -----------------------------------------------


class _TenantNameMixin(serializers.Serializer):
    """Resolve tenant_name from a ``{schema_name: name}`` dict passed in
    ``context["tenant_names"]`` (one query for the whole page — no N+1)."""

    tenant_name = serializers.SerializerMethodField()

    def get_tenant_name(self, obj) -> str:
        names = self.context.get("tenant_names", {})
        return names.get(obj.tenant_schema, obj.tenant_schema)


class SupportTicketAdminListSerializer(_TenantNameMixin, serializers.ModelSerializer):
    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "tenant_schema",
            "tenant_name",
            "subject",
            "status",
            "priority",
            "creator_name",
            "creator_email",
            "created_at",
            "updated_at",
        ]


class SupportTicketAdminDetailSerializer(_TenantNameMixin, serializers.ModelSerializer):
    messages = SupportTicketMessageSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "tenant_schema",
            "tenant_name",
            "subject",
            "status",
            "priority",
            "creator_id",
            "creator_name",
            "creator_email",
            "creator_roles",
            "context",
            "created_at",
            "updated_at",
            "resolved_at",
            "messages",
        ]


class SupportTicketSetStatusRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TicketStatus.choices)
