"""Tests for ``OptinService`` (per-delivery opt-in on on-off
ShareTypeVariations).

Covers:
  * deadline math: ``optin_deadline`` derives correctly from the
    delivery date minus the variation's configured days
  * ``is_locked`` returns True only after the deadline
  * ``toggle`` happy path: state flips, audit stamps land
  * ``toggle`` after deadline raises ``OptinDeadlinePassed``
  * ``toggle`` on a non-on-off variation raises ``OptinNotApplicable``
  * ``list_pending_for_member`` filters correctly (on-off only,
    deadline not passed, not cancelled)
  * Default-state stamping in ``ShareDelivery.save()`` — off-by-
    default vs on-by-default variations
"""

from __future__ import annotations

import datetime

import pytest
import time_machine
from django.utils import timezone

from apps.commissioning.errors import (
    OptinDeadlinePassed,
    OptinNotApplicable,
)
from apps.commissioning.services.optin_service import OptinService
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    JasminUserFactory,
    MemberFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

_TODAY = datetime.date(2026, 4, 6)  # Monday, ISO W15 2026
# Delivery dates land on the Share's ``delivery_day`` (day_number).
# Default SharesDeliveryDayFactory uses ``day_number=2`` (Wednesday).
# So the delivery date for ``year=2026, delivery_week=15`` is
# 2026-04-08 (Wednesday of ISO W15).
_DELIVERY_DATE = datetime.date(2026, 4, 8)


def _on_off_variation(*, default_state: bool = False, deadline_days: int = 3):
    """Variation with on-off semantics enabled."""
    return ShareTypeVariationFactory(
        requires_optin=True,
        default_optin_state=default_state,
        optin_deadline_days_before_delivery=deadline_days,
    )


def _get_or_make_delivery_day():
    """Return the canonical Wednesday SDD, reused across calls.

    ``SharesDeliveryDay`` carries a TimeBoundMixin overlap check on
    ``day_number``, so creating two with ``day_number=2`` in the same
    test trips the check. Tests that call ``_make_share_delivery``
    more than once share a single row via this helper.
    """
    from apps.commissioning.models import SharesDeliveryDay

    existing = SharesDeliveryDay.objects.filter(day_number=2).first()
    if existing is not None:
        return existing
    return SharesDeliveryDayFactory(day_number=2)


def _get_or_make_station_day(delivery_day):
    from apps.commissioning.models import DeliveryStationDay

    existing = DeliveryStationDay.objects.filter(delivery_day=delivery_day).first()
    if existing is not None:
        return existing
    return DeliveryStationDayFactory(delivery_day=delivery_day)


def _make_share_delivery(*, variation, member=None):
    """Build a ShareDelivery wired to a member (via a Subscription).

    ``OptinService.toggle`` invalidates the charge schedule via
    ``regenerate_for_subscription``, which needs a Subscription
    attached to a Member. We build the whole chain here.

    Each factory has its own SubFactory chain for ``SharesDeliveryDay``
    (via ``ShareFactory.delivery_day`` and again via
    ``DeliveryStationDayFactory.delivery_day``). Two unrelated SDD
    rows with ``day_number=2`` collide on TimeBoundMixin's overlap
    check, so we look up an existing canonical SDD + DSD or create
    one — see ``_get_or_make_delivery_day``. Mirrors the pattern in
    ``test_share_delivery_service.TestGetVariationDeliveryCounts``.
    """
    member = member or MemberFactory()
    delivery_day = _get_or_make_delivery_day()
    station_day = _get_or_make_station_day(delivery_day)
    share = ShareFactory(share_type_variation=variation, delivery_day=delivery_day)
    sub = SubscriptionFactory(
        member=member,
        share_type_variation=variation,
        default_delivery_station_day=station_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
    )
    return ShareDeliveryFactory(
        share=share, subscription=sub, delivery_station_day=station_day
    )


