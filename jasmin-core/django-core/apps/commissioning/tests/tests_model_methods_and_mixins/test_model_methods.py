"""Tests for model methods across multiple models."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import time_machine
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    DeliveryStationDayFactory,
    HarvestFactory,
    MemberFactory,
    MovementShareArticleFactory,
    OfferFactory,
    PaymentCycleFactory,
    ShareArticleFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
)


# ---------------------------------------------------------------------------
# ContactEntity.name  (basics.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestContactEntityName:
    def test_company_name_takes_priority(self, tenant):
        ce = ContactEntityFactory(
            company_name="Farm Co", first_name="John", last_name="Doe"
        )
        assert ce.name == "Farm Co"

    def test_fallback_to_first_last(self, tenant):
        ce = ContactEntityFactory(company_name=None, first_name="John", last_name="Doe")
        assert ce.name == "John Doe"

    def test_first_only(self, tenant):
        ce = ContactEntityFactory(company_name=None, first_name="John", last_name=None)
        assert ce.name == "John"

    def test_returns_none_when_no_names(self, tenant):
        ce = ContactEntityFactory(company_name=None, first_name=None, last_name=None)
        assert ce.name is None


# ---------------------------------------------------------------------------
# ShareArticle.get_amount_per_pu_for_reseller  (basics.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareArticleGetAmountPerPu:
    def test_kg_unit(self, tenant):
        article = ShareArticleFactory(default_kg_per_pu_reseller=Decimal("10.000"))
        assert article.get_amount_per_pu_for_reseller("KG") == Decimal("10.000")

    def test_pcs_unit(self, tenant):
        article = ShareArticleFactory(default_pieces_per_pu_reseller=20)
        assert article.get_amount_per_pu_for_reseller("PCS") == 20

    def test_bunch_unit(self, tenant):
        article = ShareArticleFactory(default_bunches_per_pu_reseller=5)
        assert article.get_amount_per_pu_for_reseller("BUNCH") == 5

    def test_unknown_unit_returns_none(self, tenant):
        article = ShareArticleFactory()
        assert article.get_amount_per_pu_for_reseller("LITERS") is None

    def test_none_unit_returns_none(self, tenant):
        article = ShareArticleFactory()
        assert article.get_amount_per_pu_for_reseller(None) is None

    def test_case_insensitive(self, tenant):
        article = ShareArticleFactory(default_kg_per_pu_reseller=Decimal("5.000"))
        assert article.get_amount_per_pu_for_reseller("kg") == Decimal("5.000")


# ---------------------------------------------------------------------------
# Share.save  (auto-populate day defaults from delivery_day)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareSave:
    def test_auto_populates_day_defaults(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_packing_day=2,
            default_washing_day=1,
            default_cleaning_day=1,
            default_get_current_stock_day=0,
        )
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            delivery_day=sdd,
            share_type_variation=variation,
            harvesting_day=None,
            packing_day=None,
            washing_day=None,
            cleaning_day=None,
            get_current_stock_day=None,
        )

        assert share.harvesting_day == 1
        assert share.packing_day == 2
        assert share.washing_day == 1
        assert share.cleaning_day == 1
        assert share.get_current_stock_day == 0

    def test_does_not_overwrite_explicit_values(self, tenant):
        sdd = SharesDeliveryDayFactory(
            day_number=2,
            default_harvesting_day=1,
            default_packing_day=2,
        )
        variation = ShareTypeVariationFactory()
        share = ShareFactory(
            delivery_day=sdd,
            share_type_variation=variation,
            harvesting_day=4,
            packing_day=5,
        )

        assert share.harvesting_day == 4
        assert share.packing_day == 5


# ---------------------------------------------------------------------------
# ShareDelivery.clean  (delivery_day match)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareDeliveryClean:
    def test_matching_delivery_day_passes(self, tenant):
        from apps.commissioning.tests.factories import ShareDeliveryFactory

        sdd = SharesDeliveryDayFactory(day_number=2)
        dsd = DeliveryStationDayFactory(delivery_day=sdd)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(delivery_day=sdd, share_type_variation=variation)

        _delivery = ShareDeliveryFactory(share=share, delivery_station_day=dsd)
        # should not raise — saved successfully

    def test_mismatched_delivery_day_raises(self, tenant):
        sdd1 = SharesDeliveryDayFactory(day_number=2)
        sdd2 = SharesDeliveryDayFactory(day_number=4)
        dsd = DeliveryStationDayFactory(delivery_day=sdd2)
        variation = ShareTypeVariationFactory()
        share = ShareFactory(delivery_day=sdd1, share_type_variation=variation)

        from apps.commissioning.models import ShareDelivery

        delivery = ShareDelivery(share=share, delivery_station_day=dsd)
        with pytest.raises(ValidationError, match="must match"):
            delivery.full_clean()


# ---------------------------------------------------------------------------
# ShareType.clean  (circular packing reference detection)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeClean:
    def test_no_packing_ref_passes(self, tenant):
        st = ShareTypeFactory(gets_packed_with=None)
        st.clean()  # should not raise

    def test_self_reference_raises(self, tenant):
        st = ShareTypeFactory()
        st.gets_packed_with = st
        with pytest.raises(ValidationError, match="Cannot pack with itself"):
            st.clean()

    def test_circular_chain_raises(self, tenant):
        st_a = ShareTypeFactory()
        st_b = ShareTypeFactory(share_option="CHICKEN_SHARE", gets_packed_with=st_a)
        st_a.gets_packed_with = st_b
        with pytest.raises(ValidationError, match="Cannot pack with itself"):
            st_a.clean()


# ---------------------------------------------------------------------------
# ShareTypeVariation.clean  (date bound validation)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareTypeVariationClean:
    def test_valid_from_before_parent_raises(self, tenant):
        st = ShareTypeFactory(valid_from=datetime.date(2026, 3, 2))
        stv = ShareTypeVariationFactory.build(
            share_type=st,
            valid_from=datetime.date(2026, 1, 5),
        )
        with pytest.raises(ValidationError, match="start date"):
            stv.clean()

    def test_valid_until_after_parent_raises(self, tenant):
        st = ShareTypeFactory(
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        stv = ShareTypeVariationFactory.build(
            share_type=st,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
        )
        with pytest.raises(ValidationError, match="end date"):
            stv.clean()

    def test_valid_range_within_parent_passes(self, tenant):
        st = ShareTypeFactory(
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 12, 27),
        )
        stv = ShareTypeVariationFactory(
            share_type=st,
            valid_from=datetime.date(2026, 1, 5),
            valid_until=datetime.date(2026, 6, 28),
        )
        stv.clean()  # should not raise


# ---------------------------------------------------------------------------
# DeliveryStationDay.clean  (time range validation)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryStationDayClean:
    def test_valid_times_pass(self, tenant):
        dsd = DeliveryStationDayFactory(
            delivery_time_begin=datetime.time(8, 0),
            delivery_time_end=datetime.time(12, 0),
            pickup_time_begin=datetime.time(14, 0),
            pickup_time_end=datetime.time(18, 0),
        )
        dsd.clean()  # should not raise

    def test_delivery_end_before_begin_raises(self, tenant):
        dsd = DeliveryStationDayFactory.build(
            delivery_time_begin=datetime.time(12, 0),
            delivery_time_end=datetime.time(8, 0),
        )
        with pytest.raises(ValidationError, match="Delivery end time"):
            dsd.clean()

    def test_pickup_end_before_begin_raises(self, tenant):
        dsd = DeliveryStationDayFactory.build(
            pickup_time_begin=datetime.time(18, 0),
            pickup_time_end=datetime.time(14, 0),
        )
        with pytest.raises(ValidationError, match="Pickup end time"):
            dsd.clean()


# ---------------------------------------------------------------------------
# UserInvitation.save / is_expired  (members.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserInvitation:
    def test_auto_sets_expires_at(self, tenant):
        from apps.commissioning.models import UserInvitation

        member = MemberFactory()
        inv = UserInvitation(member=member, email="test@example.com")
        inv.save()

        assert inv.expires_at is not None
        delta = inv.expires_at - inv.created_at
        assert 6 <= delta.days <= 7

    def test_preserves_explicit_expires_at(self, tenant):
        from apps.commissioning.models import UserInvitation

        member = MemberFactory()
        custom_expiry = timezone.now() + datetime.timedelta(days=30)
        inv = UserInvitation(
            member=member, email="test@example.com", expires_at=custom_expiry
        )
        inv.save()

        assert inv.expires_at == custom_expiry

    def test_is_expired_true(self, tenant):
        from apps.commissioning.models import UserInvitation

        member = MemberFactory()
        inv = UserInvitation(
            member=member,
            email="test@example.com",
            expires_at=timezone.now() - datetime.timedelta(days=1),
            status="sent",
        )
        inv.save()
        assert inv.is_expired is True

    def test_is_expired_false_when_accepted(self, tenant):
        from apps.commissioning.models import UserInvitation

        member = MemberFactory()
        inv = UserInvitation(
            member=member,
            email="test@example.com",
            expires_at=timezone.now() - datetime.timedelta(days=1),
            status="accepted",
        )
        inv.save()
        assert inv.is_expired is False


# ---------------------------------------------------------------------------
# Subscription properties & methods  (members.py)
# ---------------------------------------------------------------------------
def _make_subscription(tenant, **overrides):
    """Helper to build a Subscription with all required relations."""
    member = MemberFactory()
    variation = ShareTypeVariationFactory()
    dsd = DeliveryStationDayFactory()
    cycle = PaymentCycleFactory()
    defaults = dict(
        member=member,
        share_type_variation=variation,
        payment_cycle=cycle,
        default_delivery_station_day=dsd,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),  # must be Sunday
    )
    defaults.update(overrides)
    return SubscriptionFactory(**defaults)


@pytest.mark.django_db
class TestSubscriptionProperties:
    @time_machine.travel("2026-06-15")
    def test_is_current_true(self, tenant):
        sub = _make_subscription(tenant)
        assert sub.is_current is True

    @time_machine.travel("2027-03-01")
    def test_is_current_false_when_past(self, tenant):
        sub = _make_subscription(tenant)
        assert sub.is_current is False

    @time_machine.travel("2025-06-01")
    def test_is_current_false_when_future(self, tenant):
        sub = _make_subscription(tenant)
        assert sub.is_current is False

    @time_machine.travel("2027-01-01")
    def test_is_expired_true(self, tenant):
        sub = _make_subscription(tenant)
        assert sub.is_expired is True

    def test_is_expired_false_for_open_ended(self, tenant):
        sub = _make_subscription(tenant, valid_until=None)
        assert sub.is_expired is False

    @time_machine.travel("2026-12-20T12:00:00+00:00")
    def test_days_until_expiry(self, tenant):
        sub = _make_subscription(tenant)
        assert sub.days_until_expiry == 7  # Dec 20 to Dec 27

    def test_days_until_expiry_none_for_open_ended(self, tenant):
        sub = _make_subscription(tenant, valid_until=None)
        assert sub.days_until_expiry is None


# ---------------------------------------------------------------------------
# MemberLoan.clean  (members.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberLoanClean:
    def test_end_before_start_raises(self, tenant):
        from apps.commissioning.models.members import MemberLoan

        member = MemberFactory()
        loan = MemberLoan(
            member=member,
            amount=1000,
            interest_rate=Decimal("2.50"),
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 1, 1),
        )
        with pytest.raises(ValidationError, match="End date"):
            loan.full_clean()

    def test_paid_back_before_start_raises(self, tenant):
        from apps.commissioning.models.members import MemberLoan

        member = MemberFactory()
        loan = MemberLoan(
            member=member,
            amount=1000,
            interest_rate=Decimal("2.50"),
            start_date=datetime.date(2026, 6, 1),
            paid_back_date=datetime.date(2026, 1, 1),
        )
        with pytest.raises(ValidationError, match="Paid back"):
            loan.full_clean()

    def test_valid_dates_pass(self, tenant):
        from apps.commissioning.models.members import MemberLoan

        member = MemberFactory()
        loan = MemberLoan(
            member=member,
            amount=1000,
            interest_rate=Decimal("2.50"),
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2027, 1, 1),
            paid_back_date=datetime.date(2027, 1, 1),
        )
        loan.full_clean()  # should not raise


# ---------------------------------------------------------------------------
# MovementShareArticle.clean / save  (movements.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMovementShareArticleCleanSave:
    def test_inventory_no_source_passes(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory()
        m = MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            movement_type="INVENTORY",
        )
        assert m.pk is not None
        assert m.movement_type == "INVENTORY"

    def test_inventory_with_source_raises(self, tenant):
        from apps.commissioning.models import MovementShareArticle

        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        harvest = HarvestFactory(storage=storage)

        m = MovementShareArticle(
            share_article=article,
            storage=storage,
            movement_type="INVENTORY",
            harvest=harvest,
            amount=Decimal("10.000"),
        )
        with pytest.raises(ValidationError, match="INVENTORY movements must not"):
            m.full_clean()

    def test_non_inventory_no_source_raises(self, tenant):
        from apps.commissioning.models import MovementShareArticle

        article = ShareArticleFactory()
        m = MovementShareArticle(
            share_article=article,
            movement_type="HARVEST",
            amount=Decimal("10.000"),
        )
        with pytest.raises(ValidationError, match="exactly one source"):
            m.full_clean()

    def test_auto_sets_movement_type_from_source(self, tenant):
        article = ShareArticleFactory()
        storage = StorageFactory(is_short_term_harvest_storage=True)
        harvest = HarvestFactory(storage=storage)

        m = MovementShareArticleFactory(
            share_article=article,
            storage=storage,
            harvest=harvest,
            movement_type=None,  # should be auto-set
        )
        assert m.movement_type == "HARVEST"


# ---------------------------------------------------------------------------
# Offer check_availability / update_available_amount  (resellers.py)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOfferAvailability:
    def test_check_availability_true(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))
        assert offer.check_availability(50) is True

    def test_check_availability_false(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("10.000"))
        assert offer.check_availability(20) is False

    def test_check_availability_none_amount(self, tenant):
        article = ShareArticleFactory()
        # ``amount`` is NOT NULL at the DB level; build an unsaved instance
        # to exercise the defensive ``None`` branch in ``check_availability``.
        offer = OfferFactory.build(share_article=article, amount=None)
        assert offer.check_availability(1) is False

    def test_update_decrements(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("100.000"))
        offer.update_available_amount(30)
        offer.refresh_from_db()
        assert offer.amount == Decimal("70.000")

    def test_update_over_order_raises(self, tenant):
        article = ShareArticleFactory()
        offer = OfferFactory(share_article=article, amount=Decimal("10.000"))
        with pytest.raises(ValidationError, match="Not enough stock"):
            offer.update_available_amount(20)

    def test_update_none_amount_raises(self, tenant):
        article = ShareArticleFactory()
        # See ``test_check_availability_none_amount``: build unsaved.
        offer = OfferFactory.build(share_article=article, amount=None)
        with pytest.raises(ValidationError, match="No available amount"):
            offer.update_available_amount(1)


# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCoopShareClean:
    """The cancel/payback equity-return date-order guards on CoopShare.clean().

    The date checks run BEFORE the GenG min/max equity check, so a 1-share /
    value-100 instance (within the default window) isolates the ordering rules.
    """

    def _coop_share(self, **kwargs):
        from apps.commissioning.models.members import CoopShare

        defaults = {
            "member": MemberFactory(),
            "amount_of_coop_shares": 1,
            "value_one_coop_share": 100,
        }
        defaults.update(kwargs)
        return CoopShare(**defaults)

    def test_paid_back_before_payback_due_raises(self, tenant):
        share = self._coop_share(
            payback_due_date=datetime.date(2026, 6, 1),
            paid_back_date=datetime.date(2026, 1, 1),
        )
        with pytest.raises(ValidationError, match="Paid-back date"):
            share.full_clean()

    def test_payback_due_before_cancel_effective_raises(self, tenant):
        share = self._coop_share(
            cancelled_effective_at=datetime.date(2026, 6, 1),
            payback_due_date=datetime.date(2026, 1, 1),
        )
        with pytest.raises(ValidationError, match="Payback due date"):
            share.full_clean()

    def test_valid_dates_pass(self, tenant):
        share = self._coop_share(
            cancelled_effective_at=datetime.date(2026, 1, 1),
            payback_due_date=datetime.date(2026, 2, 1),
            paid_back_date=datetime.date(2026, 3, 1),
        )
        share.full_clean()  # should not raise

    def test_null_tolerant_when_one_side_missing(self, tenant):
        # Only one member of each pair is set, so no order check fires.
        share = self._coop_share(payback_due_date=datetime.date(2026, 6, 1))
        share.full_clean()  # should not raise
