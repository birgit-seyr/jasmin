from typing import Any

from rest_framework import serializers

# Every concrete commissioning model that carries ``FinalizableMixin``, by the
# lowercase ``_meta.model_name`` that ``apps.get_model`` resolves. The generic
# bulk (un)finalize endpoints accept only these; a test keeps the tuple in step
# with the model registry.
FINALIZABLE_MODEL_NAMES: tuple[str, ...] = (
    "cratecontentinvoicereseller",
    "cratedeliverynotecontent",
    "crateordercontent",
    "deliverynotecontent",
    "deliverynotereseller",
    "forecast",
    "harvest",
    "invoicereseller",
    "invoiceresellercontent",
    "offer",
    "order",
    "ordercontent",
    "sharecontent",
)


class FinalizableModelNameField(serializers.ChoiceField):
    """A model-name choice matched case-insensitively.

    ``apps.get_model`` has always lowercased the name, so clients sending
    ``"Order"`` and ``"order"`` both stay valid. A non-string value is refused
    as an invalid choice instead of reaching ``.lower()``.
    """

    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, str):
            self.fail("invalid_choice", input=data)
        return super().to_internal_value(data.lower())


class BulkFinalizeRequestSerializer(serializers.Serializer):
    model = FinalizableModelNameField(
        choices=FINALIZABLE_MODEL_NAMES,
        help_text=(
            "Finalizable commissioning model, by model name (case-insensitive). "
            "offer, forecast and harvest need a staff role; every other model "
            "needs office."
        ),
    )
    app_label = serializers.ChoiceField(
        choices=["commissioning"],
        required=False,
        default="commissioning",
        help_text="App label where the model is defined; only 'commissioning'",
    )
    ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        help_text="List of IDs to finalize or unfinalize",
    )


class BulkFinalizeResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    finalized_count = serializers.IntegerField()
    already_finalized_count = serializers.IntegerField()
    total_requested = serializers.IntegerField()
    errors = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of errors encountered during finalization",
    )


class BulkUnfinalizeResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    unfinalized_count = serializers.IntegerField()


class BulkFinalizeShareContentResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    finalized_count = serializers.IntegerField()
    already_finalized_count = serializers.IntegerField()
    total_requested = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField())
    finalization_status = serializers.DictField(
        child=serializers.BooleanField(),
        help_text="Map of composite_id → is_finalized (True if ALL rows in group are finalized)",
    )
