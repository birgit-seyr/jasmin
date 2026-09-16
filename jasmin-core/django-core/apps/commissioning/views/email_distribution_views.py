"""Subscription-based e-mail distribution lists for the AbosEmails page.

Office builds a copyable recipient list by filtering active subscriptions —
"everyone picking up at this delivery-station-day", "everyone with this share
type", or "everyone active in this date range".
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice
from core.serializers import ErrorResponseSerializer

from ..models import Member, Subscription
from ..models.managers import active_on_date_q
from ..schemas import catalogue_param
from ..serializers import SubscriptionMemberEmailsResponseSerializer
from ..utils.query_params import validate_query_params


@extend_schema(
    summary="Member e-mails for a subscription filter (distribution list)",
    description=(
        "Distinct e-mail addresses of members holding a confirmed, "
        "non-waiting-list subscription that matches the filter — a copyable "
        "e-mail distribution list for the AbosEmails page.\n\n"
        "Base filter: ``admin_confirmed=True``, ``on_waiting_list=False``, "
        "active in the window, and — where the window has a start — not "
        "cancelled effective before that start. Each "
        "bound of the active window applies on its own: ``date_from`` alone "
        "means 'still running on or after that date', ``date_to`` alone "
        "'already started by that date', both together the overlap with "
        "``[date_from, date_to]``, and neither collapses the window to today. "
        "Sending ``date_from`` after ``date_to`` is refused (400) rather than "
        "served as a backwards window. "
        "``delivery_station_day`` and ``share_type`` narrow "
        "it further; combine freely. Each member's primary and secondary "
        "addresses (``email`` / ``email_2`` / ``email_3``) are all included; "
        "blanks, non-address junk, and duplicates are dropped."
    ),
    parameters=[
        catalogue_param(
            "delivery_station_day",
            required=False,
            description="Only subscriptions assigned to this DeliveryStationDay id.",
        ),
        catalogue_param(
            "share_type",
            required=False,
            description="Only subscriptions whose variation belongs to this ShareType id.",
        ),
        catalogue_param(
            "date_from",
            required=False,
            description="Active-window start (YYYY-MM-DD). With ``date_to``, matches "
            "subscriptions whose term overlaps the range.",
        ),
        catalogue_param(
            "date_to", required=False, description="Active-window end (YYYY-MM-DD)."
        ),
    ],
    responses={
        200: SubscriptionMemberEmailsResponseSerializer,
        400: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([IsOffice])
def subscription_member_emails(request: Request) -> Response:
    """Return the distinct member e-mails for the given subscription filter."""
    params = validate_query_params(
        request,
        optional=["delivery_station_day", "share_type", "date_from", "date_to"],
    )
    delivery_station_day = params["delivery_station_day"]
    share_type = params["share_type"]
    date_from = params["date_from"]
    date_to = params["date_to"]

    today = timezone.now().date()
    # The cancellation cutoff is the start of the requested window: a
    # subscription cancelled effective before it was already gone by then.
    # A window open at the start (``date_to`` alone) has no such cutoff — the
    # term filter alone decides. With no bound at all the window is today.
    window_start = date_from if (date_from or date_to) else today

    subscriptions = Subscription.objects.filter(
        admin_confirmed=True, on_waiting_list=False
    )
    if window_start is not None:
        subscriptions = subscriptions.filter(
            # A cancellation effective on or after the window start was still
            # in the future for part of it, so the subscription counts.
            Q(cancelled_effective_at__isnull=True)
            | Q(cancelled_effective_at__gte=window_start)
        )

    if date_from or date_to:
        # Each bound narrows the term overlap independently, so a one-sided
        # window means what it says: with only ``date_from`` the window runs
        # from that date onwards, with only ``date_to`` it runs up to it.
        if date_to:
            subscriptions = subscriptions.filter(valid_from__lte=date_to)
        if date_from:
            subscriptions = subscriptions.filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=date_from)
            )
    else:
        subscriptions = subscriptions.filter(active_on_date_q(today))

    if delivery_station_day:
        subscriptions = subscriptions.filter(
            default_delivery_station_day_id=delivery_station_day
        )
    if share_type:
        subscriptions = subscriptions.filter(
            share_type_variation__share_type_id=share_type
        )

    # A member can carry up to three contact addresses: the primary ``email``
    # plus two optional secondary CharFields (``email_2`` / ``email_3``). All
    # of them belong in the distribution list. Skip blanks and non-address
    # junk (the secondaries aren't validated as e-mail), and de-duplicate
    # case-insensitively across the whole result (the secondaries aren't
    # unique and may repeat another member's address).
    rows = (
        Member.objects.filter(id__in=subscriptions.values("member_id"))
        .order_by("last_name", "first_name", "email")
        .values("email", "email_2", "email_3", "first_name", "last_name")
    )
    seen: set[str] = set()
    members: list[dict] = []
    for row in rows:
        for field in ("email", "email_2", "email_3"):
            address = (row[field] or "").strip()
            if "@" not in address:
                continue
            key = address.lower()
            if key in seen:
                continue
            seen.add(key)
            members.append(
                {
                    "email": address,
                    "first_name": row["first_name"],
                    "last_name": row["last_name"],
                }
            )
    payload = {"count": len(members), "members": members}
    return Response(
        SubscriptionMemberEmailsResponseSerializer(payload).data,
        status=status.HTTP_200_OK,
    )
