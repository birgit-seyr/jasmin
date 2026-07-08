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


class PurchaseCostByWeekSerializer(serializers.Serializer):
    """One (ISO week, purchase cost) point for the purchase-statistics bar chart.

    ``amount`` is the total money spent buying in purchased ("Zukauf") share
    articles that week — a 2dp money STRING (full precision survives the wire),
    not a JSON number, mirroring the money-on-the-wire convention.
    """

    year = serializers.IntegerField(help_text="ISO year of the delivery week.")
    week = serializers.IntegerField(help_text="ISO delivery week (1–53).")
    amount = serializers.CharField(
        help_text="Total purchase cost for the week, 2dp string."
    )
