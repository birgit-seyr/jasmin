from rest_framework import serializers


class CombinedOrderOverviewSerializer(serializers.Serializer):
    """Full response shape for the combined order overview."""

    # Order
    id = serializers.CharField()
    order_number = serializers.CharField()
    order_date = serializers.DateField(allow_null=True)
    order_is_finalized = serializers.BooleanField()
    sum_netto = serializers.CharField(allow_null=True)
    # Reseller
    reseller_id = serializers.CharField(allow_null=True)
    reseller_name = serializers.CharField(allow_null=True)
    # Delivery note
    has_delivery_note = serializers.BooleanField()
    delivery_note_id = serializers.CharField(allow_null=True)
    delivery_note_number = serializers.CharField(allow_null=True)
    delivery_note_prefix = serializers.CharField(allow_null=True)
    delivery_note_date = serializers.DateField(allow_null=True)
    delivery_note_is_finalized = serializers.BooleanField()
    delivery_note_has_been_sent_to_reseller = serializers.BooleanField()
    delivery_note_has_been_sent_to_reseller_at = serializers.DateTimeField(
        allow_null=True
    )
    # Invoice
    has_invoice = serializers.BooleanField()
    invoice_id = serializers.CharField(allow_null=True)
    invoice_number = serializers.CharField(allow_null=True)
    invoice_date = serializers.DateField(allow_null=True)
    has_finalized_invoice = serializers.BooleanField()
    invoice_finalized_at = serializers.DateTimeField(allow_null=True)
    invoice_has_been_sent_to_reseller = serializers.BooleanField()
    invoice_has_been_sent_to_reseller_at = serializers.DateTimeField(allow_null=True)
    invoice_has_been_sent_to_accounting = serializers.BooleanField()
    invoice_has_been_sent_to_accounting_at = serializers.DateTimeField(allow_null=True)
    has_been_paid = serializers.BooleanField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    invoice_cancelled_by = serializers.CharField(allow_null=True)
    invoice_storno_id = serializers.CharField(allow_null=True)
    invoice_storno_number = serializers.CharField(allow_null=True)
