from rest_framework import serializers


class MemberGrowthStatisticSerializer(serializers.Serializer):
    """Serializer for member growth statistics."""

    period = serializers.DateField(help_text="Period date (start of month/week/year)")
    new_members = serializers.IntegerField(
        help_text="Number of new members in this period"
    )
    total_members = serializers.IntegerField(
        help_text="Cumulative total members up to this period"
    )


class MemberDashboardStatisticsSerializer(serializers.Serializer):
    """Snapshot ("today") of member + cooperative-share statistics."""

    total_members = serializers.IntegerField()
    trial_members = serializers.IntegerField()
    confirmed_members = serializers.IntegerField()
    pending_members = serializers.IntegerField()
    cancelled_members = serializers.IntegerField()
    average_age = serializers.FloatField(
        help_text="Average age (years) of current members with a known birth date"
    )
    total_coop_shares = serializers.FloatField()
    confirmed_coop_shares = serializers.FloatField()
    pending_coop_shares = serializers.FloatField()
    paid_coop_shares = serializers.FloatField()
    unpaid_coop_shares = serializers.FloatField()
    payback_due_coop_shares = serializers.FloatField(
        help_text="Shares owed back to cancelled members, not yet paid back"
    )
