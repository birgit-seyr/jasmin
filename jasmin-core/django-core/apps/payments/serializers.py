from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.commissioning.serializers.serializers_mixin import (
    MemberStringFieldMixin,
)
from apps.shared.pii_masking import MaskedIBANFieldMixin

from .errors import MandateReferenceLocked, SepaMandateSignedInFuture
from .models import BillingProfile, BillingRun, ChargeSchedule


def validate_mandate_signature_date(value):
    """Refuse a SEPA mandate signature date that lies beyond tomorrow.

    A ``DtOfSgntr`` after today is refused at export — where it aborts the
    pain.008 batch for every other member in the run — so both the interactive
    write and the CSV import reject it at entry. The bound is one day past the
    server's today rather than today itself: the office SEPA modal derives the
    signature date from the BROWSER clock, so an operator in a timezone ahead
    of the server's ``TIME_ZONE`` signs a mandate dated the server's tomorrow.
    That one day of slack absorbs the skew and still catches the data-entry
    slips — dates weeks or months out — that a batch actually dies on.

    The rule lives here rather than on ``BillingProfile.clean()``, which runs
    on every save and would make an already-stored future date permanently
    un-saveable, including the export's own first-use stamp.
    """
    if value is not None and value > timezone.localdate() + timedelta(days=1):
        raise SepaMandateSignedInFuture(
            "A SEPA mandate cannot be dated after today.",
            field="sepa_mandate_signed_at",
        )
    return value


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
        # The owning ``member`` FK is set ONCE at create (the SEPA-setup
        # flow POSTs it) and must never be reassigned on update — pointing an
        # existing profile at another member would hand over their SEPA setup.
        # Lock it read-only for updates only (an instance is bound), leaving it
        # writable on create where it's the sole source of the link.
        if self.instance is not None:
            self.fields["member"].read_only = True

    def validate_sepa_mandate_reference(self, value):
        # Once a mandate has been collected against, the bank matches every
        # following RCUR transaction to the reference it holds on file, so a
        # changed reference orphans the mandate. Resubmitting the stored value
        # is accepted: the office SEPA form sends the whole mandate block back
        # on every save.
        if (
            self.instance is not None
            and self.instance.sepa_mandate_first_use_at is not None
            and value != self.instance.sepa_mandate_reference
        ):
            raise MandateReferenceLocked(
                "The mandate reference cannot be changed after the mandate "
                "has been used.",
                field="sepa_mandate_reference",
            )
        return value

    def validate_sepa_mandate_signed_at(self, value):
        return validate_mandate_signature_date(value)


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
    ``BillingProfileSerializer`` list — must NOT trip the bank-identifier
    audit trail. ``has_active_sepa_mandate`` mirrors ``is_sepa_ready``; the
    per-subscription "active during the term" refinement is applied by the
    caller (it needs the subscription's dates).
    """

    member = serializers.CharField(source="member_id")
    has_active_sepa_mandate = serializers.BooleanField(
        source="is_sepa_ready", read_only=True
    )
    payment_method = serializers.CharField()
    # ``is_active`` lets the shared status tag distinguish a manually
    # deactivated mandate (inactive) from an incomplete one — the same
    # 4-state tag the SEPA mandates page renders from the full profile.
    # Still no bank identifiers, so the PII-read audit line stays untripped.
    is_active = serializers.BooleanField(read_only=True)
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
        member = obj.member
        # Company members carry only ``company_name`` (no first/last); use the
        # model's canonical display name so they aren't rendered blank.
        return member.display_name or str(member)

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


class SepaMandateImportSerializer(serializers.Serializer):
    """CSV import for SEPA direct-debit mandates (onboarding existing mandates).

    A mandate is not its own model — it is the SEPA fields on a member's
    ``BillingProfile`` (one per member). Rows are keyed by ``member_number``
    (natural key) and CREATE that member's billing profile.

    **Create-only.** A member who ALREADY has a billing profile is reported as a
    per-row conflict and left untouched — a live mandate at the bank must never
    be silently redirected. The ``sepa_mandate_reference`` from the CSV is
    preserved when given (continuity with the member's existing mandate) and
    auto-generated by ``BillingProfile.save()`` when blank. ``full_clean()`` in
    ``save()`` validates the IBAN + the SEPA-required fields per row.

    The IBAN / holder are ALSO mirrored onto the member's own encrypted
    ``Member.iban`` / ``Member.account_owner`` columns (fill-only) so the
    office members grid does not show a blank IBAN for a freshly onboarded
    member — see ``_mirror_bank_details_to_member``.

    Column contract (the downloadable template mirrors this):

      member_number                  int   — Member.member_number (unique)
      account_holder                 str   — name on the bank account
      iban                           str   — validated IBAN
      sepa_mandate_reference         str   — optional; blank → auto-generated
      sepa_mandate_signed_at         date  — signed date (YYYY-MM-DD)
      sepa_mandate_paper_received_at date  — optional; paper mandate received
    """

    member_number = serializers.IntegerField()
    account_holder = serializers.CharField()
    iban = serializers.CharField()
    sepa_mandate_reference = serializers.CharField(required=False, allow_blank=True)
    sepa_mandate_signed_at = serializers.DateField()
    sepa_mandate_paper_received_at = serializers.DateField(
        required=False, allow_null=True
    )

    def validate_sepa_mandate_signed_at(self, value):
        return validate_mandate_signature_date(value)

    @staticmethod
    def _resolve_member(number: int):
        from apps.commissioning.models import Member

        member = Member.objects.filter(member_number=number).first()
        if member is None:
            raise serializers.ValidationError(
                {"member_number": f"No member with number {number}."}
            )
        return member

    def validate(self, attrs):
        member = self._resolve_member(attrs["member_number"])
        # Create-only: never touch an existing profile / live mandate.
        if BillingProfile.objects.filter(member=member).exists():
            raise serializers.ValidationError(
                {
                    "member_number": (
                        f"Member {attrs['member_number']} already has a billing "
                        "profile — skipped (create-only import; an existing "
                        "profile/mandate is never overwritten)."
                    )
                }
            )
        attrs["_member"] = member
        return attrs

    @staticmethod
    def _mirror_bank_details_to_member(member, validated_data) -> None:
        """Copy the mandate's IBAN / holder onto the member's OWN columns.

        ``Member.iban`` / ``Member.account_owner`` are a SEPARATE encrypted
        pair from ``BillingProfile.iban`` / ``account_holder`` — nothing syncs
        them, and only the BillingProfile copy drives collection (it is what
        the pain.008 debtor block reads). The Member copy is what the office
        members grid shows, so an onboarded member whose mandate imported fine
        would otherwise show a blank IBAN there and look half-migrated.

        **Fill-only, never overwrite.** A differing value already on the member
        is left alone: silently rewriting a stored IBAN is not what a mandate
        import is for, even though a real import is step-up gated like the
        interactive IBAN edit. In practice the member is always blank here —
        the caller is create-only, so it never runs for a member who already
        has a profile.
        """
        updated_fields: list[str] = []
        if not member.iban:
            member.iban = validated_data["iban"]
            updated_fields.append("iban")
        if not member.account_owner:
            member.account_owner = validated_data["account_holder"]
            updated_fields.append("account_owner")
        if updated_fields:
            member.save(update_fields=updated_fields)

    def create(self, validated_data) -> BillingProfile:
        from .constants import PaymentMethodOptions

        member = validated_data["_member"]
        profile = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban=validated_data["iban"],
            account_holder=validated_data["account_holder"],
            # Blank → None so the model's ``save()`` mints a fresh reference
            # (an empty string would collide on the unique column).
            sepa_mandate_reference=(
                validated_data.get("sepa_mandate_reference") or None
            ),
            sepa_mandate_signed_at=validated_data["sepa_mandate_signed_at"],
            sepa_mandate_paper_received_at=validated_data.get(
                "sepa_mandate_paper_received_at"
            ),
        )
        # Same per-row transaction as the profile insert (the importer wraps
        # each row), so a failure here rolls the mandate back too rather than
        # leaving a profile with no matching member record.
        self._mirror_bank_details_to_member(member, validated_data)
        return profile
