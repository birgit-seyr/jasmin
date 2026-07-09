from datetime import date

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from ..constants import get_default_tax_rate_crates
from ..models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    Offer,
    OfferGroup,
    OrderContent,
    Reseller,
)
from ..utils.iso_week_utils import date_from_order
from .serializers_mixin import (
    ARTICLE_DIFF_FIELDS,
    CRATE_DIFF_FIELDS,
    CreatedByNameMixin,
    DeletableListSerializer,
    DeletableMixin,
    DifferenceTrackingMixin,
    DynamicContactFieldsMixin,
    LinePricingFieldsMixin,
    LinkedUserInfoMixin,
    NameFieldMixin,
    ShareArticleResolutionMixin,
    TaxBreakdownFieldMixin,
)


class ResellerListSerializer(DeletableListSerializer):
    """Bulk-precomputes each reseller's *linked delivery station* deletability
    on top of the row-level ``can_be_deleted`` batching from
    :class:`DeletableListSerializer`.

    Without this, ``get_linked_delivery_station_can_be_deleted`` runs
    ``can_delete_instance`` (R queries) per row's linked DeliveryStation —
    an O(N*R) N+1 on the reseller list. Here it costs R queries total.
    """

    # Set on ``self`` once ``to_representation`` runs; child reads it.
    _linked_delivery_station_deletable_pks: set | None = None
    _linked_delivery_station_failed: bool = False

    def to_representation(self, data):
        instances = list(data)
        if instances:
            self._compute_linked_delivery_station_deletable(instances)
        return super().to_representation(instances)

    def _compute_linked_delivery_station_deletable(self, instances: list) -> None:
        from ..models import DeliveryStation
        from ..utils.deletion_utils import bulk_deletable_pks

        ds_pks = []
        for reseller in instances:
            # ``linked_delivery_station`` is select_related in the viewset, so
            # this reverse O2O access is query-free.
            try:
                delivery_station = reseller.linked_delivery_station
            except DeliveryStation.DoesNotExist:
                continue
            if delivery_station is not None:
                ds_pks.append(delivery_station.pk)

        if not ds_pks:
            self._linked_delivery_station_deletable_pks = set()
            return

        deletable, failed = bulk_deletable_pks(
            DeliveryStation, ds_pks, exclude_models=["Reseller"]
        )
        self._linked_delivery_station_deletable_pks = deletable
        self._linked_delivery_station_failed = failed


