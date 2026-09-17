"""The contact IBAN is checked for well-formedness before it is stored.

``ContactEntity.iban`` is the bank account a reseller / delivery station is
paid on. It carries the same mod-97 + country-length validator as every other
IBAN column, and because the flattened contact fields are hand-built (they do
not inherit model validators) and the write path never calls ``full_clean()``,
the serializer re-attaches it. Both layers are pinned here.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.commissioning.serializers import (
    DeliveryStationSerializer,
    ResellerSerializer,
)
from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    DeliveryStationFactory,
    ResellerFactory,
)

VALID_IBAN = "DE89370400440532013000"
VALID_IBAN_WITH_SPACES = "DE89 3704 0044 0532 0130 00"
# Correct country + length, wrong check digits.
INVALID_IBAN = "DE00370400440532013000"


@pytest.mark.django_db
class TestResellerSerializerIban:
    def test_invalid_iban_is_rejected(self, tenant):
        reseller = ResellerFactory()

        serializer = ResellerSerializer(
            instance=reseller, data={"iban": INVALID_IBAN}, partial=True
        )

        assert serializer.is_valid() is False
        assert "iban" in serializer.errors
        assert serializer.errors["iban"][0].code == "iban_invalid"

    def test_valid_iban_is_accepted(self, tenant):
        reseller = ResellerFactory()

        serializer = ResellerSerializer(
            instance=reseller, data={"iban": VALID_IBAN}, partial=True
        )

        assert serializer.is_valid() is True, serializer.errors

    def test_valid_iban_with_spaces_is_accepted(self, tenant):
        """The office pastes IBANs straight off a bank statement."""
        reseller = ResellerFactory()

        serializer = ResellerSerializer(
            instance=reseller, data={"iban": VALID_IBAN_WITH_SPACES}, partial=True
        )

        assert serializer.is_valid() is True, serializer.errors

    @pytest.mark.parametrize("empty_value", ["", None])
    def test_absent_iban_stays_allowed(self, tenant, empty_value):
        """The column is optional — a reseller without bank details must keep
        saving."""
        reseller = ResellerFactory()

        serializer = ResellerSerializer(
            instance=reseller, data={"iban": empty_value}, partial=True
        )

        assert serializer.is_valid() is True, serializer.errors


@pytest.mark.django_db
class TestDeliveryStationSerializerIban:
    def test_invalid_iban_is_rejected(self, tenant):
        station = DeliveryStationFactory()

        serializer = DeliveryStationSerializer(
            instance=station, data={"iban": INVALID_IBAN}, partial=True
        )

        assert serializer.is_valid() is False
        assert "iban" in serializer.errors

    def test_valid_iban_is_accepted(self, tenant):
        station = DeliveryStationFactory()

        serializer = DeliveryStationSerializer(
            instance=station, data={"iban": VALID_IBAN}, partial=True
        )

        assert serializer.is_valid() is True, serializer.errors


@pytest.mark.django_db
class TestContactEntityIbanValidator:
    def _contact(self, **overrides):
        return ContactEntityFactory(
            address="Marktstrasse 1",
            zip_code="80331",
            city="Munich",
            **overrides,
        )

    def test_full_clean_rejects_an_invalid_iban(self, tenant):
        contact = self._contact(iban=INVALID_IBAN)

        with pytest.raises(ValidationError) as exc_info:
            contact.full_clean()

        assert "iban" in exc_info.value.error_dict

    def test_full_clean_accepts_a_valid_iban(self, tenant):
        contact = self._contact(iban=VALID_IBAN)

        contact.full_clean()

    def test_full_clean_accepts_a_contact_without_an_iban(self, tenant):
        contact = self._contact(iban=None)

        contact.full_clean()
