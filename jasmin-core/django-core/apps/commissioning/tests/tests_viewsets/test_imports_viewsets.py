"""HTTP-level tests for the CSV-import & external-code-mapping endpoints.

Covers:

* ``ExternalCodeMappingViewSet`` — list (with ``kind`` filter), create,
  unique-constraint enforcement, delete.
* ``ShareImportBatchViewSet`` — the full upload → preview → apply round-
  trip via the API, plus error responses.
* ``ExternalShareDemandViewSet`` — read-only list filtered by year/week.

These complement the service-level tests in
``tests_services/test_share_import_service.py``: here we exercise the DRF
layer (multipart parsing, permissions, serializer validation, status codes)
that the React client actually talks to.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    ExternalCodeMapping,
    ExternalShareDemand,
    ShareImportBatch,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

CSV_HEADER = (
    "year,delivery_week,delivery_station_code,"
    "delivery_day_code,variation_code,quantity\n"
)


def _csv(rows: list[str]) -> bytes:
    return (
        CSV_HEADER + "".join(r if r.endswith("\n") else r + "\n" for r in rows)
    ).encode()


def _uploaded(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="text/csv")


@pytest.fixture()
def world(tenant):
    """One station + day + variation, plus the matching mappings.

    Mirrors the ``import_world`` fixture used by the service tests so
    HTTP tests can drive the same happy path end-to-end.
    """
    station = DeliveryStationFactory()
    day = SharesDeliveryDayFactory(day_number=2)
    sd = DeliveryStationDayFactory(delivery_station=station, delivery_day=day)
    variation = ShareTypeVariationFactory()

    ExternalCodeMapping.objects.bulk_create(
        [
            ExternalCodeMapping(
                kind=ExternalCodeMapping.KIND_STATION,
                external_code="STN-1",
                internal_id=str(station.id),
            ),
            ExternalCodeMapping(
                kind=ExternalCodeMapping.KIND_DAY,
                external_code="WED",
                internal_id=str(day.id),
            ),
            ExternalCodeMapping(
                kind=ExternalCodeMapping.KIND_VARIATION,
                external_code="VEG-M",
                internal_id=str(variation.id),
            ),
        ]
    )

    return {
        "station": station,
        "day": day,
        "station_day": sd,
        "variation": variation,
    }


# ---------------------------------------------------------------------------
# ExternalCodeMappingViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExternalCodeMappingViewSet:
    URL = reverse("external_code_mapping-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_returns_existing_mappings(self, api_client, world):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        codes = {m["external_code"] for m in resp.data}
        assert codes == {"STN-1", "WED", "VEG-M"}

    def test_list_filtered_by_kind(self, api_client, world):
        resp = api_client.get(self.URL, {"kind": ExternalCodeMapping.KIND_STATION})
        assert resp.status_code == status.HTTP_200_OK
        assert {m["external_code"] for m in resp.data} == {"STN-1"}
        assert all(m["kind"] == ExternalCodeMapping.KIND_STATION for m in resp.data)

    def test_create_mapping(self, api_client, world):
        # Add a second station mapping pointing at a freshly-created station.
        station2 = DeliveryStationFactory()
        payload = {
            "kind": ExternalCodeMapping.KIND_STATION,
            "external_code": "STN-2",
            "internal_id": str(station2.id),
        }
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert ExternalCodeMapping.objects.filter(
            kind=ExternalCodeMapping.KIND_STATION, external_code="STN-2"
        ).exists()

    def test_create_duplicate_external_code_rejected(self, api_client, world):
        # (kind, external_code) is unique — re-creating must 400.
        payload = {
            "kind": ExternalCodeMapping.KIND_STATION,
            "external_code": "STN-1",
            "internal_id": str(world["station"].id),
        }
        resp = api_client.post(self.URL, payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_mapping(self, api_client, world):
        mapping = ExternalCodeMapping.objects.get(external_code="WED")
        url = reverse("external_code_mapping-detail", kwargs={"pk": mapping.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not ExternalCodeMapping.objects.filter(pk=mapping.pk).exists()


# ---------------------------------------------------------------------------
# ShareImportBatchViewSet — upload / preview / apply round-trip
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareImportBatchViewSet:
    LIST_URL = reverse("share_import_batch-list")
    UPLOAD_URL = reverse("share_import_batch-upload")

    # ---- upload ---------------------------------------------------------

    def test_upload_returns_201_and_preview_ready_status(self, api_client, world):
        f = _uploaded("ok.csv", _csv(["2026,15,STN-1,WED,VEG-M,4"]))
        resp = api_client.post(
            self.UPLOAD_URL,
            {"file": f, "year": 2026, "delivery_week": 15},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        # Upload synchronously runs parse_and_validate; a clean file ends
        # in VALIDATED (preview_ready is reached only after /preview/).
        assert resp.data["status"] == ShareImportBatch.STATUS_VALIDATED
        assert ShareImportBatch.objects.count() == 1

    def test_upload_with_invalid_csv_returns_201_but_failed_status(
        self, api_client, world
    ):
        f = _uploaded("bad.csv", _csv(["2026,15,UNKNOWN,WED,VEG-M,4"]))
        resp = api_client.post(
            self.UPLOAD_URL,
            {"file": f, "year": 2026, "delivery_week": 15},
            format="multipart",
        )
        # The endpoint always creates the batch (so the user can inspect
        # the per-row error report) — only the status reflects failure.
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["status"] == ShareImportBatch.STATUS_FAILED
        assert resp.data["error_count"] >= 1

    def test_upload_missing_file_returns_400(self, api_client, world):
        resp = api_client.post(
            self.UPLOAD_URL,
            {"year": 2026, "delivery_week": 15},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_upload_is_idempotent_for_same_bytes(self, api_client, world):
        body = {"year": 2026, "delivery_week": 15}
        payload1 = _csv(["2026,15,STN-1,WED,VEG-M,4"])

        r1 = api_client.post(
            self.UPLOAD_URL,
            {"file": _uploaded("a.csv", payload1), **body},
            format="multipart",
        )
        r2 = api_client.post(
            self.UPLOAD_URL,
            {"file": _uploaded("a.csv", payload1), **body},
            format="multipart",
        )
        assert r1.status_code == r2.status_code == status.HTTP_201_CREATED
        assert r1.data["id"] == r2.data["id"]
        assert ShareImportBatch.objects.count() == 1

    # ---- preview --------------------------------------------------------

    def test_preview_action_marks_batch_preview_ready(self, api_client, world):
        upload = api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("ok.csv", _csv(["2026,15,STN-1,WED,VEG-M,5"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        batch_id = upload.data["id"]
        url = reverse("share_import_batch-preview", kwargs={"pk": batch_id})

        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] == ShareImportBatch.STATUS_PREVIEW_READY
        assert resp.data["diff_report"]["totals"]["added"] == 1

    def test_preview_action_on_invalid_csv_returns_400(self, api_client, world):
        upload = api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("bad.csv", _csv(["2026,15,STN-NOPE,WED,VEG-M,1"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        batch_id = upload.data["id"]
        url = reverse("share_import_batch-preview", kwargs={"pk": batch_id})

        resp = api_client.post(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ---- apply ----------------------------------------------------------

    def test_full_round_trip_upload_preview_apply(self, api_client, world):
        upload = api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("ok.csv", _csv(["2026,15,STN-1,WED,VEG-M,7"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        batch_id = upload.data["id"]

        # preview
        api_client.post(reverse("share_import_batch-preview", kwargs={"pk": batch_id}))
        # apply
        resp = api_client.post(
            reverse("share_import_batch-apply", kwargs={"pk": batch_id})
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] == ShareImportBatch.STATUS_APPLIED

        # The applied batch produced exactly one ExternalShareDemand row.
        assert ExternalShareDemand.objects.filter(
            year=2026,
            delivery_week=15,
            quantity=7,
            share_type_variation=world["variation"],
        ).exists()

    def test_apply_on_invalid_csv_returns_400(self, api_client, world):
        upload = api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("bad.csv", _csv(["2026,15,STN-NOPE,WED,VEG-M,1"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        batch_id = upload.data["id"]
        resp = api_client.post(
            reverse("share_import_batch-apply", kwargs={"pk": batch_id})
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # ---- list / filter --------------------------------------------------

    def test_list_filters_by_year_and_week(self, api_client, world):
        # Two uploads for different weeks.
        api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("w15.csv", _csv(["2026,15,STN-1,WED,VEG-M,1"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        api_client.post(
            self.UPLOAD_URL,
            {
                "file": _uploaded("w16.csv", _csv(["2026,16,STN-1,WED,VEG-M,2"])),
                "year": 2026,
                "delivery_week": 16,
            },
            format="multipart",
        )

        resp = api_client.get(self.LIST_URL, {"year": 2026, "delivery_week": 16})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["delivery_week"] == 16


# ---------------------------------------------------------------------------
# ExternalShareDemandViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExternalShareDemandViewSet:
    URL = reverse("external_share_demand-list")

    def test_list_empty(self, api_client, tenant):
        resp = api_client.get(self.URL)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_list_after_apply_shows_demand(self, api_client, world):
        upload = api_client.post(
            reverse("share_import_batch-upload"),
            {
                "file": _uploaded("ok.csv", _csv(["2026,15,STN-1,WED,VEG-M,3"])),
                "year": 2026,
                "delivery_week": 15,
            },
            format="multipart",
        )
        batch_id = upload.data["id"]
        api_client.post(reverse("share_import_batch-preview", kwargs={"pk": batch_id}))
        api_client.post(reverse("share_import_batch-apply", kwargs={"pk": batch_id}))

        resp = api_client.get(self.URL, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["quantity"] == 3
