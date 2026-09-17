"""``ForecastSerializer`` — the columns ``ForecastService`` does not write.

Forecast create/update run through ``ForecastService``, which copies a fixed set
of keys out of ``validated_data``. ``storage`` and ``day_number`` are not in
that set, so a writable declaration would advertise a write that never lands.
Both stay serialized on output.
"""

from __future__ import annotations

import pytest

from apps.commissioning.serializers import ForecastSerializer
from apps.commissioning.tests.factories import ForecastFactory, StorageFactory

SERVICE_OWNED_FIELDS = ("storage", "day_number")


@pytest.mark.django_db
class TestForecastServiceOwnedFields:
    @pytest.mark.parametrize("field", SERVICE_OWNED_FIELDS)
    def test_field_is_read_only(self, field):
        assert field in ForecastSerializer.Meta.read_only_fields
        assert ForecastSerializer().fields[field].read_only is True

    def test_patch_cannot_repoint_the_storage_of_a_forecast_that_has_one(self, tenant):
        forecast = ForecastFactory(note="before")
        original_storage_id = forecast.storage_id
        assert original_storage_id is not None
        other_storage = StorageFactory(is_short_term_harvest_storage=True)

        serializer = ForecastSerializer(
            instance=forecast,
            data={"storage": other_storage.id, "note": "after"},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors
        assert "storage" not in serializer.validated_data
        serializer.save()

        forecast.refresh_from_db()
        assert forecast.storage_id == original_storage_id
        # The legitimate half of the same payload still lands.
        assert forecast.note == "after"

    def test_patch_cannot_attach_a_storage_to_a_forecast_without_one(self, tenant):
        forecast = ForecastFactory(storage=None)
        storage = StorageFactory(is_short_term_harvest_storage=True)

        serializer = ForecastSerializer(
            instance=forecast, data={"storage": storage.id}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save()

        forecast.refresh_from_db()
        assert forecast.storage_id is None

    def test_patch_cannot_set_the_day_number(self, tenant):
        forecast = ForecastFactory()
        assert forecast.day_number is None

        serializer = ForecastSerializer(
            instance=forecast, data={"day_number": 3}, partial=True
        )
        assert serializer.is_valid(), serializer.errors
        assert "day_number" not in serializer.validated_data
        serializer.save()

        forecast.refresh_from_db()
        assert forecast.day_number is None
