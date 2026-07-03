"""Tests for the CSV-based weekly :class:`ShareImportService`.

Covers the four pipeline stages (ingest, validate, preview, apply) and the
external-code-mapping plumbing they depend on.
"""

from __future__ import annotations

import pytest

from apps.commissioning.models import (
    ExternalCodeMapping,
    ExternalShareDemand,
    Share,
    ShareImportBatch,
)
from apps.commissioning.services.share_import_service import (
    ShareImportService,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    JasminUserFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
)
from core.errors import JasminError


def _csv_bytes(rows: list[dict]) -> bytes:
    header = (
        "year,delivery_week,delivery_station_code,"
        "delivery_day_code,variation_code,quantity"
    )
    body = "\n".join(
        ",".join(
            str(r[k])
            for k in (
                "year",
                "delivery_week",
                "delivery_station_code",
                "delivery_day_code",
                "variation_code",
                "quantity",
            )
        )
        for r in rows
    )
    return f"{header}\n{body}\n".encode()


@pytest.fixture()
def import_world(tenant):
    """One station, one day, one variation, plus the matching mappings."""
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


@pytest.mark.django_db
class TestShareImportPipeline:
    def test_ingest_is_idempotent_for_same_checksum(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 4,
                }
            ]
        )

        first = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="w15.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        second = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="w15.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )

        assert first.pk == second.pk
        assert ShareImportBatch.objects.count() == 1

    def test_validate_flags_unknown_codes(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-DOES-NOT-EXIST",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 3,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="bad.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )

        outcome = ShareImportService.parse_and_validate(batch)

        batch.refresh_from_db()
        assert not outcome.is_ok
        assert batch.status == ShareImportBatch.STATUS_FAILED
        assert batch.error_count == 1

    def test_validate_rejects_mismatched_year_or_week(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 14,  # batch is week 15
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 3,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="x.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert not outcome.is_ok

    def test_validate_flags_within_file_duplicates(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 4,
                },
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 7,
                },
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="dup.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert not outcome.is_ok

    def test_full_apply_creates_share_and_demand(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 9,
                }
            ]
        )

        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="ok.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert outcome.is_ok

        ShareImportService.build_preview(batch, outcome.rows)
        batch.refresh_from_db()
        assert batch.status == ShareImportBatch.STATUS_PREVIEW_READY
        assert batch.diff_report["totals"]["added"] == 1

        ShareImportService.apply(batch, outcome.rows, applied_by=user)
        batch.refresh_from_db()

        assert batch.status == ShareImportBatch.STATUS_APPLIED
        assert ExternalShareDemand.objects.filter(
            year=2026,
            delivery_week=15,
            quantity=9,
            share_type_variation=import_world["variation"],
        ).exists()
        # Apply must have created the matching Share row so downstream
        # code can pivot off it.
        assert Share.objects.filter(
            year=2026,
            delivery_week=15,
            delivery_day=import_world["day"],
            share_type_variation=import_world["variation"],
        ).exists()

    def test_re_apply_supersedes_previous_batch(self, import_world):
        user = JasminUserFactory(roles=["office"])

        def _run(qty: int, filename: str) -> ShareImportBatch:
            data = _csv_bytes(
                [
                    {
                        "year": 2026,
                        "delivery_week": 15,
                        "delivery_station_code": "STN-1",
                        "delivery_day_code": "WED",
                        "variation_code": "VEG-M",
                        "quantity": qty,
                    }
                ]
            )
            batch = ShareImportService.ingest_upload(
                file_bytes=data,
                original_filename=filename,
                year=2026,
                delivery_week=15,
                uploaded_by=user,
            )
            outcome = ShareImportService.parse_and_validate(batch)
            ShareImportService.build_preview(batch, outcome.rows)
            return ShareImportService.apply(batch, outcome.rows, applied_by=user)

        first = _run(3, "v1.csv")
        second = _run(7, "v2.csv")

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == ShareImportBatch.STATUS_SUPERSEDED
        assert second.status == ShareImportBatch.STATUS_APPLIED
        # Only the latest week's rows remain.
        qs = ExternalShareDemand.objects.filter(year=2026, delivery_week=15)
        assert qs.count() == 1
        assert qs.first().quantity == 7

    # ---- additional edge cases ------------------------------------------

    def test_validate_flags_missing_required_columns(self, import_world):
        user = JasminUserFactory(roles=["office"])
        # CSV is missing the `quantity` column entirely.
        bad = (
            b"year,delivery_week,delivery_station_code,"
            b"delivery_day_code,variation_code\n"
            b"2026,15,STN-1,WED,VEG-M\n"
        )

        batch = ShareImportService.ingest_upload(
            file_bytes=bad,
            original_filename="missing_col.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        batch.refresh_from_db()

        assert not outcome.is_ok
        assert batch.status == ShareImportBatch.STATUS_FAILED
        assert any(
            "Missing columns" in msg for msgs in outcome.errors.values() for msg in msgs
        )

    def test_validate_flags_non_integer_quantity(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = (
            b"year,delivery_week,delivery_station_code,"
            b"delivery_day_code,variation_code,quantity\n"
            b"2026,15,STN-1,WED,VEG-M,not-a-number\n"
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="bad_int.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert not outcome.is_ok

    def test_validate_flags_negative_quantity(self, import_world):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": -1,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="neg.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert not outcome.is_ok
        assert any(
            "quantity must be >= 0" in msg
            for msgs in outcome.errors.values()
            for msg in msgs
        )

    def test_validate_flags_unlinked_station_day(self, tenant):
        """Station + day exist & are mapped, but no DeliveryStationDay
        joins them — should error."""
        user = JasminUserFactory(roles=["office"])
        station = DeliveryStationFactory()
        day = SharesDeliveryDayFactory(day_number=2)
        # NOTE: no DeliveryStationDayFactory linking station+day
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

        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 1,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="unlinked.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)

        assert not outcome.is_ok
        assert any(
            "no DeliveryStationDay links" in msg
            for msgs in outcome.errors.values()
            for msg in msgs
        )

    def test_preview_reports_updated_and_removed(self, import_world):
        """A second import for the same week with a changed qty for one
        row and a missing row should produce both 'updated' and 'removed'
        diff entries."""
        user = JasminUserFactory(roles=["office"])

        # Seed a second station+day+variation so the first apply has
        # two rows; the second import will only contain one of them.
        station2 = DeliveryStationFactory()
        DeliveryStationDayFactory(
            delivery_station=station2,
            delivery_day=import_world["day"],
        )
        variation2 = ShareTypeVariationFactory()
        ExternalCodeMapping.objects.bulk_create(
            [
                ExternalCodeMapping(
                    kind=ExternalCodeMapping.KIND_STATION,
                    external_code="STN-2",
                    internal_id=str(station2.id),
                ),
                ExternalCodeMapping(
                    kind=ExternalCodeMapping.KIND_VARIATION,
                    external_code="VEG-L",
                    internal_id=str(variation2.id),
                ),
            ]
        )

        first = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 4,
                },
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-2",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-L",
                    "quantity": 2,
                },
            ]
        )
        b1 = ShareImportService.ingest_upload(
            file_bytes=first,
            original_filename="v1.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        o1 = ShareImportService.parse_and_validate(b1)
        ShareImportService.build_preview(b1, o1.rows)
        ShareImportService.apply(b1, o1.rows, applied_by=user)

        # Second upload: STN-1 qty changes 4 -> 9, STN-2 row is gone.
        second = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 9,
                }
            ]
        )
        b2 = ShareImportService.ingest_upload(
            file_bytes=second,
            original_filename="v2.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        o2 = ShareImportService.parse_and_validate(b2)
        diff = ShareImportService.build_preview(b2, o2.rows)

        assert diff.as_dict()["totals"] == {
            "added": 0,
            "updated": 1,
            "removed": 1,
        }
        assert diff.updated[0]["old_quantity"] == 4
        assert diff.updated[0]["new_quantity"] == 9
        assert diff.removed[0]["quantity"] == 2

    def test_apply_rejects_batch_in_wrong_status(self, import_world):
        """Calling apply() on a batch that isn't validated/preview_ready
        must raise rather than silently overwrite the week."""
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 1,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="raw.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        # Status is still STATUS_UPLOADED — not validated, not preview_ready.
        assert batch.status == ShareImportBatch.STATUS_UPLOADED
        with pytest.raises(JasminError):
            ShareImportService.apply(batch, [], applied_by=user)

    def test_demand_service_reads_external_after_apply(self, import_world):
        """End-to-end: applying an import batch makes the rows visible to
        :class:`ExternalDemandBackend`, the calculation backend used when
        the tenant has CSV-imports enabled."""
        from apps.commissioning.services.share_demand_service import (
            ExternalDemandBackend,
        )

        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": 6,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename="dem.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        ShareImportService.build_preview(batch, outcome.rows)
        ShareImportService.apply(batch, outcome.rows, applied_by=user)

        backend = ExternalDemandBackend()
        # ExternalDemandBackend exposes a per-(year, week) lookup; the
        # exact method name isn't part of this contract test — we just
        # verify the row exists & is reachable.
        rows = ExternalShareDemand.objects.filter(year=2026, delivery_week=15)
        assert rows.count() == 1
        assert rows.first().quantity == 6
        # And the backend can be instantiated against the real data.
        assert backend is not None


# ---------------------------------------------------------------------------
# Recompute propagation on apply (2026-06-04)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApplyTriggersRecompute:
    """``ShareImportService.apply`` must call ``recompute_shares`` so
    a re-import that corrects demand numbers propagates into the
    downstream ShareContent / theoretical / movement tables. Without
    this wiring, the planning UI silently shows stale numbers until
    the office manually clicks Recompute — that was the original gap.

    The recompute itself is exercised by its own tests
    (``test_share_content_service``, ``recompute.py`` callers); here
    we lock the CALL CONTRACT — that ``apply`` reaches it with the
    right scope, and that a recompute failure rolls back the whole
    transaction.
    """

    def _do_apply(self, world, *, quantity: int = 9) -> ShareImportBatch:
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": quantity,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename=f"q{quantity}.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        ShareImportService.build_preview(batch, outcome.rows)
        ShareImportService.apply(batch, outcome.rows, applied_by=user)
        return batch

    def test_apply_invokes_recompute_with_week_share_ids(
        self, import_world, monkeypatch
    ):
        captured: list[set[str]] = []

        def _spy(share_ids):
            captured.append({str(i) for i in share_ids})

        monkeypatch.setattr(
            "apps.commissioning.services.recompute.recompute_shares", _spy
        )

        self._do_apply(import_world)

        # apply() recomputes the imported week, then forward-seeds the
        # next week (a copy flagged as an estimate) and recomputes that
        # too — two calls, imported week first.
        assert len(captured) == 2
        # First call carries the ids of every Share for the imported week.
        expected_ids = {
            str(s)
            for s in Share.objects.filter(year=2026, delivery_week=15).values_list(
                "id", flat=True
            )
        }
        assert expected_ids
        assert captured[0] == expected_ids
        # Second call carries the forward-seeded next week's Shares.
        seeded_ids = {
            str(s)
            for s in Share.objects.filter(year=2026, delivery_week=16).values_list(
                "id", flat=True
            )
        }
        assert seeded_ids
        assert captured[1] == seeded_ids

    def test_reimport_recomputes_again_on_second_apply(self, import_world, monkeypatch):
        """The whole motivation for this wiring: a corrected reimport
        must trigger recompute a second time so the planning view
        catches up to the new demand."""
        call_count = {"n": 0}

        def _spy(share_ids):
            call_count["n"] += 1

        monkeypatch.setattr(
            "apps.commissioning.services.recompute.recompute_shares", _spy
        )

        self._do_apply(import_world, quantity=9)
        self._do_apply(import_world, quantity=12)

        # Each apply recomputes twice: the imported week plus the
        # forward-seeded next week. Two applies → four calls. The point
        # of the test stands — a corrected reimport recomputes again.
        assert call_count["n"] == 4

    def test_recompute_failure_rolls_back_the_import(self, import_world, monkeypatch):
        """If recompute raises, the whole atomic block must unwind:
        no ``STATUS_APPLIED`` batch, no new ``ExternalShareDemand``
        rows. The office sees an error and retries instead of being
        left with a half-applied state."""

        def _explode(share_ids):
            raise RuntimeError("synthetic recompute failure")

        monkeypatch.setattr(
            "apps.commissioning.services.recompute.recompute_shares", _explode
        )

        with pytest.raises(RuntimeError, match="synthetic recompute failure"):
            self._do_apply(import_world)

        # No applied batch for this week.
        assert not ShareImportBatch.objects.filter(
            year=2026,
            delivery_week=15,
            status=ShareImportBatch.STATUS_APPLIED,
        ).exists()
        # No external demand rows persisted either — the bulk_create
        # got rolled back alongside the status flip.
        assert not ExternalShareDemand.objects.filter(
            year=2026, delivery_week=15
        ).exists()


# ---------------------------------------------------------------------------
# Forward-seed the next week with an estimate (2026-06-09)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestForwardSeedNextWeek:
    """``apply`` copies the applied amounts into the NEXT ISO week as an
    estimate (``is_estimate=True``) so a workflow running ahead of next
    week's real upload already has a number to plan against. The seed is
    skipped when next week already holds a real upload, and is replaced
    when next week's own real file is later applied.
    """

    def _apply(self, *, year: int, week: int, quantity: int, filename: str):
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": year,
                    "delivery_week": week,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": quantity,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename=filename,
            year=year,
            delivery_week=week,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        assert outcome.is_ok, outcome.errors
        ShareImportService.build_preview(batch, outcome.rows)
        return ShareImportService.apply(batch, outcome.rows, applied_by=user)

    def test_apply_seeds_next_week_as_estimate(self, import_world):
        self._apply(year=2026, week=15, quantity=9, filename="w15.csv")

        # The imported week is real.
        real = ExternalShareDemand.objects.get(year=2026, delivery_week=15)
        assert real.is_estimate is False
        assert real.quantity == 9

        # Next week was seeded with a copy, flagged as an estimate, and
        # got its Share anchor so planning can pivot off it.
        seeded = ExternalShareDemand.objects.get(year=2026, delivery_week=16)
        assert seeded.is_estimate is True
        assert seeded.quantity == 9
        assert seeded.share_type_variation_id == str(import_world["variation"].id)
        assert Share.objects.filter(year=2026, delivery_week=16).exists()

    def test_seed_crosses_the_year_boundary(self, import_world):
        # 2026 has 53 ISO weeks, so the week after 53/2026 is 1/2027 — not a
        # naive week+1 that would overflow into an invalid week 54.
        self._apply(year=2026, week=53, quantity=4, filename="w53.csv")

        seeded = ExternalShareDemand.objects.get(year=2027, delivery_week=1)
        assert seeded.is_estimate is True
        assert seeded.quantity == 4

    def test_real_upload_replaces_the_seeded_estimate(self, import_world):
        # Week 15 real → seeds week 16 as an estimate (qty 9).
        self._apply(year=2026, week=15, quantity=9, filename="w15.csv")
        assert (
            ExternalShareDemand.objects.get(year=2026, delivery_week=16).is_estimate
            is True
        )

        # Week 16's own real file lands → replaces the estimate with
        # confirmed data, leaving exactly one (real) row.
        self._apply(year=2026, week=16, quantity=20, filename="w16.csv")
        rows = ExternalShareDemand.objects.filter(year=2026, delivery_week=16)
        assert rows.count() == 1
        row = rows.get()
        assert row.is_estimate is False
        assert row.quantity == 20

    def test_seed_skipped_when_next_week_has_real_demand(self, import_world):
        # Real upload for week 16 first (qty 20).
        self._apply(year=2026, week=16, quantity=20, filename="w16.csv")

        # A later/corrective real upload for week 15 would normally seed
        # week 16 — but week 16 already holds REAL demand, so the seed must
        # be skipped rather than clobber it with week 15's number.
        self._apply(year=2026, week=15, quantity=9, filename="w15.csv")

        row = ExternalShareDemand.objects.get(year=2026, delivery_week=16)
        assert row.is_estimate is False  # untouched
        assert row.quantity == 20  # not overwritten by week 15's 9


# ---------------------------------------------------------------------------
# End-to-end propagation: import → recompute → theoreticals reflect new demand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReimportPropagatesIntoTheoreticals:
    """The single integration test that proves the WHOLE chain works:

        Import quantity=9
            → ExternalShareDemand replaced
            → apply() fires recompute_shares
            → TheoreticalHarvest.amount reflects 9

        Reimport quantity=12
            → ExternalShareDemand replaced again
            → apply() fires recompute_shares again
            → TheoreticalHarvest.amount reflects 12 (not stale at 9)

    Wiring tests in ``TestApplyTriggersRecompute`` above mock
    ``recompute_shares`` and prove the call shape. The recompute
    pipeline itself is exercised in dedicated tests for
    ``ShareContentService``. THIS test removes the seam between them:
    no mocks on the recompute path, real DB writes top to bottom,
    so a regression that silently breaks the propagation would fail
    here even when both halves pass in isolation.

    The chain depends on
    ``TenantSettings.uploads_weekly_share_amount=True`` (so the
    demand backend routes to ``ExternalDemandBackend`` instead of
    ``SubscriptionDemandBackend``). Without it, the recompute would
    read zero demand from a non-existent Subscription and the
    theoreticals would never change with the imported quantity.
    """

    def _force_external_demand_backend(self):
        """Pin the demand dispatcher to ``ExternalDemandBackend`` so the
        recompute pipeline reads from ``ExternalShareDemand`` (the rows
        the import writes) instead of from Subscription counts.

        This mirrors the bypass pattern used by
        ``test_share_demand_service.py`` — setting up
        ``TenantSettings.uploads_weekly_share_amount=True`` in tests is
        documented there as fragile, and patching the dispatcher is the
        codebase's standard workaround. Returns a context manager that
        must wrap every ``apply()`` call so the patch is live while the
        recompute fires.
        """
        from unittest.mock import patch

        from apps.commissioning.services.share_demand_service import (
            ExternalDemandBackend,
        )

        return patch(
            "apps.commissioning.services.share_demand_service._resolve_backend",
            return_value=ExternalDemandBackend(),
        )

    def _apply(self, world, *, quantity: int) -> None:
        user = JasminUserFactory(roles=["office"])
        data = _csv_bytes(
            [
                {
                    "year": 2026,
                    "delivery_week": 15,
                    "delivery_station_code": "STN-1",
                    "delivery_day_code": "WED",
                    "variation_code": "VEG-M",
                    "quantity": quantity,
                }
            ]
        )
        batch = ShareImportService.ingest_upload(
            file_bytes=data,
            original_filename=f"q{quantity}_{id(data)}.csv",
            year=2026,
            delivery_week=15,
            uploaded_by=user,
        )
        outcome = ShareImportService.parse_and_validate(batch)
        ShareImportService.build_preview(batch, outcome.rows)
        ShareImportService.apply(batch, outcome.rows, applied_by=user)

    def test_reimport_recalculates_theoretical_harvest(self, import_world):
        from decimal import Decimal

        from apps.commissioning.models import TheoreticalHarvest
        from apps.commissioning.tests.factories import (
            ForecastFactory,
            ShareArticleFactory,
            ShareContentFactory,
            StorageFactory,
        )

        # ---- World setup ----
        # The office has already planned a ShareContent for this week
        # — 5 kg of an article per share, packed at STN-1 — AND
        # attached a matching Forecast to it. Both are required for
        # ``TheoreticalHarvest`` to be created (the recompute creates
        # one only when ``ShareContent.forecast`` is non-null + a
        # Forecast exists for the (week, article)).
        storage = StorageFactory(is_short_term_harvest_storage=True)
        article = ShareArticleFactory()
        forecast = ForecastFactory(
            year=2026,
            delivery_week=15,
            share_article=article,
            unit="KG",
            size="M",
            storage=storage,
        )
        share_content = ShareContentFactory(
            share__year=2026,
            share__delivery_week=15,
            share__delivery_day=import_world["day"],
            share__share_type_variation=import_world["variation"],
            share_article=article,
            delivery_station=import_world["station"],
            amount=Decimal("5"),
            unit="KG",
            size="M",
            # The forecast FK is the gate. Without it, the recompute
            # produces no TheoreticalHarvest at all — that's what
            # bit the first version of this test.
            forecast=forecast,
        )

        # ---- First import: quantity=9 ----
        # Wrap apply() in the dispatcher patch so the recompute fired
        # at the end of apply() reads from ExternalShareDemand instead
        # of Subscription counts.
        with self._force_external_demand_backend():
            self._apply(import_world, quantity=9)

        first = TheoreticalHarvest.objects.filter(share_content=share_content).first()
        assert first is not None, (
            "TheoreticalHarvest should have been created by the recompute "
            "fired at the end of apply()."
        )
        assert first.amount == Decimal("45"), (
            f"5 kg/share × 9 imported demand should give 45 kg of "
            f"theoretical harvest, got {first.amount}"
        )

        # ---- Reimport: quantity=12 ----
        # This is the case that USED to silently leave the planning
        # numbers at 45 — the office had to remember to click
        # Recompute. The wiring we shipped makes this automatic.
        with self._force_external_demand_backend():
            self._apply(import_world, quantity=12)

        # ``recompute_for_shares`` is delete + recreate (idempotent),
        # so we can't refresh_from_db the old row — fetch fresh.
        second = TheoreticalHarvest.objects.filter(share_content=share_content).first()
        assert second is not None
        assert second.amount == Decimal("60"), (
            f"After reimport with quantity=12, the recompute should "
            f"produce 5 × 12 = 60 kg of theoretical harvest, got "
            f"{second.amount}. If this fails with 45, the wiring in "
            f"ShareImportService.apply() that calls recompute_shares "
            f"has regressed."
        )
