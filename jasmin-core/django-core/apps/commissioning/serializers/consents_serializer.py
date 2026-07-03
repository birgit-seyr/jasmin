"""Serializers for ConsentDocument and ConsentRecord.

The write side is intentionally narrow: the only way to *create* a
ConsentRecord through the API is to POST ``{document_id}`` — IP and
user-agent are derived from the request server-side, and ``member`` is
inferred from the URL nested under members. That keeps the audit trail
honest: nobody can spoof a consent timestamp or impersonate a member.

Convention: NO ``fields = "__all__"`` in this file (or any user-facing
serializer in this project). The explicit list means that adding a
new column to the model never silently widens the public API surface.
Concrete failure mode without it: if someone adds an ``internal_notes``
column to ``ConsentDocument``, ``"__all__"`` would auto-expose it via
``GET /api/commissioning/consent_documents/`` — which is AllowAny
because the registration wizard reads it. The explicit list forces a
deliberate "yes, expose this" edit at review time.
"""

from __future__ import annotations

from rest_framework import serializers

from ..models import ConsentDocument, ConsentKind, ConsentRecord
from .serializers_mixin import DeletableMixin


class ConsentDocumentSerializer(DeletableMixin, serializers.ModelSerializer):
    """Read-and-write serializer for ConsentDocument.

    ``body_sha256`` is computed in ``Model.save()`` — never set from
    the wire — so it's marked read-only here. ``valid_until`` is set
    automatically by ``TimeBoundMixin.handle_succession`` when a
    successor is published; we keep it on the wire so the admin UI
    can show "this version was retired on …", but it's read-only.

    ``can_be_deleted`` is injected by ``DeletableMixin`` and answers
    "is any ConsentRecord pointing at this document?" — False once
    any member has consented, True otherwise. The frontend hides the
    delete button when False; the FK's ``on_delete=PROTECT`` enforces
    the same at the DB layer.

    We DO NOT use ``fields = "__all__"`` here on purpose — see the
    module docstring of this file. The explicit list means adding
    a new column to the model never silently widens the public API.
    """

    class Meta:
        model = ConsentDocument
        # ``can_be_deleted`` is INJECTED by ``DeletableMixin.get_fields()``
        # — listing it in ``Meta.fields`` would make ``ModelSerializer``
        # try to resolve it against the model and raise
        # ImproperlyConfigured. It still appears in the response (and
        # in the OpenAPI schema) because drf-spectacular introspects
        # the serializer's runtime ``get_fields()`` output, not Meta.
        fields = [
            "id",
            "kind",
            "version",
            "locale",
            "title",
            "valid_from",
            "valid_until",
            "body",
            "body_sha256",
            "created_at",
        ]
        read_only_fields = ["id", "body_sha256", "valid_until", "created_at"]


class ConsentDocumentSummarySerializer(serializers.ModelSerializer):
    """Thin variant for embedding inside ConsentRecord — omits the full
    body to keep list payloads bounded."""

    class Meta:
        model = ConsentDocument
        fields = ["id", "kind", "version", "locale", "title", "valid_from"]
        read_only_fields = fields


class ConsentRecordSerializer(serializers.ModelSerializer):
    """Read serializer — full document summary embedded so the UI can
    render "you agreed to <title> v<version> on <date>" without a
    second round-trip."""

    document = ConsentDocumentSummarySerializer(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ConsentRecord
        fields = [
            "id",
            "member",
            "document",
            "consented_at",
            "ip_address",
            "user_agent",
            "revoked_at",
            "revoked_reason",
            "revoked_by",
            "is_active",
        ]
        read_only_fields = fields


class ConsentRecordCreateSerializer(serializers.Serializer):
    """Write input for "I agree to this document right now".

    ``member`` is optional and only honoured for office staff — a
    member-role caller is always pinned to their own record (the
    viewset enforces this). IP/user-agent come from the request
    server-side, never from this payload.
    """

    document_id = serializers.CharField()
    member = serializers.CharField(
        required=False,
        help_text="Target Member id. Office staff only; member-role "
        "callers are pinned to their own record server-side.",
    )


class ConsentRecordRevokeSerializer(serializers.Serializer):
    """Optional ``reason`` accompanying a revoke. Free-text; we store
    up to 200 chars for the audit trail."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class CurrentConsentDocumentQuerySerializer(serializers.Serializer):
    """Query params for ``/consent-documents/current/``."""

    kind = serializers.ChoiceField(choices=ConsentKind.choices)
    locale = serializers.CharField(default="de", required=False)
