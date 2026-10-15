from typing import Any

from rest_framework import serializers

from ..models import Offer
from ..services.offer_update import update_offer
from .serializers_mixin import FINALIZATION_READONLY_FIELDS


class OfferSerializer(serializers.ModelSerializer):
    share_article_name = serializers.CharField(read_only=True)
    forecast_exists = serializers.BooleanField(read_only=True)
    amount_ordered = serializers.DecimalField(
        max_digits=7, decimal_places=3, read_only=True
    )

    organic_status = serializers.CharField(
        source="share_article.organic_status", read_only=True, allow_null=True
    )
    expected_amount = serializers.DecimalField(
        max_digits=9,
        decimal_places=3,
        write_only=True,
        required=False,
        help_text=(
            "The available amount the client read, sent with an edit of "
            "``amount``. Order lines move the stock all the time, so a changed "
            "amount is saved only while the stored one still equals this, and "
            "refused with offer.amount_changed (409) otherwise. Without it, "
            "only the stored amount itself is accepted."
        ),
    )

    class Meta:
        model = Offer
        fields = "__all__"
        # Offers are finalized only through ``/bulk_finalize/``.
        read_only_fields = FINALIZATION_READONLY_FIELDS

    def create(self, validated_data: dict[str, Any]) -> Offer:
        validated_data.pop("expected_amount", None)
        return super().create(validated_data)

    def update(self, instance: Offer, validated_data: dict[str, Any]) -> Offer:
        # Saves only what changed, so a published offer takes an edit of its
        # amount alone.
        expected_amount = validated_data.pop("expected_amount", None)
        update_offer(instance, validated_data, expected_amount=expected_amount)
        return instance
