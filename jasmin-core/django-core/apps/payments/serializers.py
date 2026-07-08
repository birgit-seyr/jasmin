from __future__ import annotations

from rest_framework import serializers

from apps.commissioning.serializers.serializers_mixin import (
    MemberStringFieldMixin,
)
from apps.shared.pii_masking import MaskedIBANFieldMixin

from .models import BillingProfile, BillingRun, ChargeSchedule


class BillingProfileSerializer(
    MemberStringFieldMixin, MaskedIBANFieldMixin, serializers.ModelSerializer
):
    is_sepa_ready = serializers.BooleanField(read_only=True)
    # Human-readable "# <number> - <first> <last>" for the owning member, so the
    # office SEPA-mandate report can show WHO each mandate belongs to without a
    # second members fetch. Same label formatter as the subscription / coop-share
    # rows (shared mixin) so it can't drift. ``select_related("member")`` on the
    # viewset keeps this off the N+1 path.
    member_string = serializers.SerializerMethodField(read_only=True)
    # The decrypted SEPA fields are accepted on write but never echoed in
    # full — bulk reads (and the MANAGEMENT role's all-members view) get only
    # a masked representation so a list payload can't exfiltrate every
    # member's bank details. Full editing happens on the dedicated SEPA modal.
    # Getters come from ``MaskedIBANFieldMixin`` (sources default to
    # ``iban`` / ``account_holder``, which match BillingProfile's columns).
    iban_masked = serializers.SerializerMethodField()
    account_holder_masked = serializers.SerializerMethodField()

    class Meta:
        model = BillingProfile
        fields = [
            "id",
            "member",
            "member_string",
            "payment_method",
            "iban",
            "account_holder",
            "iban_masked",
            "account_holder_masked",
            "sepa_mandate_reference",
            "sepa_mandate_signed_at",
            "sepa_mandate_first_use_at",
            "sepa_mandate_paper_received_at",
            "is_active",
            "notes",
            "is_sepa_ready",
        ]
        read_only_fields = ["id", "sepa_mandate_first_use_at", "is_sepa_ready"]
        # Decrypted IBAN / account_holder accepted on write, masked on read.
        extra_kwargs = {
            "iban": {"write_only": True},
            "account_holder": {"write_only": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TEN-3: the owning ``member`` FK is set ONCE at create (the SEPA-setup
        # flow POSTs it) and must never be reassigned on update — pointing an
        # existing profile at another member would hand over their SEPA setup.
        # Lock it read-only for updates only (an instance is bound), leaving it
        # writable on create where it's the sole source of the link.
        if self.instance is not None:
            self.fields["member"].read_only = True


class BillingProfileMemberSerializer(BillingProfileSerializer):
    """Member-facing read serializer for a member's OWN billing profile.

    Identical to the office :class:`BillingProfileSerializer` but WITHOUT the
    office-internal free-text ``notes``. ``read_only_fields`` guards writes,
    not read exposure, so the office serializer would otherwise leak the
    office's billing annotations to the member. Writes stay office-only, so
    this only narrows the incidental member read."""

    class Meta(BillingProfileSerializer.Meta):
        fields = [f for f in BillingProfileSerializer.Meta.fields if f != "notes"]


class SepaMandateStatusSerializer(serializers.Serializer):
    """Lightweight per-member SEPA mandate status for overview tables.

    Deliberately excludes the bank identifiers (IBAN / account holder) so a
    bulk read neither decrypts nor exposes bank PII, and — unlike the full
    ``BillingProfileSerializer`` list — must NOT trip the SEC-1 bank-identifier
    audit trail. ``has_active_sepa_mandate`` mirrors ``is_sepa_ready``; the
    per-subscription "active during the term" refinement is applied by the
    caller (it needs the subscription's dates).
    """

    member = serializers.CharField(source="member_id")
    has_active_sepa_mandate = serializers.BooleanField(
        source="is_sepa_ready", read_only=True
    )
    payment_method = serializers.CharField()
    sepa_mandate_reference = serializers.CharField(allow_null=True)
    sepa_mandate_signed_at = serializers.DateField(allow_null=True)
    sepa_mandate_paper_received_at = serializers.DateField(allow_null=True)


class ChargeScheduleSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    member_number = serializers.IntegerField(
        source="member.member_number",
        default=None,
        read_only=True,
        allow_null=True,
    )
    subscription_label = serializers.SerializerMethodField()

    class Meta:
        model = ChargeSchedule
        fields = [
            "id",
            "member",
            "member_name",
            "member_number",
            "subscription",
            "subscription_label",
            "period_start",
            "period_end",
            "due_date",
            "expected_amount",
            "currency",
            "description",
            "status",
            "billing_run",
            "end_to_end_id",
        ]
        read_only_fields = [
            "id",
            "member_name",
            "member_number",
            "subscription_label",
            "billing_run",
            "end_to_end_id",
        ]

    def get_member_name(self, obj: ChargeSchedule) -> str:
        m = obj.member
        # Company members carry only ``company_name`` (no first/last); use the
        # model's canonical display name so they aren't rendered blank.
        return m.display_name or str(m)

    def get_subscription_label(self, obj: ChargeSchedule) -> str:
        """Clean label without the (physical/virtual) variation_type suffix."""
        share_type_variation = getattr(obj.subscription, "share_type_variation", None)
        if share_type_variation is None:
            return str(obj.subscription)
        share_type = getattr(share_type_variation, "share_type", "")
        size = (
            share_type_variation.get_size_display()
            if hasattr(share_type_variation, "get_size_display")
            else ""
        )
        return f"{share_type} – {size}".strip(" –")


class ChargeScheduleMonthlyIncomeSerializer(serializers.Serializer):
    """One (month, billed income) point for the DashboardAbos income chart.

    ``amount`` is a 2dp money STRING (full precision survives the wire), not a
    JSON number — mirrors the money-on-the-wire convention.
    """

    month = serializers.CharField(help_text="Due-date month, 'YYYY-MM'.")
    amount = serializers.CharField(
        help_text="Summed expected_amount for the month, 2dp string."
    )


class BillingRunSerializer(serializers.ModelSerializer):
    sepa_xml_export_url = serializers.SerializerMethodField()

    class Meta:
        model = BillingRun
        fields = [
            "id",
            "created_at",
            "created_by",
            "period_start",
            "period_end",
            "collection_date",
            "payment_method",
            "status",
            "total_amount",
            "charge_count",
            "msg_id",
            "sepa_xml_export_url",
            "notes",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "status",
            "total_amount",
            "charge_count",
            "msg_id",
            "sepa_xml_export_url",
        ]

    def get_sepa_xml_export_url(self, obj: BillingRun) -> str | None:
        return obj.sepa_xml_export.url if obj.sepa_xml_export else None


class CreateBillingRunSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    collection_date = serializers.DateField()
    payment_method = serializers.ChoiceField(
        choices=BillingRun._meta.get_field("payment_method").choices,
        default="SEPA_DD",
    )
