from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.shared.pii_masking import MaskedIBANFieldMixin

from ..models import ContactEntity, CoopShare, Member


class MyDataCoopShareSerializer(serializers.ModelSerializer):
    """Slim CoopShare projection for the member's self-view: only the
    fields the user actually needs to see in their own data tab
    (amount + payment status). All fields are read-only — equity
    record changes are office-managed (cf. CoopShareViewSet)."""

    class Meta:
        model = CoopShare
        # ``admin_confirmed`` / ``admin_confirmed_at`` so the member can see
        # which shares are still pending office confirmation vs already
        # confirmed (and when); ``cancelled_at`` so divested shares can be
        # excluded from the member's confirmed/pending split.
        fields = [
            "id",
            "amount_of_coop_shares",
            "due_date",
            "paid_at",
            "admin_confirmed",
            "admin_confirmed_at",
            "cancelled_at",
        ]
        read_only_fields = fields


class MyCoopShareSubscribeSerializer(serializers.ModelSerializer):
    """Member self-service coop-share subscription ("Zeichnung"). The member
    only supplies the amount (+ optional note); everything authoritative —
    ``member``, ``value_one_coop_share``, ``is_increase``, ``admin_confirmed`` —
    is set server-side in :class:`MyCoopShareSubscribeView`. The created share
    stays ``admin_confirmed=False`` until the office confirms it."""

    # Affirmation that the member agrees to the tenant's Zeichnungsvertrag.
    # Required server-side only when the tenant has uploaded a contract (gated
    # in MyCoopShareSubscribeView); write-only, not a model field.
    agreed_to_contract = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = CoopShare
        fields = ["amount_of_coop_shares", "note", "agreed_to_contract"]

    def validate_amount_of_coop_shares(self, value):
        from core.errors import BadRequestError

        if value is None or value <= 0:
            raise BadRequestError(
                "amount_of_coop_shares must be greater than 0",
                code="coop_share.invalid_amount",
            )
        # A cooperative share is a whole Geschäftsanteil (GenG) — reject
        # fractional amounts, matching the integer-only public registration path.
        if value % 1 != 0:
            raise BadRequestError(
                "amount_of_coop_shares must be a whole number",
                code="coop_share.invalid_amount",
            )
        return value


class MySubscriptionSubscribeSerializer(serializers.Serializer):
    """Member self-service subscription ("Abo") input. The member chooses the
    share-type variation, amount, billing cycle, delivery station+day, and
    start date; everything authoritative — ``member`` (taken from the token),
    ``is_trial`` (forced False), ``price_per_delivery`` (derived from the
    variation), ``admin_confirmed`` (stays False) — is set server-side in
    :class:`MySubscriptionSubscribeView`. The draft is office-confirmed (and its
    deliveries materialised) through the existing abo confirmation flow."""

    share_type_variation = serializers.CharField()
    quantity = serializers.IntegerField(min_value=1)
    payment_cycle = serializers.CharField()
    valid_from = serializers.DateField()
    # Required: open-ended subscriptions are not allowed (the term must have an
    # end date — enforced again server-side by the subscription create path).
    valid_until = serializers.DateField()
    default_delivery_station_day = serializers.CharField()
    # Solidarity pricing: a member-chosen price, honoured ONLY when the tenant
    # enables ``allows_solidarity_pricing`` (the view forces the reference price
    # otherwise). Validated against the variation's floor server-side.
    price_per_delivery = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True
    )
    # A full station-day turns the draft into a waiting-list entry: it holds no
    # capacity and only materialises once the office confirms a freed-up spot.
    on_waiting_list = serializers.BooleanField(required=False, default=False)


class MyMemberDataReadSerializer(MaskedIBANFieldMixin, serializers.ModelSerializer):
    """Outgoing shape for ``GET /commissioning/my_member_data/``.

    Editable fields appear here so the form can pre-fill them.
    Encrypted columns (IBAN, account_owner) are returned as
    boolean "stored" indicators instead of the plaintext — mirrors
    the GDPR SAR UX. A user who wants to change them types the new
    value; we don't echo the old one back over the wire."""

    # Stored-flag getters come from ``MaskedIBANFieldMixin``; Member stores the
    # holder name in ``account_owner``, hence the source override + method_name.
    MASKED_ACCOUNT_HOLDER_SOURCE = "account_owner"
    iban_stored = serializers.SerializerMethodField()
    account_owner_stored = serializers.SerializerMethodField(
        method_name="get_account_holder_stored"
    )
    coop_shares = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            # ---- Editable (saved via MyMemberDataUpdateSerializer) ----
            "first_name",
            "last_name",
            "company_name",
            "pickup_name",
            "address",
            "zip_code",
            "city",
            "country",
            "email",
            "birth_date",
            "iban_stored",
            "account_owner_stored",
            # ---- Read-only summary ----
            "member_number",
            "is_trial",
            "is_active",
            "entry_date",
            "coop_shares",
        ]
        read_only_fields = fields

    @extend_schema_field(MyDataCoopShareSerializer(many=True))
    def get_coop_shares(self, obj: Member) -> list[dict]:
        # Prefetched on the view so this is not N+1.
        shares = getattr(obj, "_prefetched_coop_shares", None)
        if shares is None:
            shares = CoopShare.objects.filter(member=obj)
        return MyDataCoopShareSerializer(shares, many=True).data


