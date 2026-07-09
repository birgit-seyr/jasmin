from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.authz.permissions import IsStaff, RolePermissionsMixin

from ..models import CoopShare, Member, Subscription

# All four badge counters below return ``{"count": <int>}``. Declare the shape
# once via inline_serializer so the generated frontend client gets a real
# typed wrapper instead of falling back to ``unknown``.
_COUNT_RESPONSE = inline_serializer(
    name="UnconfirmedCountResponse",
    fields={"count": drf_serializers.IntegerField()},
)


def pending_admin_confirmation_q() -> Q:
    """Queryset predicate mirroring ``AdminConfirmableMixin.is_pending``.

    A row is "pending admin confirmation" when it is not yet confirmed
    (``admin_confirmed`` False — or NULL, defensively) AND not already rejected
    (``admin_rejected_at`` is NULL). A rejected application has been handled, so
    it must not keep a "needs attention" badge lit.

    This is the queryset equivalent of the row-level ``is_pending`` property;
    keep the two in lockstep. The generic badge counters below and the
    members_viewsets coop-share pending subquery both build on it, so the
    definition of "pending" stays single-sourced (no more silently dropping the
    ``admin_confirmed__isnull=True`` branch).
    """
    return (Q(admin_confirmed=False) | Q(admin_confirmed__isnull=True)) & Q(
        admin_rejected_at__isnull=True
    )


class _PendingCountViewSet(RolePermissionsMixin, viewsets.ViewSet):
    """Base for the "needs office confirmation" badge counters.

    Each subclass sets ``count_model`` (an ``AdminConfirmableMixin`` model) and
    optionally narrows the base ``pending_admin_confirmation_q()`` predicate via
    ``extra_filter`` (a ``.filter``) / ``exclude_filter`` (an ``.exclude``) — the
    trial split and the cancelled-coop-share carve-out. Returns
    ``{"count": <int>}``.
    """

    read_permission = IsStaff
    write_permission = IsStaff
    # Class-level ``serializer_class`` silences spectacular's "unable to guess
    # serializer" warning. Each action also has its own @extend_schema below —
    # this is the type-discovery fallback.
    serializer_class = _COUNT_RESPONSE

    count_model: type | None = None
    extra_filter: dict | None = None
    exclude_filter: dict | None = None

    @extend_schema(responses={200: _COUNT_RESPONSE})
    @action(detail=False, methods=["get"])
    def unconfirmed_count(self, request):
        queryset = self.count_model.objects.filter(pending_admin_confirmation_q())
        if self.extra_filter:
            queryset = queryset.filter(**self.extra_filter)
        if self.exclude_filter:
            queryset = queryset.exclude(**self.exclude_filter)
        return Response({"count": queryset.count()})


class UnconfirmedSubscriptionsViewSet(_PendingCountViewSet):
    # Non-trial subscriptions still needing office attention.
    count_model = Subscription
    exclude_filter = {"is_trial": True}


class UnconfirmedTrialSubscriptionsViewSet(_PendingCountViewSet):
    # Trial subscriptions still needing office attention.
    count_model = Subscription
    extra_filter = {"is_trial": True}


class UnconfirmedMembersViewSet(_PendingCountViewSet):
    # Non-trial members still awaiting admin confirmation.
    count_model = Member
    exclude_filter = {"is_trial": True}


class UnconfirmedCoopSharesViewSet(_PendingCountViewSet):
    # Coop shares (Geschäftsanteile) still needing office confirmation and not
    # cancelled (a cancelled share is handled — don't keep the badge lit).
    # CoopShare keeps its own ``cancelled_at`` clause; no conflation with the
    # subscription/member counters.
    count_model = CoopShare
    extra_filter = {"cancelled_at__isnull": True}
