"""Public (no-login) waiting-list offer endpoints.

The office offers a freed spot; the member accepts or declines from the email's
magic link WITHOUT logging in. ``AllowAny`` is safe because the
``notification_token`` in the URL *is* the credential — single-use, minted per
offer and cleared on any response (accept / decline / expiry). Tenant-scoped by
subdomain like the rest of the tenant API.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..errors import WaitingListOfferInvalid
from ..services.waiting_list_offer_service import WaitingListOfferService


def _format_address(contact) -> str:
    """ "<street>, <zip> <city>" from a ContactEntity, skipping blank parts."""
    if contact is None:
        return ""
    street = getattr(contact, "address", "") or ""
    zip_code = getattr(contact, "zip_code", "") or ""
    city = getattr(contact, "city", "") or ""
    locality = " ".join(p for p in (zip_code, city) if p)
    return ", ".join(p for p in (street, locality) if p)


def _offer_payload(subscription) -> dict:
    """Flat, PII-light view of an offer for the public accept page."""
    variation = subscription.share_type_variation
    share_type = getattr(variation, "share_type", None) if variation else None
    station_day = subscription.default_delivery_station_day
    station = getattr(station_day, "delivery_station", None) if station_day else None
    contact = getattr(station, "contact", None) if station else None
    member = subscription.member
    return {
        "member_first_name": getattr(member, "first_name", "") or "",
        # Share-type name + RAW size sent separately: the client composes
        # "<qty> × <name> <size-label>" and LOCALIZES the size itself.
        # ``share_type_variation_string`` bakes in the untranslated size, so it
        # can't be re-localized downstream — hence name + size here.
        "variation_name": getattr(share_type, "name", "") or "",
        "variation_size": getattr(variation, "size", "") or "",
        "delivery_station_name": (
            getattr(contact, "name", "")
            or getattr(station_day, "delivery_station_short_name", "")
            or ""
        ),
        "delivery_station_address": _format_address(contact),
        "valid_from": (
            subscription.valid_from.isoformat() if subscription.valid_from else None
        ),
        "valid_until": (
            subscription.valid_until.isoformat() if subscription.valid_until else None
        ),
        "quantity": subscription.quantity,
        # Money on the wire as a canonical string (never float) — see the money
        # hygiene rule.
        "price_per_delivery": (
            str(subscription.price_per_delivery)
            if subscription.price_per_delivery is not None
            else None
        ),
        "status": subscription.waiting_list_status,
        "expires_at": (
            subscription.notification_expires_at.isoformat()
            if subscription.notification_expires_at
            else None
        ),
        "expired": subscription.has_expired_notification,
    }


_OFFER_RESPONSE = inline_serializer(
    name="WaitingListOfferDetail",
    fields={
        "member_first_name": drf_serializers.CharField(allow_blank=True),
        "variation_name": drf_serializers.CharField(allow_blank=True),
        "variation_size": drf_serializers.CharField(allow_blank=True),
        "delivery_station_name": drf_serializers.CharField(allow_blank=True),
        "delivery_station_address": drf_serializers.CharField(allow_blank=True),
        "valid_from": drf_serializers.CharField(allow_null=True),
        "valid_until": drf_serializers.CharField(allow_null=True),
        "quantity": drf_serializers.IntegerField(),
        "price_per_delivery": drf_serializers.CharField(allow_null=True),
        "status": drf_serializers.CharField(),
        "expires_at": drf_serializers.CharField(allow_null=True),
        "expired": drf_serializers.BooleanField(),
    },
)


class WaitingListOfferDetailView(APIView):
    """GET the offer behind a token — drives the member's accept/decline page."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: _OFFER_RESPONSE})
    def get(self, request: Request, token) -> Response:
        subscription = WaitingListOfferService.get_open_offer(token)
        if subscription is None:
            raise WaitingListOfferInvalid(
                "This offer link is invalid or has already been used."
            )
        return Response(_offer_payload(subscription))


class WaitingListOfferAcceptView(APIView):
    """The member accepts — the subscription leaves the waiting list as a
    normal, not-yet-admin-confirmed abo."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={200: _OFFER_RESPONSE})
    def post(self, request: Request, token) -> Response:
        subscription = WaitingListOfferService.accept_offer(token)
        return Response(_offer_payload(subscription))


class WaitingListOfferDeclineView(APIView):
    """The member declines — the held slot is freed."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={200: _OFFER_RESPONSE})
    def post(self, request: Request, token) -> Response:
        subscription = WaitingListOfferService.decline_offer(token)
        return Response(_offer_payload(subscription))
