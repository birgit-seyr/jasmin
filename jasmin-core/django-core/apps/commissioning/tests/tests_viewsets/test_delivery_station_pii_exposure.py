"""What a member may read off a delivery station.

``DeliveryStationViewSet`` is ``IsStaffOrMember`` and, without a ``?member=``
scope, its queryset is the whole tenant catalogue — so every field the
serializer emits is readable by every member-role login, for every station.

Two things must therefore not be in that payload. ``ContactEntity.iban`` is an
``EncryptedCharField``; it reaches the row at all only because
``get_contact_annotations`` flattens every scalar contact column onto the
queryset, and ``ResellerSerializer`` already drops it over the same shared row
rather than undo encryption-at-rest for a bulk read. The station-operational
block (door code, host's direct line) is what a member needs for the stop they
actually collect from, and nobody else's.
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.urls import reverse
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    MemberFactory,
    SubscriptionFactory,
)

IBAN = "DE89370400440532013000"
ACCESS_CODE = "gate-4711"
OPERATIONAL_FIELDS = (
    "access_code",
    "contact_name",
    "contact_phone",
    "messenger_group_link",
)

# A Monday inside ``SubscriptionFactory``'s default 2026-01-05 → 2027-01-03
# window. ``get_queryset`` decides "is this subscription still current" against
# the wall clock, so an unfrozen run would start failing once real time passes
# the factory's ``valid_until``.
FROZEN_NOW = datetime.datetime(2026, 6, 1, 12, 0)


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(FROZEN_NOW, tick=False):
        yield


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _station_with_bank_details(**kwargs):
    contact = ContactEntityFactory(
        iban=IBAN, address="Hauptstrasse 1", zip_code="4051", city="Basel"
    )
    return DeliveryStationFactory(
        contact=contact,
        access_code=ACCESS_CODE,
        contact_name="Station Host",
        contact_phone="+41 61 000 00 00",
        messenger_group_link="https://example.test/group",
        **kwargs,
    )


def _rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.mark.django_db
class TestDeliveryStationMemberExposure:
    URL = reverse("delivery_station-list")

    def test_member_never_receives_a_station_iban(self, tenant, member_user):
        _station_with_bank_details()

        response = _client(member_user).get(self.URL)

        assert response.status_code == 200
        rows = _rows(response)
        assert (
            rows
        ), "fixture produced no stations — the assertions below would be vacuous"
        for row in rows:
            # Both the raw key and the value: a masked or absent field is fine,
            # the decrypted account number is not.
            assert row.get("iban") in (None, ""), "the decrypted IBAN is on the wire"
            assert IBAN not in str(row)

    def test_staff_never_receive_a_station_iban_either(self, tenant, api_client):
        _station_with_bank_details()

        response = api_client.get(self.URL)

        assert response.status_code == 200
        for row in _rows(response):
            assert IBAN not in str(row)

    def test_member_cannot_read_the_door_code_of_a_foreign_station(
        self, tenant, member_user
    ):
        _station_with_bank_details()

        response = _client(member_user).get(self.URL)

        assert response.status_code == 200
        for row in _rows(response):
            for field in OPERATIONAL_FIELDS:
                assert not row.get(field), (
                    f"{field} of a station this member does not collect from "
                    f"is readable"
                )

    def test_member_still_reads_the_door_code_of_their_own_station(
        self, tenant, member_user
    ):
        """The pickup modal depends on this — the fix must not black it out."""
        own = _station_with_bank_details()
        member = MemberFactory(user=member_user)
        SubscriptionFactory(
            member=member,
            admin_confirmed=True,
            default_delivery_station_day=DeliveryStationDayFactory(
                delivery_station=own
            ),
        )

        response = _client(member_user).get(self.URL)

        assert response.status_code == 200
        mine = [row for row in _rows(response) if row["id"] == own.id]
        assert mine, "the member's own station is missing from the catalogue"
        assert mine[0]["access_code"] == ACCESS_CODE
        # …and still no bank details, even on their own station.
        assert IBAN not in str(mine[0])
