"""CSV import serializer for cooperative shares (member equity onboarding).

A ``CoopShare`` is a member's GenG cooperative-equity position. A bulk
onboarding CSV references the member by ``member_number`` (natural key) and
CREATES the share as **unconfirmed** (``admin_confirmed=False``) — the office
confirms it afterwards, mirroring the interactive create flow. ``save()`` runs
``full_clean()``, so the GenG min/max equity window (``CoopShare.clean`` →
``CoopShareService.assert_within_min_max``) is enforced per row; a row that would
push the member outside the window comes back as a per-row error.

NOTE: ``Share`` and ``CoopShare`` are fundamentally different models — this is
coop_share (equity), never Share (a delivery-share).
"""

from __future__ import annotations

from rest_framework import serializers

from ..models import CoopShare, Member


class CoopShareImportSerializer(serializers.Serializer):
    """Import one cooperative-share row for an existing member.

    Column contract (the downloadable template mirrors this):

      member_number          int   — Member.member_number (unique)
      amount_of_coop_shares  dec   — number of shares the member holds
      value_one_coop_share   int   — value of a single share (currency units)
      is_increase            bool  — an increase over the mandatory amount
                                     (default false)
      due_date               date  — optional payment deadline (YYYY-MM-DD)
      paid_at                date  — optional date the member actually paid
      note                   str   — optional free-text note

    ``due_date`` / ``paid_at`` come from ``PayableMixin`` and are the pair the
    office manages side by side on the coop-shares grid. A tenant migrating
    existing equity brings both over — an onboarded share whose payment history
    is lost would look unpaid and land in the office's outstanding list.

    There is deliberately NO ``paid_at >= due_date`` invariant (see
    ``PayableMixin``): ``due_date`` is a DEADLINE, so paying early is normal.
    """

    member_number = serializers.IntegerField()
    amount_of_coop_shares = serializers.DecimalField(max_digits=10, decimal_places=2)
    value_one_coop_share = serializers.IntegerField(min_value=1)
    is_increase = serializers.BooleanField(required=False, default=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    # ``CoopShare.paid_at`` is a DateTimeField, but the office grid edits it as
    # a plain date — a bare ``YYYY-MM-DD`` cell is accepted and DRF anchors it
    # to midnight in the active timezone.
    paid_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

    @staticmethod
    def _resolve_member(number: int) -> Member:
        member = Member.objects.filter(member_number=number).first()
        if member is None:
            raise serializers.ValidationError(
                {"member_number": f"No member with number {number}."}
            )
        return member

    def validate_amount_of_coop_shares(self, value):
        from ..services.coop_share_service import CoopShareService

        # A cooperative share is a whole Geschäftsanteil — the same rule as the
        # office grid and member self-service (zero, negative and fractional
        # amounts come back as a per-row error).
        CoopShareService.assert_valid_amount(value)
        return value

    def validate(self, attrs):
        attrs["_member"] = self._resolve_member(attrs["member_number"])
        return attrs

    def create(self, validated_data) -> CoopShare:
        # Unconfirmed — the office confirms through the normal flow (which keeps
        # the GenG §30/§31 audit trail). ``save()`` → ``full_clean()`` enforces
        # the min/max equity window per row.
        return CoopShare.objects.create(
            member=validated_data["_member"],
            amount_of_coop_shares=validated_data["amount_of_coop_shares"],
            value_one_coop_share=validated_data["value_one_coop_share"],
            is_increase=bool(validated_data.get("is_increase")),
            due_date=validated_data.get("due_date"),
            paid_at=validated_data.get("paid_at"),
            note=validated_data.get("note") or "",
        )
