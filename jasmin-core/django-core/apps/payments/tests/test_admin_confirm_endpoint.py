"""Regression test for the admin-confirmation endpoint contract.

Locks in two invariants:

1.  Confirmation MUST go through ``POST /api/commissioning/abos/{id}/confirm/``.
    That endpoint calls ``Subscription.confirm()`` which in turn invokes
    the model's ``_post_confirm`` hook — materialising Shares,
    ShareDeliveries and PLANNED ChargeSchedule rows for the term.

2.  ``PATCH`` on the regular detail route with ``{"admin_confirmed": true}``
    MUST NOT be a shortcut for confirmation:
       - either the field is rejected / read-only, or
       - the boolean flips but no side-effects fire.
    The frontend bug we lock in here was: an old admin modal PATCHed the
    flag directly, which left the subscription "confirmed" in the DB
    while ChargeSchedules and ShareDeliveries were never created.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.commissioning.models import Share, ShareDelivery
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    PaymentCycleFactory,
    SubscriptionFactory,
)
from apps.payments.constants import ChargeStatus
from apps.payments.models import ChargeSchedule


def _make_unconfirmed_subscription(member):
    # The member must hold equity within the GenG min/max window (default 3-100),
    # else confirming the subscription — which cascades member.confirm — is now
    # correctly blocked. 3 shares satisfies the default minimum.
    CoopShareFactory(member=member, amount_of_coop_shares=Decimal(3))
    sub = SubscriptionFactory(
        member=member,
        valid_from=datetime.date(2026, 6, 1),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )
    # SubscriptionFactory may default to admin_confirmed=True; force it back.
    sub.admin_confirmed = False
    sub.admin_confirmed_at = None
    sub.admin_confirmed_by = None
    sub.save(
        update_fields=[
            "admin_confirmed",
            "admin_confirmed_at",
            "admin_confirmed_by",
        ]
    )
    # Drop anything that prior factory-driven save() may have materialised.
    ChargeSchedule.objects.filter(subscription=sub).delete()
    ShareDelivery.objects.filter(subscription=sub).delete()
    return sub


@pytest.mark.django_db
class TestAdminConfirmEndpoint:
    def test_post_confirm_materialises_charges(
        self, tenant, tenant_settings, billing_profile, api_client, member
    ):
        sub = _make_unconfirmed_subscription(member)

        url = f"/api/commissioning/abos/{sub.pk}/confirm/"
        resp = api_client.post(url, data={}, format="json")

        assert resp.status_code == 200, resp.content
        sub.refresh_from_db()
        assert sub.admin_confirmed is True
        assert sub.admin_confirmed_at is not None
        # PLANNED charges must have been created for the 7-month MONTHLY term.
        planned_count = ChargeSchedule.objects.filter(
            subscription=sub, status=ChargeStatus.PLANNED
        ).count()
        assert planned_count == 7, (
            f"Expected 7 PLANNED ChargeSchedule rows for a Jun→Dec MONTHLY "
            f"subscription, got {planned_count}."
        )

    def test_double_confirm_returns_409(
        self, tenant, tenant_settings, billing_profile, api_client, member
    ):
        sub = _make_unconfirmed_subscription(member)
        url = f"/api/commissioning/abos/{sub.pk}/confirm/"
        first = api_client.post(url, data={}, format="json")
        assert first.status_code == 200, first.content

        # ``SubscriptionAlreadyConfirmed`` is a ConflictError — 409, not
        # 400 (mirrors MemberAlreadyConfirmed), with the canonical body.
        second = api_client.post(url, data={}, format="json")
        assert second.status_code == 409, second.content
        assert second.data["code"] == "subscription.already_confirmed"

    def test_patch_admin_confirmed_does_not_materialise(
        self, tenant, tenant_settings, billing_profile, api_client, member
    ):
        """PATCH on the boolean must NOT be a back-door confirmation.

        Whether the framework rejects the field or silently flips it, the
        critical invariant is the same: no side-effect rows are created.
        Going through this path leaves the subscription in a half-broken
        state from the billing layer's perspective — which is the bug we
        documented in the modal refactor.
        """
        sub = _make_unconfirmed_subscription(member)
        url = f"/api/commissioning/abos/{sub.pk}/"
        resp = api_client.patch(url, data={"admin_confirmed": True}, format="json")

        # Whatever the response code, the materialisation side-effects
        # MUST NOT have fired:
        assert (
            ChargeSchedule.objects.filter(
                subscription=sub, status=ChargeStatus.PLANNED
            ).count()
            == 0
        ), (
            "PATCHing admin_confirmed must not create ChargeSchedule rows. "
            f"Response code was {resp.status_code}."
        )
        # No shares/deliveries materialised for the term either.
        assert not ShareDelivery.objects.filter(subscription=sub).exists()
        assert not Share.objects.filter(sharedelivery__subscription=sub).exists()