@pytest.mark.django_db
class TestOptinDeadline:
    def test_deadline_is_delivery_minus_configured_days(self, tenant):
        variation = _on_off_variation(deadline_days=3)
        sd = _make_share_delivery(variation=variation)
        deadline = OptinService.optin_deadline(sd)
        # delivery = 2026-04-08 (Wed of W15), -3 days = 2026-04-05.
        assert deadline == _DELIVERY_DATE - datetime.timedelta(days=3)

    def test_deadline_is_none_for_non_onoff_variation(self, tenant):
        # Default variation: no requires_optin.
        plain = ShareTypeVariationFactory()
        sd = _make_share_delivery(variation=plain)
        assert OptinService.optin_deadline(sd) is None

    def test_is_locked_before_deadline_returns_false(self, tenant):
        variation = _on_off_variation(deadline_days=3)
        sd = _make_share_delivery(variation=variation)
        # deadline = Apr 5; today = Apr 4 → not yet locked
        assert OptinService.is_locked(sd, today=datetime.date(2026, 4, 4)) is False

    def test_is_locked_on_deadline_day_returns_false(self, tenant):
        variation = _on_off_variation(deadline_days=3)
        sd = _make_share_delivery(variation=variation)
        # deadline = Apr 5; today = Apr 5 → still toggleable
        assert OptinService.is_locked(sd, today=datetime.date(2026, 4, 5)) is False

    def test_is_locked_after_deadline_returns_true(self, tenant):
        variation = _on_off_variation(deadline_days=3)
        sd = _make_share_delivery(variation=variation)
        # deadline = Apr 5; today = Apr 6 → locked
        assert OptinService.is_locked(sd, today=datetime.date(2026, 4, 6)) is True

    def test_non_onoff_variation_is_always_locked(self, tenant):
        plain = ShareTypeVariationFactory()
        sd = _make_share_delivery(variation=plain)
        # Locked sentinel for "toggle is not applicable here".
        assert OptinService.is_locked(sd, today=datetime.date(1900, 1, 1)) is True


@pytest.mark.django_db
class TestOptinToggle:
    @time_machine.travel(datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC))
    def test_toggle_happy_path_flips_state_and_stamps_audit(self, tenant):
        variation = _on_off_variation(default_state=False)
        sd = _make_share_delivery(variation=variation)
        assert sd.is_opted_in is False  # default-OFF variation
        actor = JasminUserFactory(roles=["office"])

        OptinService.toggle(sd, opt_in=True, actor=actor)

        sd.refresh_from_db()
        assert sd.is_opted_in is True
        assert sd.optin_decided_at is not None
        assert sd.optin_decided_by == actor

    @time_machine.travel(datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC))
    def test_toggle_can_flip_back_off(self, tenant):
        """Default-ON variation that the member opts OUT of."""
        variation = _on_off_variation(default_state=True)
        sd = _make_share_delivery(variation=variation)
        assert sd.is_opted_in is True  # default-ON variation
        actor = JasminUserFactory(roles=["office"])

        OptinService.toggle(sd, opt_in=False, actor=actor)

        sd.refresh_from_db()
        assert sd.is_opted_in is False
        assert sd.optin_decided_by == actor

    def test_toggle_after_deadline_raises(self, tenant):
        variation = _on_off_variation(deadline_days=3)
        sd = _make_share_delivery(variation=variation)
        actor = JasminUserFactory(roles=["office"])

        with time_machine.travel(
            datetime.datetime(2026, 4, 6, 10, 0, tzinfo=datetime.UTC)
        ):
            with pytest.raises(OptinDeadlinePassed) as exc:
                OptinService.toggle(sd, opt_in=True, actor=actor)
        assert exc.value.code == "optin.deadline_passed"

    def test_toggle_on_non_onoff_variation_raises(self, tenant):
        plain = ShareTypeVariationFactory()  # requires_optin defaults to False
        sd = _make_share_delivery(variation=plain)
        actor = JasminUserFactory(roles=["office"])

        with pytest.raises(OptinNotApplicable) as exc:
            OptinService.toggle(sd, opt_in=True, actor=actor)
        assert exc.value.code == "optin.not_applicable"