class ResellerSerializer(
    DeletableMixin,
    DynamicContactFieldsMixin,
    LinkedUserInfoMixin,
    serializers.ModelSerializer,
):
    LINKED_USER_ATTR = "linked_user"
    has_orders = serializers.BooleanField(read_only=True)
    # Computed on read from the reverse OneToOne; on write it's a transient
    # flag the service uses to auto-create / unlink a ``DeliveryStation``.
    # The actual FK lives on ``DeliveryStation.linked_reseller``.
    is_also_delivery_station = serializers.BooleanField(required=False)
    linked_delivery_station = serializers.PrimaryKeyRelatedField(read_only=True)
    # Tells the frontend whether the ``is_also_delivery_station`` checkbox
    # may be unticked. False when the linked DS still has dependants and
    # would be orphaned by an unlink.
    linked_delivery_station_can_be_deleted = serializers.SerializerMethodField()
    # Snapshot of the linked JasminUser so the frontend can render the
    # user-status button + modal (account_status, invitation, etc).
    linked_user_info = serializers.SerializerMethodField()
    # The contact IBAN is EncryptedCharField — never echo it in plaintext (see
    # to_representation, which drops the raw copy). Expose a masked value + a
    # "stored" flag so the office UI can show a hint and type-to-change.
    iban_masked = serializers.SerializerMethodField()
    iban_stored = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_contact_fields(
            strict_required=True,
            handle_conflicts=False,
            exclude_fields={"id"},
        )

    def validate(self, data):
        """Custom validation for contact fields.

        On CREATE (or full PUT), require every required contact field
        to be present and non-empty.

        On PATCH (``self.partial=True``), validate ONLY the fields
        actually in the payload. Missing fields keep their existing
        instance values — that's the whole point of PATCH. Without
        this guard, editing a single field that lives on the
        ``ContactEntity`` (e.g. ``iban`` or ``uid`` from the new
        ResellerInvoiceSettingsModal) would demand the office re-
        send the full address block on every save.
        """
        contact_fields = self._get_contact_field_names(exclude_fields={"id"})
        contact_data = {k: v for k, v in data.items() if k in contact_fields}

        if contact_data and not self.partial:
            required_contact_fields = self._get_required_contact_fields(
                exclude_fields={"id"}
            )
            missing_fields = []

            for field_name in required_contact_fields:
                if field_name not in contact_data or contact_data[field_name] in [
                    None,
                    "",
                ]:
                    missing_fields.append(field_name)

            if missing_fields:
                raise serializers.ValidationError(
                    f"Missing required contact fields: {', '.join(missing_fields)}"
                )

        return data

    def to_representation(self, instance):
        """Customize the output representation to include contact fields"""
        data = super().to_representation(instance)

        if instance.contact:
            contact_fields = self._get_contact_field_names(exclude_fields={"id"})
            for field_name in contact_fields:
                # No ``, None`` default: ``field_name`` comes from
                # ``_get_contact_field_names`` walking the model meta —
                # if a name in that list doesn't resolve, that's a real
                # bug to surface, not silently render as null.
                data[field_name] = getattr(instance.contact, field_name)

        # NEVER echo the decrypted IBAN — ``ContactEntity.iban`` is an
        # EncryptedCharField, so the copy loop above would undo encryption-at-
        # rest and hand a full-register bank-account harvest to any staff read.
        # The ``iban_masked`` / ``iban_stored`` declared fields carry the safe
        # view; the office types a new IBAN to change it (still accepted on
        # write). Full reveal, if ever needed, belongs on a step-up-gated surface.
        data.pop("iban", None)

        # Derived flag for the frontend checkbox.
        from ..models import DeliveryStation

        try:
            data["is_also_delivery_station"] = (
                instance.linked_delivery_station is not None
            )
        except DeliveryStation.DoesNotExist:
            data["is_also_delivery_station"] = False

        return data

    def get_iban_masked(self, obj) -> str:
        from apps.shared.pii_masking import mask_iban

        contact = getattr(obj, "contact", None)
        return mask_iban(getattr(contact, "iban", None) if contact else None)

    def get_iban_stored(self, obj) -> bool:
        contact = getattr(obj, "contact", None)
        return bool(getattr(contact, "iban", None) if contact else None)

    def get_linked_delivery_station_can_be_deleted(self, obj) -> bool:
        """True iff unlinking would not orphan a DS that's still in use.

        Used by the frontend to disable the ``is_also_delivery_station``
        checkbox when the link cannot safely be undone.
        """
        from ..models import DeliveryStation

        try:
            delivery_station = obj.linked_delivery_station
        except DeliveryStation.DoesNotExist:
            return True
        if delivery_station is None:
            return True

        # List path: the parent ListSerializer precomputed deletability for
        # every linked delivery station on the page in one batch.
        parent = getattr(self, "parent", None)
        if (
            isinstance(parent, ResellerListSerializer)
            and not parent._linked_delivery_station_failed
            and parent._linked_delivery_station_deletable_pks is not None
        ):
            return delivery_station.pk in parent._linked_delivery_station_deletable_pks

        # Detail / create / update path — single instance, single check.
        from ..utils.deletion_utils import can_delete_instance

        can_delete, _ = can_delete_instance(
            delivery_station, exclude_models=["Reseller"]
        )
        return can_delete

    class Meta:
        model = Reseller
        fields = "__all__"
        # Override the auto-wired DeletableListSerializer so the list path
        # also bulk-precomputes linked-delivery-station deletability.
        list_serializer_class = ResellerListSerializer


class OfferSerializer(serializers.ModelSerializer):
    share_article_name = serializers.CharField(read_only=True)
    forecast_exists = serializers.BooleanField(read_only=True)
    amount_ordered = serializers.DecimalField(
        max_digits=7, decimal_places=3, read_only=True
    )

    organic_status = serializers.CharField(
        source="share_article.organic_status", read_only=True, allow_null=True
    )

    class Meta:
        model = Offer
        fields = "__all__"


class OrderContentSerializer(
    LinePricingFieldsMixin, NameFieldMixin, serializers.ModelSerializer
):
    year = serializers.IntegerField(write_only=True)
    delivery_week = serializers.IntegerField(write_only=True)
    day_number = serializers.IntegerField(write_only=True)
    reseller = serializers.PrimaryKeyRelatedField(
        queryset=Reseller.objects.all(), write_only=True
    )
    harvesting_day = serializers.IntegerField(write_only=True, required=False)
    packing_day = serializers.IntegerField(write_only=True, required=False)
    washing_day = serializers.IntegerField(write_only=True, required=False)
    cleaning_day = serializers.IntegerField(write_only=True, required=False)
    # ``last_possible_ordering_day`` may genuinely be ``null`` on the wire
    # (resellers without a hard deadline). The other three day fields
    # must always carry an integer if present — the model's
    # ``null=True`` exists for legacy/migration rows, not as a valid
    # write-time input.
    last_possible_ordering_day = serializers.IntegerField(
        write_only=True, required=False, allow_null=True
    )
    NAME_FIELDS = ["share_article_name"]
    order_id = serializers.CharField(read_only=True)
    order_number = serializers.CharField(read_only=True)
    order_number_prefix = serializers.CharField(read_only=True)
    order_is_finalized = serializers.BooleanField(read_only=True)
    delivery_note_is_finalized = serializers.BooleanField(read_only=True)

    delivery_note_id = serializers.CharField(read_only=True)
    delivery_note_number = serializers.CharField(read_only=True)
    delivery_note_prefix = serializers.CharField(read_only=True)

    invoice_id = serializers.CharField(read_only=True)
    invoice_number = serializers.CharField(read_only=True)
    invoice_prefix = serializers.CharField(read_only=True)
    has_invoice = serializers.BooleanField(read_only=True)
    has_finalized_invoice = serializers.BooleanField(read_only=True)

    class Meta:
        model = OrderContent
        fields = "__all__"
        extra_kwargs = {
            "order": {"read_only": True},
            # tax_rate is derivable from the offer/article pricing — the service
            # (create_order_with_content_and_crates / update_order_content)
            # resolves it via the canonical chain when omitted. Don't force the
            # client (e.g. the customer order page) to send it.
            "tax_rate": {"required": False, "allow_null": True},
        }


