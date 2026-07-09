"""Canonical request bodies for bulk-by-IDs endpoints.

The single home for the ``{"ids": [...]}`` shape shared across the finalize,
inventory, forecast-copy, offer/reminder-send and set-to-paid endpoints.
Runtime extraction/validation goes through
:func:`apps.commissioning.utils.validation_utils.parse_bulk_ids`; these
serializers exist to document the shape for the generated frontend client.
"""

from rest_framework import serializers


class BulkIdsRequestSerializer(serializers.Serializer):
    """Request body carrying only a non-empty list of IDs: ``{"ids": [...]}``."""

    ids = serializers.ListField(child=serializers.CharField(), min_length=1)


class BulkIdsWithDateRequestSerializer(BulkIdsRequestSerializer):
    """``BulkIdsRequestSerializer`` plus an optional ``date``."""

    date = serializers.DateField(required=False, allow_null=True)