@pytest.mark.django_db
class TestDefaultStateStamping:
    """``ShareDelivery.save()`` stamps ``is_opted_in`` from the
    variation's ``default_optin_state`` on insert."""

    def test_off_by_default_variation_starts_off(self, tenant):
        variation = _on_off_variation(default_state=False)
        sd = _make_share_delivery(variation=variation)
        assert sd.is_opted_in is False

    def test_on_by_default_variation_starts_on(self, tenant):
        variation = _on_off_variation(default_state=True)
        sd = _make_share_delivery(variation=variation)
        assert sd.is_opted_in is True

    def test_non_onoff_variation_keeps_field_default(self, tenant):
        """Non-on-off variations don't touch ``is_opted_in`` — it
        stays at the model's column default (False)."""
        plain = ShareTypeVariationFactory()
        sd = _make_share_delivery(variation=plain)
        assert sd.is_opted_in is False


@pytest.mark.django_db
class TestListPendingForMember:
    def test_returns_only_on_off_deliveries(self, tenant):
        member = MemberFactory()
        on_off = _on_off_variation()
        plain = ShareTypeVariationFactory()
        _make_share_delivery(variation=on_off, member=member)
        _make_share_delivery(variation=plain, member=member)

        with time_machine.travel(
            datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC)
        ):
            result = OptinService.list_pending_for_member(member)
        assert len(result) == 1
        assert result[0].share.share_type_variation == on_off

    def test_excludes_past_deadline_deliveries(self, tenant):
        member = MemberFactory()
        variation = _on_off_variation(deadline_days=3)
        _make_share_delivery(variation=variation, member=member)

        with time_machine.travel(
            datetime.datetime(2026, 4, 7, 10, 0, tzinfo=datetime.UTC)
        ):
            # deadline = Apr 5, today = Apr 7 → past deadline
            result = OptinService.list_pending_for_member(member)
        assert result == []

    def test_other_members_deliveries_not_included(self, tenant):
        owner = MemberFactory()
        other = MemberFactory()
        variation = _on_off_variation()
        _make_share_delivery(variation=variation, member=owner)

        with time_machine.travel(
            datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC)
        ):
            result = OptinService.list_pending_for_member(other)
        assert result == []

    def test_excludes_cancelled_subscriptions(self, tenant):
        member = MemberFactory()
        variation = _on_off_variation()
        sd = _make_share_delivery(variation=variation, member=member)
        sd.subscription.cancelled_at = timezone.now()
        sd.subscription.save()

        with time_machine.travel(
            datetime.datetime(2026, 4, 4, 10, 0, tzinfo=datetime.UTC)
        ):
            result = OptinService.list_pending_for_member(member)
        assert result == []


@pytest.mark.django_db
class TestShippableQuerySet:
    """``ShareDelivery.objects.shippable()`` — the single ship predicate as a
    named queryset (joker not taken AND no-opt-in-required-OR-opted-in). Guards
    the DRY-1 / API-1 fix: a new aggregation reads ``.shippable()`` instead of
    re-spelling the rule or forgetting it."""

    def test_normal_delivery_is_shippable(self, tenant):
        from apps.commissioning.models import ShareDelivery

        sd = _make_share_delivery(variation=ShareTypeVariationFactory())
        assert ShareDelivery.objects.shippable().filter(pk=sd.pk).exists()

    def test_jokered_delivery_is_excluded(self, tenant):
        from apps.commissioning.models import ShareDelivery

        sd = _make_share_delivery(variation=ShareTypeVariationFactory())
        # .update() bypasses save() — the predicate must hold at the DB layer.
        ShareDelivery.objects.filter(pk=sd.pk).update(joker_taken=True)
        assert not ShareDelivery.objects.shippable().filter(pk=sd.pk).exists()

    def test_opted_out_onoff_is_excluded(self, tenant):
        from apps.commissioning.models import ShareDelivery

        # default-OFF on-off → save seeds is_opted_in=False → opted out.
        sd = _make_share_delivery(variation=_on_off_variation(default_state=False))
        assert sd.is_opted_in is False
        assert not ShareDelivery.objects.shippable().filter(pk=sd.pk).exists()

    def test_opted_in_onoff_is_shippable(self, tenant):
        from apps.commissioning.models import ShareDelivery

        # default-ON on-off → save seeds is_opted_in=True → ships.
        sd = _make_share_delivery(variation=_on_off_variation(default_state=True))
        assert sd.is_opted_in is True
        assert ShareDelivery.objects.shippable().filter(pk=sd.pk).exists()