class OfferGroupSerializer(DeletableMixin, serializers.ModelSerializer):
    reseller_names = serializers.CharField(read_only=True)

    class Meta:
        model = OfferGroup
        fields = "__all__"
        # is_default is set only by the seed migration — never via the API.
        read_only_fields = ["is_default"]

    def get_can_be_deleted(self, obj) -> bool:
        # The seeded default offer group is protected — never deletable,
        # regardless of FK references.
        if getattr(obj, "is_default", False):
            return False
        return super().get_can_be_deleted(obj)


class CrateContentInvoiceResellerSerializer(
    DifferenceTrackingMixin,
    LinePricingFieldsMixin,
    NameFieldMixin,
    serializers.ModelSerializer,
):
    NAME_FIELDS = ["crate_type_name"]
    DIFF_FIELDS = CRATE_DIFF_FIELDS

    class Meta:
        model = CrateContentInvoiceReseller
        fields = "__all__"
        read_only_fields = ["is_finalized", "finalized_at", "finalized_by"]


# for the Invoice Modal:
class InvoiceResellerContentSerializer(
    ShareArticleResolutionMixin,
    DifferenceTrackingMixin,
    LinePricingFieldsMixin,
    serializers.ModelSerializer,
):
    # ``share_article_name`` + ``organic_status`` come from
    # ``ShareArticleResolutionMixin``.

    # Snapshot-backed diff fields. The article cannot be diffed because the
    # upstream FK is not snapshotted (intentional — see SourceSnapshotMixin).
    DIFF_FIELDS = ARTICLE_DIFF_FIELDS

    class Meta:
        model = InvoiceResellerContent
        fields = "__all__"


class CrateItemSummarySerializer(serializers.Serializer):
    """Aggregated crate summary returned by Invoice/DeliveryNote `crate_items`."""

    id = serializers.CharField()
    crate_type = serializers.CharField()
    crate_type_name = serializers.CharField(allow_null=True)
    amount = serializers.IntegerField()
    price_per_unit = serializers.CharField()
    rabatt = serializers.FloatField()
    line_netto = serializers.CharField()
    tax_rate = serializers.FloatField()
    invoice_id = serializers.CharField(required=False, allow_null=True)
    invoice_number = serializers.CharField(required=False, allow_null=True)
    invoice_prefix = serializers.CharField(required=False, allow_null=True)
    invoice_is_finalized = serializers.BooleanField(required=False)
    delivery_note_id = serializers.CharField(required=False, allow_null=True)
    delivery_note_number = serializers.CharField(required=False, allow_null=True)
    delivery_note_prefix = serializers.CharField(required=False, allow_null=True)
    delivery_note_is_finalized = serializers.BooleanField(required=False)


class CrateOrderSummarySerializer(serializers.Serializer):
    """Aggregated crate summary returned by ``CrateOrderContentViewSet``.

    Money is sent as canonical 2dp STRINGS (``price_per_unit`` /
    ``line_netto``), matching the DN/invoice ``CrateItemSummarySerializer``
    — never JSON floats — so full precision survives the wire and the
    client does not recompute line totals in floating point. ``rabatt`` /
    ``tax_rate`` stay numeric. ``note`` / ``order_id`` / ``order_number`` /
    ``order_number_prefix`` only appear on create.
    """

    id = serializers.CharField()
    crate_type = serializers.CharField()
    crate_type_name = serializers.CharField(allow_null=True)
    amount = serializers.IntegerField()
    price_per_unit = serializers.CharField()
    rabatt = serializers.FloatField()
    line_netto = serializers.CharField()
    tax_rate = serializers.FloatField()
    note = serializers.CharField(required=False, allow_null=True)
    order_id = serializers.CharField(required=False)
    # ``display_number`` (e.g. "39v"), a STRING — mirrors OrderContentItem so
    # the frontend formats "{prefix}-{display_number}" the same on create and
    # on reload. Was IntegerField (raw number) and lacked the prefix entirely.
    order_number = serializers.CharField(required=False, allow_null=True)
    order_number_prefix = serializers.CharField(required=False, allow_null=True)


