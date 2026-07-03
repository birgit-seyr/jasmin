"""SEC-2: the DeliveryExceptionPeriod list is member-readable. A member must
see ONLY the pauses on variations they subscribe to, and never the office
free-text ``note``; staff see every pause with its note.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    DeliveryExceptionPeriodFactory,
    JasminUserFactory,
    MemberFactory,
    SubscriptionFactory,
)


@pytest.mark.django_db
class TestDeliveryExceptionMemberScoping:
    URL = reverse("delivery_exception_periods-list")

    def _member_client(self):
        member_user = JasminUserFactory(roles=["member"])
        member = MemberFactory(user=member_user)
        client = APIClient()
        client.force_authenticate(user=member_user)
        return client, member

    def test_staff_sees_all_periods_including_the_note(self, api_client, tenant):
        DeliveryExceptionPeriodFactory(note="office secret")
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert any(row.get("note") == "office secret" for row in resp.data)

    def test_member_sees_only_own_variation_and_no_note(self, tenant):
        client, member = self._member_client()
        # A pause on the member's OWN subscribed variation ...
        mine = SubscriptionFactory(member=member)
        my_pause = DeliveryExceptionPeriodFactory(
            share_type_variation=mine.share_type_variation, note="secret A"
        )
        # ... and one on a variation the member does NOT subscribe to.
        DeliveryExceptionPeriodFactory(note="secret B")

        resp = client.get(self.URL)

        assert resp.status_code == status.HTTP_200_OK
        # Only the member's own variation is returned — no cross-variation leak.
        assert {row["id"] for row in resp.data} == {my_pause.id}
        # The office note is stripped from every member-visible row.
        assert all("note" not in row for row in resp.data)

    def test_member_without_subscriptions_sees_nothing(self, tenant):
        DeliveryExceptionPeriodFactory()
        client, _member = self._member_client()
        resp = client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []
