"""Request / response serializers for the email-template API.

Used by :class:`apps.notifications.viewsets.EmailTemplateViewSet` and
:class:`apps.notifications.viewsets.EmailLogViewSet`.
"""

from __future__ import annotations

from rest_framework import serializers

from .errors import UndeclaredPlaceholders
from .models import EmailLog
from .registry import EmailTemplateSpec
from .template_renderer import (
    find_undeclared_placeholders,
    find_unsafe_placeholders,
)


def _reject_unsafe_placeholders(value: str, field: str) -> str:
    """Reject tenant-edited template fields that reference private/dunder
    paths (``{{ x.__class__ }}``, ``{{ x.save.__globals__... }}``). The
    renderer already refuses to resolve these, but rejecting at write time
    gives the editor a clear error instead of a silently-blank render — and
    keeps the malicious string from ever being persisted."""
    unsafe = find_unsafe_placeholders(value or "")
    if unsafe:
        raise serializers.ValidationError(
            "Disallowed placeholders (private/dunder paths are not "
            f"permitted): {', '.join(sorted(set(unsafe)))}"
        )
    return value


class _SafeTemplateFieldsMixin:
    """Validates the editable template fields:

    * Per field: reject private/dunder placeholders (security).
    * Cross-field (in :meth:`validate`): reject any ``{{ placeholder }}`` that
      is not declared in the slug's registry spec (and is not a trusted raw
      key) — those would render empty with no warning. The spec is passed in
      via ``context["spec"]`` by the viewset.
    """

    _EDITABLE_FIELDS = ("subject", "body_html", "body_text")

    def validate_subject(self, value: str) -> str:
        return _reject_unsafe_placeholders(value, "subject")

    def validate_body_html(self, value: str) -> str:
        return _reject_unsafe_placeholders(value, "body_html")

    def validate_body_text(self, value: str) -> str:
        return _reject_unsafe_placeholders(value, "body_text")

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)  # type: ignore[misc]
        spec: EmailTemplateSpec | None = self.context.get("spec")  # type: ignore[attr-defined]
        if spec is None:
            # No spec in context → can't check declarations. The viewset always
            # supplies one; this guard keeps the serializer usable standalone.
            return attrs
        declared = frozenset(variable.name for variable in spec.variables)
        offending: list[str] = []
        for field in self._EDITABLE_FIELDS:
            if field not in attrs:
                continue
            offending.extend(find_undeclared_placeholders(attrs[field] or "", declared))
        if offending:
            # De-duplicate, preserve first-seen order.
            seen: set[str] = set()
            unique = [p for p in offending if not (p in seen or seen.add(p))]
            raise UndeclaredPlaceholders(
                "The template references variables that are not available for "
                f"this email: {', '.join(unique)}.",
                details={"placeholders": unique},
            )
        return attrs


class EmailLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailLog
        fields = [
            "id",
            "recipient",
            "subject",
            "template",
            "purpose",
            "status",
            "error",
            "related_object_type",
            "related_object_id",
            "created_at",
            "sent_at",
            "delivered_at",
        ]
        read_only_fields = fields


class EmailTemplateVariableSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField(allow_blank=True)


class EmailTemplateListItemSerializer(serializers.Serializer):
    slug = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    available_languages = serializers.ListField(child=serializers.CharField())
    customized_languages = serializers.ListField(child=serializers.CharField())
    updated_at = serializers.DateTimeField(allow_null=True)


class EmailTemplateDetailSerializer(serializers.Serializer):
    slug = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    language = serializers.CharField()
    available_languages = serializers.ListField(child=serializers.CharField())
    subject = serializers.CharField()
    body_html = serializers.CharField()
    body_text = serializers.CharField()
    default_subject = serializers.CharField()
    default_body_html = serializers.CharField()
    default_body_text = serializers.CharField()
    is_customized = serializers.BooleanField()
    updated_at = serializers.DateTimeField(allow_null=True)
    variables = EmailTemplateVariableSerializer(many=True)


class EmailTemplateUpdateSerializer(_SafeTemplateFieldsMixin, serializers.Serializer):
    """All fields optional: the view always runs this with
    ``partial=True`` (PATCH semantics), and passing an explicit
    ``request=`` to extend_schema bypasses spectacular's auto
    ``Patched*`` all-optional component — required fields here would
    force generated clients to always send the full template."""

    subject = serializers.CharField(allow_blank=True, max_length=512, required=False)
    body_html = serializers.CharField(allow_blank=True, required=False)
    body_text = serializers.CharField(allow_blank=True, required=False)


class EmailTemplateTestSendResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class TestSendSerializer(serializers.Serializer):
    recipient = serializers.EmailField(required=False)


class BackgroundJobSerializer(serializers.Serializer):
    """Snapshot of a ``BackgroundJob`` row for the polling endpoint.

    Shape is intentionally generic — ``progress`` and ``result`` are
    free-form JSON the task wrote at run-time; the frontend interprets
    them based on ``kind``.
    """

    id = serializers.UUIDField(read_only=True)
    kind = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    progress = serializers.JSONField(read_only=True)
    result = serializers.JSONField(read_only=True)
    error = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True, allow_null=True)