class OrderContentItemSerializer(serializers.Serializer):
    """One order-content row as returned by create / update / partial_update
    (``OrderContentService._serialize_order_content``) — the flat per-row dict
    WITHOUT the delivery-note / invoice document block. The list endpoint
    augments each row with that block: see ``OrderContentListItemSerializer``.
    """

    id = serializers.CharField(allow_null=True)
    is_placeholder = serializers.BooleanField()
    order_id = serializers.CharField(allow_null=True)
    order_number = serializers.CharField(allow_null=True)
    order_number_prefix = serializers.CharField(allow_null=True)
    order_is_finalized = serializers.BooleanField()
    order_note = serializers.CharField(allow_blank=True, required=False)
    harvesting_day = serializers.IntegerField(allow_null=True)
    packing_day = serializers.IntegerField(allow_null=True)
    washing_day = serializers.IntegerField(allow_null=True)
    cleaning_day = serializers.IntegerField(allow_null=True)
    last_possible_ordering_day = serializers.IntegerField(allow_null=True)
    offer = serializers.CharField(allow_null=True)
    offer_name = serializers.CharField(allow_null=True)
    offer_available_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    amount_per_pu = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    offer_share_article_name = serializers.CharField(allow_null=True)
    share_article = serializers.CharField(allow_null=True)
    share_article_name = serializers.CharField(allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    ordered_amount = serializers.DecimalField(
        max_digits=12, decimal_places=4, allow_null=True
    )
    size = serializers.CharField()
    sort = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(allow_null=True, allow_blank=True)
    unit = serializers.CharField()
    price_per_unit = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    price_1 = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    price_2 = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    price_3 = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    rabatt = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    washing = serializers.BooleanField(required=False)
    cleaning = serializers.BooleanField(required=False)
    comes_from_long_term_storage = serializers.BooleanField(required=False)


class OrderContentListItemSerializer(OrderContentItemSerializer):
    """A list row from ``get_offers_and_order_content``: a base order-content
    item augmented with the delivery-note / invoice document block (and the
    placeholder rows synthesised for unused offers). create / update /
    partial_update return the bare base shape, which omits this block.
    """

    delivery_note_id = serializers.CharField(allow_null=True)
    delivery_note_number = serializers.CharField(allow_null=True)
    delivery_note_prefix = serializers.CharField(allow_null=True)
    delivery_note_is_finalized = serializers.BooleanField()
    invoice_id = serializers.CharField(allow_null=True)
    invoice_number = serializers.CharField(allow_null=True)
    invoice_prefix = serializers.CharField(allow_null=True)
    has_invoice = serializers.BooleanField()
    has_finalized_invoice = serializers.BooleanField()


class OrdersDeliveryDayDefaultsSerializer(serializers.Serializer):
    """Default settings for the orders' delivery day."""

    default_harvesting_day = serializers.IntegerField(allow_null=True)
    default_packing_day = serializers.IntegerField(allow_null=True)
    default_washing_day = serializers.IntegerField(allow_null=True)
    default_cleaning_day = serializers.IntegerField(allow_null=True)
    default_last_possible_ordering_day = serializers.IntegerField(allow_null=True)
    default_last_possible_ordering_time = serializers.CharField(allow_null=True)


class OrderMetadataSerializer(serializers.Serializer):
    """Top-level order identity for a period — present even when the order has
    only crates and zero OrderContent rows (a crates-only order). ``null`` when
    no order exists for the period. Mirrors the per-row ``order_*`` /
    ``delivery_note_*`` / ``invoice_*`` keys."""

    order_id = serializers.CharField(allow_null=True)
    order_number = serializers.CharField(allow_null=True)
    order_number_prefix = serializers.CharField(allow_null=True)
    order_is_finalized = serializers.BooleanField()
    order_note = serializers.CharField(allow_blank=True)
    harvesting_day = serializers.IntegerField(allow_null=True)
    packing_day = serializers.IntegerField(allow_null=True)
    washing_day = serializers.IntegerField(allow_null=True)
    cleaning_day = serializers.IntegerField(allow_null=True)
    delivery_note_id = serializers.CharField(allow_null=True)
    delivery_note_number = serializers.CharField(allow_null=True)
    delivery_note_prefix = serializers.CharField(allow_null=True)
    delivery_note_is_finalized = serializers.BooleanField()
    invoice_id = serializers.CharField(allow_null=True)
    invoice_number = serializers.CharField(allow_null=True)
    invoice_prefix = serializers.CharField(allow_null=True)
    has_invoice = serializers.BooleanField()
    has_finalized_invoice = serializers.BooleanField()


# ``many=False``: the list action returns ONE wrapper object, but
# drf-spectacular array-wraps list-action responses by default — without this
# the generated client types the response ``OrderContentListResponse[]`` while
# the runtime body is a single ``{items, order, orders_delivery_day_defaults}``.
@extend_schema_serializer(many=False)
class OrderContentListResponseSerializer(serializers.Serializer):
    """Wrapped response for OrderContentViewSet.list."""

    items = OrderContentListItemSerializer(many=True)
    # ``null`` when the period has no order. Carries the order's identity even
    # for a crates-only order, which has no ``items`` rows to derive it from.
    order = OrderMetadataSerializer(allow_null=True)
    orders_delivery_day_defaults = OrdersDeliveryDayDefaultsSerializer()


class InvoiceResellerSerializer(
    CreatedByNameMixin, TaxBreakdownFieldMixin, serializers.ModelSerializer
):
    line_items = InvoiceResellerContentSerializer(
        source="items", many=True, read_only=True
    )
    crate_items = serializers.SerializerMethodField()
    sum_netto = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    sum_brutto = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    # Flat snapshot of the reseller's billing address for the PDF +
    # ZUGFeRD renderers (both consume ``invoice.reseller_*`` directly).
    #
    # The reseller model carries a dedicated ``invoice_*`` block
    # (``invoice_name``, ``invoice_address``, ``invoice_plz``,
    # ``invoice_city``, ``invoice_email``) that the office sets via
    # ``ResellerInvoiceSettingsModal`` whenever billing diverges from
    # the storefront contact (separate accounting office, c/o
    # forwarder, etc.). Those invoice fields are the source of truth
    # for ANY document that goes out as an invoice — UStG §14 says
    # the recipient block on the invoice has to be the billing
    # address, not the delivery contact.
    #
    # Resolution per field:
    #   1. ``reseller.invoice_*`` if set
    #   2. fall back to ``reseller.contact.*`` for resellers that
    #      pre-date the invoice block, or where it was wiped, so
    #      old data keeps rendering instead of silently going blank.
    # ``country`` and ``uid`` have no invoice-level counterpart on the
    # model, so they continue to source straight from ``contact``.
    reseller_name = serializers.SerializerMethodField()
    reseller_name2 = serializers.SerializerMethodField()
    reseller_address = serializers.SerializerMethodField()
    reseller_zip = serializers.SerializerMethodField()
    reseller_city = serializers.SerializerMethodField()
    reseller_country = serializers.SerializerMethodField()
    reseller_uid = serializers.SerializerMethodField()

    # DOC-8: resolve the recipient block via the model's resolved_recipient() —
    # the FROZEN recipient_snapshot for a finalized invoice (the §14b recipient
    # as of issue, in lock-step with the sealed document_hash), and the LIVE
    # reseller/contact block for drafts. Reading live off a finalized invoice
    # would let a later reseller edit / GDPR anonymization drift the rendered
    # PDF + ZUGFeRD away from the sealed hash. resolved_recipient() returns the
    # {name, name2, address, zip, city, country, uid} dict (its live branch
    # mirrors the reseller.invoice_* → contact.* fallback this used to do).
    #
    # Resolve it ONCE per row (cached for the duration of a single row's
    # to_representation) rather than 7× — one per get_reseller_* field. DRF
    # reuses ONE serializer instance for the whole list, so the cache is reset
    # after each row to never leak across rows.
    _recipient_cache: dict | None = None

    def to_representation(self, instance):
        self._recipient_cache = instance.resolved_recipient()
        try:
            return super().to_representation(instance)
        finally:
            self._recipient_cache = None

    def _recipient(self, obj) -> dict:
        # Fresh resolve if a field method is ever invoked outside
        # to_representation (e.g. a unit test calling it directly).
        if self._recipient_cache is not None:
            return self._recipient_cache
        return obj.resolved_recipient()

    def get_reseller_name(self, obj) -> str | None:
        return self._recipient(obj).get("name")

    def get_reseller_name2(self, obj) -> str | None:
        return self._recipient(obj).get("name2")

    def get_reseller_address(self, obj) -> str | None:
        return self._recipient(obj).get("address")

    def get_reseller_zip(self, obj) -> str | None:
        return self._recipient(obj).get("zip")

    def get_reseller_city(self, obj) -> str | None:
        return self._recipient(obj).get("city")

    def get_reseller_country(self, obj) -> str | None:
        return self._recipient(obj).get("country")

    def get_reseller_uid(self, obj) -> str | None:
        return self._recipient(obj).get("uid")

    # Raw per-reseller payment-term columns. The fallback to tenant
    # defaults is done on the frontend at PDF-render time — it already
    # has TenantSettings cached via ``useTenant().getSetting()``, so
    # resolving here would mean per-row TenantSettings queries for no
    # gain. Source paths piggyback on the viewset's
    # ``select_related("reseller__contact")`` — zero extra queries.
    reseller_payment_terms_in_days = serializers.IntegerField(
        source="reseller.payment_terms_in_days", read_only=True, allow_null=True
    )
    reseller_early_payment_discount_percent = serializers.DecimalField(
        source="reseller.early_payment_discount_percent",
        max_digits=5,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    reseller_early_payment_discount_days = serializers.IntegerField(
        source="reseller.early_payment_discount_days",
        read_only=True,
        allow_null=True,
    )

    invoice_number = serializers.CharField(source="display_number", read_only=True)
    invoice_date = serializers.DateField(source="date", read_only=True)
    corresponding_delivery_notes = serializers.SerializerMethodField()
    cancels_invoice_number = serializers.SerializerMethodField()
    # ``created_by_name`` comes from ``CreatedByNameMixin``.

    class Meta:
        model = InvoiceReseller
        fields = "__all__"
        # Invoices are GoBD / UStG §14 legal documents. Their identity,
        # numbering, finalization state, integrity hash and audit links are
        # owned exclusively by the service layer (InvoiceService) and the
        # dedicated actions (upload_pdf, create_storno) — NEVER by the generic
        # create/update verbs. Without this allow-list, an office user could
        # POST/PATCH a hand-picked number/prefix/document_type/document_hash
        # with is_finalized=true and mint a pre-finalized, out-of-sequence,
        # hash-spoofed document on insert (no BEFORE INSERT DB trigger guards
        # that path). Genuinely operational fields (note, has_been_paid,
        # paid_at, due_date, items_are_grouped) stay writable; the finalized
        # protection layer separately bounds which of those a finalized row
        # accepts.
        read_only_fields = [
            "number",
            "prefix",
            "document_type",
            "document_hash",
            "is_finalized",
            "finalized_at",
            "finalized_by",
            "cancels_invoice",
            "cancelled_by_invoice",
            "correction_reason",
            "reseller",
            "date",
            "file",
            "xml_file",
            "created_by",
            "created_at",
            "has_been_sent_to_reseller_at",
            "has_been_sent_to_accounting_at",
        ]

    def get_cancels_invoice_number(self, obj) -> str | None:
        """Get formatted number of the cancelled invoice (e.g. RE-1)."""
        if obj.cancels_invoice:
            return obj.cancels_invoice.full_number
        return None

    def get_corresponding_delivery_notes(self, obj) -> str | None:
        """Get list of delivery notes referenced by invoice contents"""
        delivery_notes = set()

        for content in obj.items.all():
            # iterate over all delivery_note_contents
            for delivery_note_content in content.delivery_note_contents.all():
                if delivery_note_content.delivery_note:
                    delivery_note = delivery_note_content.delivery_note
                    delivery_note_str = delivery_note.full_number
                    delivery_notes.add(delivery_note_str)

        # Crate-only invoices have no article items — their delivery-note
        # provenance lives on the crate-line M2M, so walk that too (else the
        # "Zugehörige Lieferscheine" field renders blank on the UI + PDF).
        for crate_content in obj.crate_items.all():
            for crate_dn_content in crate_content.crate_delivery_note_contents.all():
                if crate_dn_content.delivery_note:
                    delivery_notes.add(crate_dn_content.delivery_note.full_number)

        # Return as comma-separated string
        return ", ".join(sorted(delivery_notes)) if delivery_notes else None

    @extend_schema_field(CrateItemSummarySerializer(many=True))
    def get_crate_items(self, obj):
        """Aggregated crate summary, grouped by ``crate_type``.

        Consumes the prefetched ``obj.crate_items.all()`` (configured on
        ``InvoiceResellerViewSet.queryset`` via
        ``prefetch_related("crate_items__crate_type")``) and aggregates
        in Python. Calling ``CrateContentInvoiceReseller.objects.filter(
        invoice=obj).values().annotate(...)`` here would defeat that
        prefetch and turn the list endpoint into N+2 queries per row.
        """
        from ..services.crate_summary import summarize_crate_items

        return summarize_crate_items(
            obj.crate_items.all(),
            resolve_tax_rate=lambda _crate_type: get_default_tax_rate_crates(),
            extras={
                "invoice_id": str(obj.id),
                "invoice_number": obj.display_number,
                "invoice_prefix": obj.prefix,
                "invoice_is_finalized": obj.is_finalized,
            },
        )


# for the Delivery Note Modal:
class DeliveryNoteResellerContentSerializer(
    ShareArticleResolutionMixin,
    DifferenceTrackingMixin,
    LinePricingFieldsMixin,
    serializers.ModelSerializer,
):
    # ``share_article_name`` + ``organic_status`` come from
    # ``ShareArticleResolutionMixin``.

    DIFF_FIELDS = ARTICLE_DIFF_FIELDS

    class Meta:
        model = DeliveryNoteContent
        fields = "__all__"


class CrateDeliveryNoteContentSerializer(
    DifferenceTrackingMixin,
    LinePricingFieldsMixin,
    NameFieldMixin,
    serializers.ModelSerializer,
):
    NAME_FIELDS = ["crate_type_name"]

    DIFF_FIELDS = CRATE_DIFF_FIELDS

    class Meta:
        model = CrateDeliveryNoteContent
        fields = "__all__"
        read_only_fields = ["is_finalized", "finalized_at", "finalized_by"]


class DeliveryNoteResellerSerializer(
    CreatedByNameMixin, TaxBreakdownFieldMixin, serializers.ModelSerializer
):
    line_items = DeliveryNoteResellerContentSerializer(
        source="items", many=True, read_only=True
    )
    crate_items = serializers.SerializerMethodField()
    sum_netto = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    sum_brutto = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    # Flat snapshot of the reseller's contact, hopping through ``order``.
    # See InvoiceResellerSerializer for the rationale on ``source=`` +
    # ``default=None`` (handles unset segments cleanly, no method needed).
    reseller_name = serializers.CharField(
        source="order.reseller.contact.name",
        default=None,
        read_only=True,
        allow_null=True,
    )
    reseller_address = serializers.CharField(
        source="order.reseller.contact.address",
        default=None,
        read_only=True,
        allow_null=True,
    )
    reseller_zip = serializers.CharField(
        source="order.reseller.contact.zip_code",
        default=None,
        read_only=True,
        allow_null=True,
    )
    reseller_city = serializers.CharField(
        source="order.reseller.contact.city",
        default=None,
        read_only=True,
        allow_null=True,
    )
    reseller_country = serializers.CharField(
        source="order.reseller.contact.country",
        default=None,
        read_only=True,
        allow_null=True,
    )

    delivery_note_number = serializers.CharField(
        source="display_number", read_only=True
    )
    delivery_note_date = serializers.DateField(source="date", read_only=True)
    order_number = serializers.CharField(
        source="order.display_number",
        default=None,
        read_only=True,
        allow_null=True,
    )
    order_date = serializers.SerializerMethodField()
    order_prefix = serializers.CharField(
        source="order.prefix",
        default=None,
        read_only=True,
        allow_null=True,
    )
    # ``created_by_name`` comes from ``CreatedByNameMixin``.

    class Meta:
        model = DeliveryNoteReseller
        fields = "__all__"
        # Delivery notes are finalized GoBD documents created by
        # DeliveryNoteService — their identity, numbering, finalization
        # state, source order and file are owned by the service / dedicated
        # actions, never the generic create/update verbs. Mirrors the
        # InvoiceReseller lock-down: without it an office user could forge a
        # pre-finalized, out-of-sequence delivery note on insert.
        read_only_fields = [
            "number",
            "prefix",
            "is_finalized",
            "finalized_at",
            "finalized_by",
            "order",
            "date",
            "file",
            "created_by",
            "created_at",
            "has_been_sent_to_reseller_at",
        ]

    def get_order_date(self, obj) -> date | None:
        """Order date via the shared ISO-week resolver (year/week/day_number)."""
        if not obj.order:
            return None
        return date_from_order(obj.order)

    @extend_schema_field(CrateItemSummarySerializer(many=True))
    def get_crate_items(self, obj):
        """Aggregated crate summary, grouped by
        ``(crate_type, price_per_unit, rabatt, tax_rate)``.

        Consumes the prefetched ``obj.crate_items.all()`` (configured on
        ``DeliveryNoteResellerViewSet.queryset`` via
        ``prefetch_related("crate_items__crate_type")``) and aggregates
        in Python. A delivery note is not a tax document (the PDF carries
        no totals / VAT), so the stored ``tax_rate`` is passed through as-is
        — no date-based fallback resolution.
        """
        from ..services.crate_summary import summarize_crate_items

        return summarize_crate_items(
            obj.crate_items.all(),
            extras={
                "delivery_note_id": str(obj.id),
                "delivery_note_number": obj.display_number,
                "delivery_note_prefix": obj.prefix,
                "delivery_note_is_finalized": obj.is_finalized,
            },
        )


# --- Shared Bulk Operation Serializers ---


class BulkDocumentRequestSerializer(serializers.Serializer):
    """Shared request for bulk operations on orders: {ids, model}."""

    ids = serializers.ListField(child=serializers.CharField(), min_length=1)
    model = serializers.ChoiceField(choices=["delivery_note", "invoice"])


class BulkDocumentWithDateRequestSerializer(BulkDocumentRequestSerializer):
    """Extends BulkDocumentRequestSerializer with an optional date."""

    date = serializers.DateField(required=False, allow_null=True)


class BulkDocumentResultRowSerializer(serializers.Serializer):
    """A per-order success row from the bulk create-document endpoints.

    The delivery-note path emits order/delivery-note identity; the invoice
    path additionally emits ``invoice_id``/``invoice_number`` (see
    ``_delivery_note_result`` / ``_invoice_result`` in ``reseller_views``).
    Schema-only — the views build the dicts by hand; typing the row here is
    what gives the generated client checked ``invoice_id``/``delivery_note_id``
    reads instead of ``{[key: string]: unknown}``."""

    order_id = serializers.CharField()
    order_number = serializers.CharField()
    delivery_note_id = serializers.CharField()
    delivery_note_number = serializers.CharField()
    success = serializers.BooleanField()
    # invoice path only
    invoice_id = serializers.CharField(required=False)
    invoice_number = serializers.CharField(required=False)


class BulkOperationResponseSerializer(serializers.Serializer):
    """Shared response shape for bulk operations."""

    model = serializers.CharField(required=False)
    total_processed = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = serializers.ListField(child=BulkDocumentResultRowSerializer())
    errors = serializers.ListField(child=serializers.DictField(), required=False)


class BulkOrderErrorRowSerializer(serializers.Serializer):
    """A per-order failure row in a bulk response.

    Produced by ``format_order_error`` (and the inline error rows in the
    set-to-paid handler, which additionally carry ``invoice_number``)."""

    order_id = serializers.CharField()
    order_number = serializers.CharField()
    error = serializers.CharField()
    success = serializers.BooleanField()
    # Only the set-to-paid "already paid" / "not paid, cannot undo" rows carry this.
    invoice_number = serializers.CharField(required=False)


class BulkDeleteResultRowSerializer(serializers.Serializer):
    """A per-order success row from BulkDeleteDocumentsView.

    delivery_note path emits order_id/order_number/delivery_note_number; the
    invoice path additionally emits delivery_note_id + invoice_number."""

    order_id = serializers.CharField()
    order_number = serializers.CharField()
    delivery_note_number = serializers.CharField()
    success = serializers.BooleanField()
    # invoice path only
    delivery_note_id = serializers.CharField(required=False)
    invoice_number = serializers.CharField(required=False)


class BulkDeleteResponseSerializer(serializers.Serializer):
    """Response shape for BulkDeleteDocumentsView (built by _build_bulk_response)."""

    model = serializers.CharField(required=False)
    total_processed = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = serializers.ListField(child=BulkDeleteResultRowSerializer())
    errors = serializers.ListField(child=BulkOrderErrorRowSerializer(), required=False)


class BulkSetToPaidResultRowSerializer(serializers.Serializer):
    """A per-order success row from BulkSetToPaidDocumentsView.

    Both paid/unpaid paths emit the full id/number set + action; ``paid_at``
    (ISO-8601 string, nullable) is present only on the "paid" path."""

    order_id = serializers.CharField()
    order_number = serializers.CharField()
    delivery_note_id = serializers.CharField()
    delivery_note_number = serializers.CharField()
    invoice_id = serializers.CharField()
    invoice_number = serializers.CharField()
    action = serializers.CharField()
    success = serializers.BooleanField()
    # "paid" path only; serialized via Invoice.paid_at.isoformat().
    paid_at = serializers.DateTimeField(required=False, allow_null=True)


# --- Combined Order Overview ---


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


# --- Copy Offers ---


class BulkCopyOffersToOfferGroupRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.CharField(), min_length=1)
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)
    offer_group = serializers.CharField()


