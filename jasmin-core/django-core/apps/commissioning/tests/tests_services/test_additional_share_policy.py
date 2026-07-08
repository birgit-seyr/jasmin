"""Tests for the additional-share ("Zusatz") base-coverage guard."""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.errors import (
    AdditionalShareExceedsBase,
    AdditionalShareRequiresBase,
)
from apps.commissioning.models import Subscription
from apps.commissioning.services.additional_share_policy import (
    assert_additional_share_has_base,
)
from apps.commissioning.services.subscription_service import SubscriptionService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

# Base subscription term (factory defaults: Monday valid_from, Sunday valid_until).
_BASE_FROM = datetime.date(2026, 1, 5)
_BASE_UNTIL = datetime.date(2027, 1, 3)


def _base_variation(size="M"):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(
            share_option="HARVEST_SHARE", is_additional_share_type=False
        ),
        size=size,
    )


def _addon_variation(size="M"):
    return ShareTypeVariationFactory(
        share_type=ShareTypeFactory(
            share_option="HONEY_SHARE", is_additional_share_type=True
        ),
        size=size,
    )


def _base_subscription(member):
    return SubscriptionFactory(
        member=member,
        share_type_variation=_base_variation(),
        valid_from=_BASE_FROM,
        valid_until=_BASE_UNTIL,
    )


@pytest.mark.django_db
class TestAdditionalShareGuard:
    def test_base_share_is_always_allowed(self, tenant):
        member = MemberFactory()
        base_var = _base_variation()
        # A non-additional variation never needs a base — no raise even with no
        # existing subscriptions.
        assert_additional_share_has_base(
            member_id=member.id,
            share_type_variation_id=base_var.id,
            valid_from=_BASE_FROM,
            valid_until=_BASE_UNTIL,
        )

    def test_additional_without_base_raises(self, tenant):
        member = MemberFactory()
        addon_var = _addon_variation()
        with pytest.raises(AdditionalShareRequiresBase):
            assert_additional_share_has_base(
                member_id=member.id,
                share_type_variation_id=addon_var.id,
                valid_from=datetime.date(2026, 2, 2),
                valid_until=datetime.date(2026, 6, 28),
            )

    def test_additional_within_base_is_allowed(self, tenant):
        member = MemberFactory()
        _base_subscription(member)
        addon_var = _addon_variation()
        # Fully inside the base term → allowed.
        assert_additional_share_has_base(
            member_id=member.id,
            share_type_variation_id=addon_var.id,
            valid_from=datetime.date(2026, 2, 2),
            valid_until=datetime.date(2026, 12, 27),
        )

    def test_additional_exceeding_base_raises_with_suggestion(self, tenant):
        member = MemberFactory()
        _base_subscription(member)
        addon_var = _addon_variation()
        with pytest.raises(AdditionalShareExceedsBase) as exc:
            assert_additional_share_has_base(
                member_id=member.id,
                share_type_variation_id=addon_var.id,
                valid_from=datetime.date(2026, 2, 2),
                valid_until=datetime.date(2027, 6, 27),  # past the base's end
            )
        assert exc.value.details["suggested_valid_until"] == str(_BASE_UNTIL)

    def test_base_starting_after_addon_does_not_cover_start(self, tenant):
        member = MemberFactory()
        _base_subscription(member)  # base starts 2026-01-05
        addon_var = _addon_variation()
        # Add-on starts BEFORE the base → no base active at its start.
        with pytest.raises(AdditionalShareRequiresBase):
            assert_additional_share_has_base(
                member_id=member.id,
                share_type_variation_id=addon_var.id,
                valid_from=datetime.date(2025, 12, 1),
                valid_until=datetime.date(2026, 6, 28),
            )

    def test_cancelled_base_effective_end_is_used(self, tenant):
        member = MemberFactory()
        base = _base_subscription(member)
        # Cancellation leaves valid_until intact but caps the effective end.
        cancelled_end = datetime.date(2026, 6, 28)
        Subscription.objects.filter(pk=base.pk).update(
            cancelled_effective_at=cancelled_end
        )
        addon_var = _addon_variation()
        with pytest.raises(AdditionalShareExceedsBase) as exc:
            assert_additional_share_has_base(
                member_id=member.id,
                share_type_variation_id=addon_var.id,
                valid_from=datetime.date(2026, 2, 2),
                valid_until=datetime.date(2026, 12, 27),
            )
        assert exc.value.details["suggested_valid_until"] == str(cancelled_end)

    def test_create_bare_subscription_enforces_the_guard(self, tenant):
        member = MemberFactory()
        addon_var = _addon_variation()
        # No base for this member → the create path refuses the add-on before
        # any row / capacity work happens.
        with pytest.raises(AdditionalShareRequiresBase):
            SubscriptionService().create_bare_subscription(
                {
                    "member": member.id,
                    "share_type_variation": addon_var.id,
                    "valid_from": datetime.date(2026, 2, 2),
                    "valid_until": datetime.date(2026, 6, 28),
                    "default_delivery_station_day": DeliveryStationDayFactory(),
                    "quantity": 1,
                }
            )
        assert not Subscription.objects.filter(member=member).exists()
