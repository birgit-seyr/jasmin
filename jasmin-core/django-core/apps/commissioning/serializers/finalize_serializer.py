from rest_framework import serializers


class BulkFinalizeRequestSerializer(serializers.Serializer):
    model = serializers.CharField(
        required=True,
        help_text="Model name to finalize (e.g., 'Order', 'CurrentStock')",
    )
    app_label = serializers.CharField(
        required=False,
        default="commissioning",
        help_text="App label where the model is defined",
    )
    ids = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        help_text="List of IDs to finalize (regular IDs or composite IDs for CurrentStock)",
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