class BulkCopyOffersResponseSerializer(serializers.Serializer):
    total_requested = serializers.IntegerField()
    total_copied = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    copied_offers = serializers.ListField(child=serializers.CharField())


# --- Summary Invoice ---


class BulkCreateSummaryInvoiceResponseSerializer(serializers.Serializer):
    invoice_id = serializers.CharField()
    invoice_number = serializers.CharField()
    sum_netto = serializers.CharField()
    sum_brutto = serializers.CharField()
    total_orders_included = serializers.IntegerField()
    total_line_items = serializers.IntegerField()
    included_orders = serializers.ListField(child=serializers.DictField())
    success = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.DictField(), required=False)
    partial_success = serializers.BooleanField(required=False)


# --- Create Offers ---


class CreateOffersRequestSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)


class CreateOffersResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    created_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    skipped_offers = serializers.ListField(
        child=serializers.DictField(), required=False
    )


# --- Set To Paid ---


class BulkSetToPaidResponseSerializer(serializers.Serializer):
    model = serializers.CharField()
    action = serializers.CharField()
    total_processed = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = serializers.ListField(child=BulkSetToPaidResultRowSerializer())
    errors = serializers.ListField(child=BulkOrderErrorRowSerializer(), required=False)


# --- Offer Sending Status ---