class MyMemberDataUpdateSerializer(serializers.ModelSerializer):
    """Incoming shape for ``PATCH /commissioning/my_member_data/``.

    Field allowlist for member self-edit. Office-only flags
    (``is_active``, ``is_trial``, ``member_number``, entry_date,
    coop-share totals) are NOT in this list and silently ignored
    if a client tries to send them — DRF only deserialises what's
    declared. Validators (IBAN format, email uniqueness) come from
    the model fields automatically."""

    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "company_name",
            "pickup_name",
            "address",
            "zip_code",
            "city",
            "country",
            "email",
            "birth_date",
            "iban",
            "account_owner",
        ]
        extra_kwargs = {
            # The model accepts blanks, but for the self-edit surface we
            # want empty strings to mean "clear the field" not "skip".
            # DRF default behavior already maps "" → "" so this is
            # explicit-rather-than-magic.
            "iban": {"required": False, "allow_blank": True, "allow_null": True},
            "account_owner": {
                "required": False,
                "allow_blank": True,
                "allow_null": True,
            },
        }

    def validate(self, attrs):
        # birth_date is statutory cooperative-registry PII that becomes legally
        # fixed once the office admin-confirms the member. The office serializer
        # locks it after confirmation; mirror that lock on the self-edit surface
        # so a confirmed member can't change it via this endpoint. Pre-
        # confirmation edits stay allowed (the check only fires when confirmed).
        if (
            self.instance is not None
            and self.instance.admin_confirmed
            and "birth_date" in attrs
            and attrs["birth_date"] != self.instance.birth_date
        ):
            from apps.commissioning.errors import LockedAfterAdminConfirmation

            raise LockedAfterAdminConfirmation(["birth_date"])
        return super().validate(attrs)


class MyCustomerDataReadSerializer(MaskedIBANFieldMixin, serializers.ModelSerializer):
    """Outgoing shape for ``GET /commissioning/my_customer_data/``.

    The view passes the owning ``Reseller`` row via context so the
    read-only ``customer_number`` can come along for the ride
    without forcing the client to make a second call."""

    # ``iban_stored`` getter comes from ``MaskedIBANFieldMixin`` (default
    # ``MASKED_IBAN_SOURCE = "iban"`` matches ``ContactEntity.iban``).
    iban_stored = serializers.SerializerMethodField()
    customer_number = serializers.SerializerMethodField()

    class Meta:
        model = ContactEntity
        fields = [
            # ---- Editable ----
            "company_name",
            "first_name",
            "last_name",
            "address",
            "zip_code",
            "city",
            "country",
            "email",
            "email_2",
            "email_3",
            "order_email",
            "phone",
            "phone_2",
            "phone_3",
            "uid",
            "iban_stored",
            # ---- Read-only summary ----
            "customer_number",
        ]
        read_only_fields = fields

    def get_customer_number(self, obj: ContactEntity) -> int | None:
        reseller = self.context.get("reseller")
        return reseller.customer_number if reseller else None


class MyCustomerDataUpdateSerializer(serializers.ModelSerializer):
    """Incoming shape for ``PATCH /commissioning/my_customer_data/``.

    Edits the linked ``ContactEntity``. The owning ``Reseller`` row
    (customer_number, invoice_*, channel flags) stays office-only."""

    class Meta:
        model = ContactEntity
        fields = [
            "company_name",
            "first_name",
            "last_name",
            "address",
            "zip_code",
            "city",
            "country",
            "email",
            "email_2",
            "email_3",
            "order_email",
            "phone",
            "phone_2",
            "phone_3",
            "uid",
            "iban",
        ]
        extra_kwargs = {
            "iban": {"required": False, "allow_blank": True, "allow_null": True},
        }
