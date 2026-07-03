"""Tests for ResellerAndDeliveryStationService."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.commissioning.errors import RequiredFieldMissing
from apps.commissioning.models import ContactEntity, DeliveryStation, Reseller
from apps.commissioning.services.reseller_and_delivery_station_service import (
    ResellerAndDeliveryStationService,
)
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    DeliveryStationFactory,
    ResellerFactory,
)


@pytest.fixture()
def svc():
    return ResellerAndDeliveryStationService()


def _contact_data(**overrides):
    """Build valid contact data for create/update methods."""
    defaults = {
        "company_name": "Test GmbH",
        "address": "Street 1",
        "zip_code": "12345",
        "city": "Berlin",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# create_reseller
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateReseller:
    def test_creates_reseller_with_contact(self, tenant, svc):
        data = {
            "is_reseller": True,
            "is_seller": False,
            "is_also_delivery_station": False,
            **_contact_data(),
        }
        reseller = svc.create_reseller(data)

        assert reseller.pk is not None
        assert reseller.contact is not None
        assert reseller.contact.city == "Berlin"

    def test_also_creates_delivery_station(self, tenant, svc):
        data = {
            "is_reseller": True,
            "is_seller": False,
            "is_also_delivery_station": True,
            **_contact_data(),
        }
        reseller = svc.create_reseller(data)

        assert DeliveryStation.objects.filter(contact=reseller.contact).exists()
        ds = DeliveryStation.objects.get(contact=reseller.contact)
        assert ds.linked_reseller == reseller

    def test_raises_on_missing_contact_fields(self, tenant, svc):
        data = {
            "is_reseller": True,
            "is_seller": False,
            "is_also_delivery_station": False,
            "company_name": "Test",
            # Missing address, zip_code, city
        }
        with pytest.raises(RequiredFieldMissing, match="Missing required contact"):
            svc.create_reseller(data)


# ---------------------------------------------------------------------------
# create_delivery_station
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateDeliveryStation:
    def test_creates_station_with_contact(self, tenant, svc):
        data = {
            "is_also_reseller": False,
            "is_also_seller": False,
            "is_active": True,
            **_contact_data(),
        }
        station = svc.create_delivery_station(data)

        assert station.pk is not None
        assert station.contact is not None

    def test_also_creates_reseller(self, tenant, svc):
        data = {
            "is_also_reseller": True,
            "is_also_seller": False,
            "is_active": True,
            **_contact_data(),
        }
        station = svc.create_delivery_station(data)

        assert Reseller.objects.filter(contact=station.contact).exists()
        assert station.linked_reseller is not None
        assert station.linked_reseller.is_reseller


# ---------------------------------------------------------------------------
# update_reseller
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateReseller:
    def test_updates_reseller_fields(self, tenant, svc):
        contact = ContactEntityFactory(address="Old St", zip_code="11111", city="Old")
        reseller = ResellerFactory(contact=contact, is_reseller=True)

        updated = svc.update_reseller(
            reseller,
            {"is_seller": True, "is_also_delivery_station": False},
        )
        assert updated.is_seller

    def test_creates_ds_when_is_also_delivery_station(self, tenant, svc):
        contact = ContactEntityFactory(address="Street", zip_code="22222", city="City")
        reseller = ResellerFactory(contact=contact, is_reseller=True)

        svc.update_reseller(
            reseller,
            {"is_also_delivery_station": True},
        )
        assert DeliveryStation.objects.filter(contact=contact).exists()


# ---------------------------------------------------------------------------
# update_delivery_station
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateDeliveryStation:
    def test_updates_station_fields(self, tenant, svc):
        contact = ContactEntityFactory(address="St", zip_code="33333", city="City")
        station = DeliveryStationFactory(contact=contact)

        updated = svc.update_delivery_station(
            station,
            {"is_also_reseller": False, "is_also_seller": False},
        )
        assert updated.pk is not None

    def test_creates_reseller_when_flags_set(self, tenant, svc):
        contact = ContactEntityFactory(address="St", zip_code="44444", city="City")
        station = DeliveryStationFactory(contact=contact)

        svc.update_delivery_station(
            station,
            {"is_also_reseller": True, "is_also_seller": False},
        )
        assert Reseller.objects.filter(contact=contact).exists()


# ---------------------------------------------------------------------------
# delete_reseller
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteReseller:
    def test_delete_seller_keeps_reseller(self, tenant, svc):
        reseller = ResellerFactory(is_reseller=True, is_seller=True)
        svc.delete_reseller(reseller, delete_context="sellers")

        reseller.refresh_from_db()
        assert reseller.is_reseller
        assert not reseller.is_seller

    def test_delete_reseller_keeps_seller(self, tenant, svc):
        reseller = ResellerFactory(is_reseller=True, is_seller=True)
        svc.delete_reseller(reseller, delete_context="resellers")

        reseller.refresh_from_db()
        assert not reseller.is_reseller
        assert reseller.is_seller

    def test_fully_deletes_when_only_role(self, tenant, svc):
        reseller = ResellerFactory(is_reseller=False, is_seller=True)
        pk = reseller.pk
        svc.delete_reseller(reseller, delete_context="sellers")
        assert not Reseller.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# delete_delivery_station
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteDeliveryStation:
    def test_deletes_and_unlinks_reseller(self, tenant, svc):
        contact = ContactEntityFactory(address="St", zip_code="55555", city="City")
        reseller = ResellerFactory(contact=contact)
        station = DeliveryStationFactory(contact=contact, linked_reseller=reseller)

        svc.delete_delivery_station(station)

        reseller.refresh_from_db()
        # ``linked_delivery_station`` is the reverse OneToOne; if the station
        # is gone the reverse accessor raises, so use ``hasattr`` to check.
        assert not hasattr(reseller, "linked_delivery_station")

    def test_deletes_orphaned_contact(self, tenant, svc):
        contact = ContactEntityFactory(address="St", zip_code="66666", city="City")
        station = DeliveryStationFactory(contact=contact)
        contact_pk = contact.pk

        svc.delete_delivery_station(station)

        assert not ContactEntity.objects.filter(pk=contact_pk).exists()

    def test_delete_refused_when_station_has_deliveries(self, tenant, svc):
        # DB-1: a station whose pickup days carry ShareDeliveries must NOT be
        # deletable — the CASCADE would silently wipe the billing basis.
        from apps.commissioning.errors import DeliveryStationInUse
        from apps.commissioning.tests.factories import (
            DeliveryStationDayFactory,
            ShareDeliveryFactory,
            ShareFactory,
            SharesDeliveryDayFactory,
        )

        station = DeliveryStationFactory()
        delivery_day = SharesDeliveryDayFactory(day_number=2)
        dsd = DeliveryStationDayFactory(
            delivery_station=station, delivery_day=delivery_day
        )
        ShareDeliveryFactory(
            share=ShareFactory(delivery_day=delivery_day),
            delivery_station_day=dsd,
        )

        with pytest.raises(DeliveryStationInUse):
            svc.delete_delivery_station(station)
        assert DeliveryStation.objects.filter(pk=station.pk).exists()


# ---------------------------------------------------------------------------
# Contact uniqueness (TXN-2)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestContactUniqueness:
    """Reseller / DeliveryStation are 1:1 with a ContactEntity, so the
    ``get_or_create(contact=…)`` / ``.get(contact=…)`` callers can rely on at
    most one row per contact. The partial unique constraint enforces it on
    non-null contacts — and a concurrent ``get_or_create`` race now becomes a
    catchable IntegrityError (re-fetched) instead of two rows that later blow up
    ``.get(contact=…)`` with MultipleObjectsReturned."""

    def test_duplicate_reseller_contact_rejected(self, tenant):
        contact = ContactEntityFactory()
        ResellerFactory(contact=contact)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ResellerFactory(contact=contact)

    def test_duplicate_delivery_station_contact_rejected(self, tenant):
        contact = ContactEntityFactory()
        DeliveryStationFactory(contact=contact)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DeliveryStationFactory(contact=contact)

    def test_get_or_create_contact_is_idempotent(self, tenant):
        contact = ContactEntityFactory()
        first, created_first = Reseller.objects.get_or_create(contact=contact)
        second, created_second = Reseller.objects.get_or_create(contact=contact)
        assert created_first is True
        assert created_second is False
        assert first.pk == second.pk

    def test_multiple_null_contacts_allowed(self, tenant):
        # The constraint is partial (``contact IS NOT NULL``) so contactless
        # rows stay unconstrained.
        ResellerFactory(contact=None)
        ResellerFactory(contact=None)
        DeliveryStationFactory(contact=None)
        DeliveryStationFactory(contact=None)
        assert Reseller.objects.filter(contact__isnull=True).count() >= 2
        assert DeliveryStation.objects.filter(contact__isnull=True).count() >= 2