class OfferSendingStatusSerializer(serializers.Serializer):
    id = serializers.CharField()
    # Null for resellers without a contact entity.
    name = serializers.CharField(allow_null=True)
    address = serializers.CharField(allow_null=True, required=False)
    zip_code = serializers.CharField(allow_null=True, required=False)
    city = serializers.CharField(allow_null=True, required=False)
    country = serializers.CharField(allow_null=True, required=False)
    uid = serializers.CharField(allow_null=True, required=False)
    sent = serializers.BooleanField()
    sent_at = serializers.DateTimeField(allow_null=True)


# --- Bulk Send Offers ---


class BulkSendOffersRequestSerializer(serializers.Serializer):
    reseller_ids = serializers.ListField(child=serializers.CharField(), min_length=1)
    year = serializers.IntegerField()
    delivery_week = serializers.IntegerField(min_value=1, max_value=53)
    offer_group = serializers.CharField()


class CreateStornoRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(help_text="Reason for the storno")


# --- Commissioning List (grouped by reseller, per week + day) ---
#
# Response shape for ``GET /api/commissioning/commissioning_lists/?year=…
# &delivery_week=…&day_number=…``. The component names below MUST match
# the strings the viewset previously passed to ``inline_serializer(name=…)``
# so the Orval-generated frontend types (``CommissioningListEntry``,
# ``CommissioningListOrder``, ``CommissioningListOrderContent``) stay
# byte-identical.


