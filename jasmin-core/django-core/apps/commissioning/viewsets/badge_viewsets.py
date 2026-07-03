from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin

from ..models import CoopShare, Member, Subscription

# All three viewsets below return ``{"count": <int>}``. Declare the shape
# once via inline_serializer so the generated frontend client gets a real
# typed wrapper instead of falling back to ``unknown``.
_COUNT_RESPONSE = inline_serializer(
    name="UnconfirmedCountResponse",
    fields={"count": drf_serializers.IntegerField()},
)


class UnconfirmedSubscriptionsViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsStaff
    # Class-level ``serializer_class`` silences spectacular's "unable to
    # guess serializer" warning. Each action also has its own
    # @extend_schema below — this is the type-discovery fallback.
    serializer_class = _COUNT_RESPONSE

    @extend_schema(responses={200: _COUNT_RESPONSE})
    @action(detail=False, methods=["get"])
    def unconfirmed_count(self, request):
        # Only subscriptions still needing office attention: not yet confirmed
        # AND not already rejected (a rejected sub is handled — don't keep the
        # badge red).
        count = (
            Subscription.objects.filter(
                Q(admin_confirmed=False) | Q(admin_confirmed__isnull=True)
            )
            .filter(admin_rejected_at__isnull=True)
            .exclude(is_trial=True)
            .count()
        )
        return Response({"count": count})


class UnconfirmedTrialSubscriptionsViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = _COUNT_RESPONSE

    @extend_schema(responses={200: _COUNT_RESPONSE})
    @action(detail=False, methods=["get"])
    def unconfirmed_count(self, request):
        # Trial subscriptions still needing attention: not yet confirmed AND not
        # already rejected.
        count = (
            Subscription.objects.filter(
                Q(admin_confirmed=False) | Q(admin_confirmed__isnull=True)
            )
            .filter(admin_rejected_at__isnull=True)
            .filter(is_trial=True)
            .count()
        )
        return Response({"count": count})


class UnconfirmedMembersViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = _COUNT_RESPONSE

    @extend_schema(responses={200: _COUNT_RESPONSE})
    @action(detail=False, methods=["get"])
    def unconfirmed_count(self, request):
        # Only members that genuinely still need office attention: not yet
        # admin-confirmed AND not already rejected. A rejected applicant has
        # been handled — counting them keeps the badge red forever.
        count = (
            Member.objects.filter(
                Q(admin_confirmed=False) | Q(admin_confirmed__isnull=True)
            )
            .filter(admin_rejected_at__isnull=True)
            .exclude(is_trial=True)
            .count()
        )
        return Response({"count": count})


class UnconfirmedCoopSharesViewSet(RolePermissionsMixin, viewsets.ViewSet):
    read_permission = IsStaff
    write_permission = IsStaff
    serializer_class = _COUNT_RESPONSE

    @extend_schema(responses={200: _COUNT_RESPONSE})
    @action(detail=False, methods=["get"])
    def unconfirmed_count(self, request):
        # Coop shares (Geschäftsanteile) still needing office confirmation: not
        # yet admin-confirmed, not already rejected, and not cancelled (a
        # cancelled share is handled — don't keep the badge red). Mirrors the
        # "pending" filter in CoopShareService.confirm_pending_for_member.
        count = (
            CoopShare.objects.filter(
                Q(admin_confirmed=False) | Q(admin_confirmed__isnull=True)
            )
            .filter(admin_rejected_at__isnull=True)
            .filter(cancelled_at__isnull=True)
            .count()
        )
        return Response({"count": count})
