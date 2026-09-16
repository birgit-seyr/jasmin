"""Tests for the subscription-based e-mail distribution endpoint
(``subscription_member_emails`` — powers the AbosEmails page)."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
import time_machine

from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

URL = "/api/commissioning/subscription_member_emails/"


def _emails(resp) -> set[str]:
    return {row["email"] for row in resp.data["members"]}


@pytest.fixture
def catalogue(tenant):
    """Two share types (each a variation) + two delivery-station-days."""
    veg = ShareTypeFactory(share_option="HARVEST_SHARE")
    fruit = ShareTypeFactory(share_option="HARVEST_SHARE_FRUIT")
    return SimpleNamespace(
        veg=veg,
        fruit=fruit,
        var_veg=ShareTypeVariationFactory(share_type=veg, size="M"),
        var_fruit=ShareTypeVariationFactory(share_type=fruit, size="S"),
        # Distinct day_number: SharesDeliveryDay is one-open-per-day_number.
        dsd1=DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=2)
        ),
        dsd2=DeliveryStationDayFactory(
            delivery_day=SharesDeliveryDayFactory(day_number=3)
        ),
    )


def _confirmed_sub(member, variation, dsd, **kw):
    kw.setdefault("admin_confirmed", True)
    return SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=dsd,
        **kw,
    )


@pytest.mark.django_db
class TestSubscriptionMemberEmails:
    def test_filter_by_delivery_station_day(self, api_client, catalogue):
        anna = MemberFactory(email="anna@x.de", last_name="Alt")
        bea = MemberFactory(email="bea@x.de", last_name="Boll")
        cara = MemberFactory(email="cara@x.de", last_name="Cern")
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(bea, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(cara, catalogue.var_fruit, catalogue.dsd2)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.status_code == 200
        assert resp.data["count"] == 2
        assert _emails(resp) == {"anna@x.de", "bea@x.de"}

        resp2 = api_client.get(URL, {"delivery_station_day": catalogue.dsd2.id})
        assert _emails(resp2) == {"cara@x.de"}

    def test_filter_by_share_type(self, api_client, catalogue):
        anna = MemberFactory(email="anna@x.de")
        cara = MemberFactory(email="cara@x.de")
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(cara, catalogue.var_fruit, catalogue.dsd2)

        resp = api_client.get(URL, {"share_type": catalogue.veg.id})
        assert _emails(resp) == {"anna@x.de"}
        resp2 = api_client.get(URL, {"share_type": catalogue.fruit.id})
        assert _emails(resp2) == {"cara@x.de"}

    def test_excludes_unconfirmed_waiting_and_cancelled(self, api_client, catalogue):
        active = MemberFactory(email="active@x.de")
        _confirmed_sub(active, catalogue.var_veg, catalogue.dsd1)
        # Unconfirmed draft.
        _confirmed_sub(
            MemberFactory(email="draft@x.de"),
            catalogue.var_veg,
            catalogue.dsd1,
            admin_confirmed=False,
        )
        # Waiting-list entry.
        _confirmed_sub(
            MemberFactory(email="waiting@x.de"),
            catalogue.var_veg,
            catalogue.dsd1,
            on_waiting_list=True,
        )
        # Cancelled with an effective date already in the past.
        _confirmed_sub(
            MemberFactory(email="cancelled@x.de"),
            catalogue.var_veg,
            catalogue.dsd1,
            cancelled_at=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            cancelled_effective_at=datetime.date(2026, 3, 2),  # Monday, past
        )

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert _emails(resp) == {"active@x.de"}

    def test_omits_members_without_email(self, api_client, catalogue):
        anna = MemberFactory(email="anna@x.de")
        no_email = MemberFactory(email=None)
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(no_email, catalogue.var_veg, catalogue.dsd1)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.data["count"] == 1
        assert _emails(resp) == {"anna@x.de"}

    def test_includes_secondary_emails(self, api_client, catalogue):
        anna = MemberFactory(
            email="anna@x.de",
            email_2="anna.work@x.de",
            email_3="anna.private@x.de",
        )
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.data["count"] == 3
        assert _emails(resp) == {
            "anna@x.de",
            "anna.work@x.de",
            "anna.private@x.de",
        }

    def test_skips_blank_and_junk_secondary_emails(self, api_client, catalogue):
        anna = MemberFactory(
            email="anna@x.de",
            email_2="   ",  # blank
            email_3="not-an-email",  # no "@"
        )
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.data["count"] == 1
        assert _emails(resp) == {"anna@x.de"}

    def test_secondary_email_deduplicated_across_members(self, api_client, catalogue):
        # A shared household address sits on Anna's primary and Bea's secondary.
        anna = MemberFactory(email="shared@x.de")
        bea = MemberFactory(email="bea@x.de", email_2="Shared@x.de")
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(bea, catalogue.var_veg, catalogue.dsd1)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        # 3 raw addresses, but the shared one collapses (case-insensitively).
        # Which case-variant of the shared address survives ("shared@x.de" vs
        # "Shared@x.de") is a first-seen tiebreak driven by member sort order,
        # which depends on the randomly generated Faker names -- both are
        # correct per the endpoint's case-insensitive contract, so compare
        # case-insensitively.
        assert resp.data["count"] == 2
        assert {e.lower() for e in _emails(resp)} == {"shared@x.de", "bea@x.de"}

    def test_member_with_multiple_matching_subs_listed_once(
        self, api_client, catalogue
    ):
        anna = MemberFactory(email="anna@x.de")
        _confirmed_sub(anna, catalogue.var_veg, catalogue.dsd1)
        _confirmed_sub(anna, catalogue.var_fruit, catalogue.dsd1)

        resp = api_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.data["count"] == 1
        assert _emails(resp) == {"anna@x.de"}

    def test_office_only(self, anon_client, catalogue):
        resp = anon_client.get(URL, {"delivery_station_day": catalogue.dsd1.id})
        assert resp.status_code in (401, 403)


@pytest.mark.django_db
class TestSubscriptionMemberEmailsDateWindow:
    """Each bound of the active window applies on its own.

    ``date_from`` alone means "still running on or after that date",
    ``date_to`` alone "already started by that date", both together the
    overlap, and neither collapses the window to today. The cancellation
    cutoff follows the window's start — and a window with no start has none.

    The clock is frozen because the no-bounds case, and the cancellation
    cutoff, are resolved against today.
    """

    # Monday, comfortably inside the "current" term below.
    FROZEN_NOW = datetime.date(2026, 3, 30)

    @pytest.fixture
    def terms(self, catalogue):
        """Three subscriptions on the same station-day: one already finished,
        one running at the frozen "now", one starting later."""
        return SimpleNamespace(
            past=_confirmed_sub(
                MemberFactory(email="past@x.de"),
                catalogue.var_veg,
                catalogue.dsd1,
                valid_from=datetime.date(2026, 1, 5),
                valid_until=datetime.date(2026, 2, 1),
            ),
            current=_confirmed_sub(
                MemberFactory(email="current@x.de"),
                catalogue.var_veg,
                catalogue.dsd1,
                valid_from=datetime.date(2026, 3, 2),
                valid_until=datetime.date(2026, 4, 26),
            ),
            future=_confirmed_sub(
                MemberFactory(email="future@x.de"),
                catalogue.var_veg,
                catalogue.dsd1,
                valid_from=datetime.date(2026, 6, 1),
                valid_until=datetime.date(2026, 8, 30),
            ),
        )

    def _request(self, api_client, catalogue, **params):
        return api_client.get(
            URL, {"delivery_station_day": catalogue.dsd1.id, **params}
        )

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_no_bounds_means_active_today(self, api_client, catalogue, terms):
        resp = self._request(api_client, catalogue)
        assert _emails(resp) == {"current@x.de"}

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_date_from_alone_leaves_the_end_open(self, api_client, catalogue, terms):
        resp = self._request(api_client, catalogue, date_from="2026-05-01")
        assert _emails(resp) == {"future@x.de"}

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_date_to_alone_leaves_the_start_open(self, api_client, catalogue, terms):
        resp = self._request(api_client, catalogue, date_to="2026-02-15")
        assert _emails(resp) == {"past@x.de"}

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_both_bounds_match_the_overlap(self, api_client, catalogue, terms):
        resp = self._request(
            api_client, catalogue, date_from="2026-03-01", date_to="2026-05-31"
        )
        assert _emails(resp) == {"current@x.de"}

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_date_to_alone_keeps_a_since_cancelled_subscription(
        self, api_client, catalogue
    ):
        """A window open at the start has no cancellation cutoff: a term that
        was running inside it belongs on the list even though the cancellation
        has taken effect by today."""
        _confirmed_sub(
            MemberFactory(email="cancelled@x.de"),
            catalogue.var_veg,
            catalogue.dsd1,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
            cancelled_effective_at=datetime.date(2026, 3, 1),
        )

        resp = self._request(api_client, catalogue, date_to="2026-02-15")

        assert _emails(resp) == {"cancelled@x.de"}

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_date_from_moves_the_cancellation_cutoff_to_the_window_start(
        self, api_client, catalogue
    ):
        """With a start, the cutoff sits there: a subscription already gone by
        then is out, one cancelled later is in."""
        for email, effective_at in (
            ("gone@x.de", datetime.date(2026, 1, 20)),
            ("leaving@x.de", datetime.date(2026, 3, 1)),
        ):
            _confirmed_sub(
                MemberFactory(email=email),
                catalogue.var_veg,
                catalogue.dsd1,
                valid_from=datetime.date(2026, 1, 5),
                valid_until=datetime.date(2026, 6, 28),
                cancelled_effective_at=effective_at,
            )

        resp = self._request(api_client, catalogue, date_from="2026-02-01")

        assert _emails(resp) == {"leaving@x.de"}