class CommissioningListOrderContent(serializers.Serializer):
    id = serializers.CharField()
    # Null when the article can't be resolved (see _build_content_entry).
    share_article_id = serializers.CharField(allow_null=True)
    share_article_name = serializers.CharField()
    amount = serializers.FloatField()
    amount_per_pu = serializers.FloatField()
    # Sourced from OrderContent.size / .unit (CharField + choices, size
    # defaults to "M") — never null/blank, so don't over-declare nullability.
    size = serializers.CharField()
    unit = serializers.CharField()
    sort = serializers.CharField(allow_null=True, allow_blank=True)
    note = serializers.CharField(allow_blank=True)


class CommissioningListOrder(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_blank=True)
    contents = CommissioningListOrderContent(many=True)


class CommissioningListEntry(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    order = CommissioningListOrder()


class BackgroundJobEnqueueResponseSerializer(serializers.Serializer):
    """Shape returned by the bulk-send endpoints that enqueue a background
    job — the frontend polls ``GET /api/jobs/{job_id}/`` until status is
    ``done`` or ``failed``. Defined here (not imported from notifications)
    to keep commissioning's one-way isolation; the background-job infra
    itself remains a documented extraction blocker.
    """

    job_id = serializers.UUIDField(read_only=True)
    kind = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
