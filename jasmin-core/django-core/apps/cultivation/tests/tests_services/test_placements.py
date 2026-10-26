"""Manual placement rules — ``services.placements.save_placements``.

The gardener may override agronomy (rotation breaks, succession taste) but not
geometry. These tests pin the geometric rules: a placement may not run past the
end of a plot, a batch may not be placed twice, and — the part this suite exists
for — a batch sized in beds of one type must sit WHOLLY inside a block of that
type.

Both the present and the absent case of ``CultivationBatch.used_bed_type`` are
exercised: a NULL FK short-circuits ``_check_bed_type`` before it looks at a
single segment, so a suite built only on unset batches would pass against code
with the whole rule deleted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.cultivation.errors import (
    BatchPlacedTwice,
    BedTypeMismatch,
    PlacementOutOfBounds,
)
from apps.cultivation.models import (
    BedType,
    CultivationBatch,
    CultivationPlanSolution,
    Plot,
    PlotContent,
    Vegetable,
)
from apps.cultivation.optimizer.loading import plot_segments
from apps.cultivation.services.placements import ProposedPlacement, save_placements

# The demo grain: 5 optimizer cells per gardener's bed.
CELLS_PER_BED = 5

# Layout under test: 4 standard beds (cells 0..19) then 2 short beds (20..29).
STANDARD_BEDS = 4
SHORT_BEDS = 2
STANDARD_END = STANDARD_BEDS * CELLS_PER_BED  # 20
CAPACITY = (STANDARD_BEDS + SHORT_BEDS) * CELLS_PER_BED  # 30


@pytest.fixture()
def bed_types(tenant):
    standard = BedType.objects.create(
        name="Standard 50 m", length_in_m=50, width_in_m=Decimal("0.75")
    )
    short = BedType.objects.create(
        name="Short 25 m", length_in_m=25, width_in_m=Decimal("0.75")
    )
    return standard, short


@pytest.fixture()
def plot(bed_types):
    """A plot whose blocks are CREATED in the reverse of their layout order.

    ``position`` — not insertion order, not pk — decides which physical beds a
    cell index refers to. The short block is therefore written FIRST and given
    the id that sorts FIRST, while carrying the LATER position; the pks are
    pinned rather than left to nanoid so the ordering is not a coin flip. Every
    expectation below (standard at cells 0..19) fails if ``position`` is ignored,
    whether the fallback is insertion order or pk order.
    """
    standard, short = bed_types
    plot = Plot.objects.create(name="Brook field", is_greenhouse=False)
    PlotContent.objects.create(
        id="AAAAAAAAAAAA",
        plot=plot,
        bed_type=short,
        amount=SHORT_BEDS,
        position=2,
    )
    PlotContent.objects.create(
        id="ZZZZZZZZZZZZ",
        plot=plot,
        bed_type=standard,
        amount=STANDARD_BEDS,
        position=1,
    )
    return plot


@pytest.fixture()
def vegetable(tenant):
    return Vegetable.objects.create(
        name="Cabbage",
        unit="PCS",
        average_kg_per_piece=Decimal("1.400"),
        default_planting_lines=2,
        default_distance_in_row=Decimal("0.50"),
        default_planting_mode="PLANTING",
        fertilizer_requirement="STRONG",
    )


def make_batch(vegetable, bed_type=None, *, beds="2.00", planting_week=14):
    """A finalized outdoor batch of ``beds`` beds of ``bed_type``.

    ``bed_type=None`` is the gardener's "place me anywhere" filler crop.
    """
    return CultivationBatch.objects.create(
        year=2027,
        planting_week=planting_week,
        harvesting_start_week=planting_week + 8,
        harvesting_end_week=planting_week + 10,
        end_week=planting_week + 12,
        vegetable=vegetable,
        planting_lines=2,
        distance_in_row_in_m=Decimal("0.500"),
        planting_mode="PLANTING",
        pieces_per_plant=Decimal("1.0"),
        yield_kg_per_m2=Decimal("2.50"),
        used_bed_type=bed_type,
        amount_of_beds=Decimal(beds),
        is_final=True,
    )


@pytest.fixture()
def solution(tenant):
    return CultivationPlanSolution.objects.create(
        year=2027, version=1, cells_per_bed=CELLS_PER_BED
    )


class TestPlotSegments:
    def test_blocks_are_laid_out_in_position_order_not_creation_order(self, plot):
        fresh = Plot.objects.get(pk=plot.pk)

        segments = plot_segments(fresh, CELLS_PER_BED)

        assert [s.bed_type_name for s in segments] == ["Standard 50 m", "Short 25 m"]
        assert [(s.start_cell, s.cell_count) for s in segments] == [
            (0, STANDARD_END),
            (STANDARD_END, SHORT_BEDS * CELLS_PER_BED),
        ]
        assert segments[-1].end_cell == CAPACITY


class TestTypedBatchPlacement:
    """``used_bed_type`` set — the branch a NULL FK never reaches."""

    def test_inside_its_own_block_succeeds(self, solution, plot, vegetable, bed_types):
        standard, _short = bed_types
        batch = make_batch(vegetable, standard)

        details = save_placements(
            solution,
            [ProposedPlacement(batch_id=batch.pk, plot_id=plot.pk, start_cell=0)],
        )

        assert len(details) == 1
        assert details[0].start_cell == 0
        assert details[0].cell_count == 10
        assert solution.details.count() == 1

    def test_last_start_that_still_ends_on_the_border_succeeds(
        self, solution, plot, vegetable, bed_types
    ):
        standard, _short = bed_types
        batch = make_batch(vegetable, standard)
        last_legal_start = STANDARD_END - 10  # 10 cells ending exactly at cell 20

        details = save_placements(
            solution,
            [
                ProposedPlacement(
                    batch_id=batch.pk, plot_id=plot.pk, start_cell=last_legal_start
                )
            ],
        )

        assert details[0].start_cell == last_legal_start

    def test_block_of_another_bed_type_is_rejected(
        self, solution, plot, vegetable, bed_types
    ):
        standard, _short = bed_types
        batch = make_batch(vegetable, standard)

        # Cells 20..29 are free and in bounds — only the bed type rules them out.
        with pytest.raises(BedTypeMismatch) as excinfo:
            save_placements(
                solution,
                [
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=STANDARD_END
                    )
                ],
            )

        assert excinfo.value.code == "cultivation.bed_type_mismatch"
        assert "Short 25 m" in excinfo.value.message
        assert excinfo.value.details["bed_type"] == standard.pk
        assert not solution.details.exists()

    def test_run_straddling_the_block_boundary_is_rejected(
        self, solution, plot, vegetable, bed_types
    ):
        standard, _short = bed_types
        batch = make_batch(vegetable, standard)
        # Start cell 15 IS a standard cell, but the 10-cell run ends at 25 —
        # half the crop would sit on short beds.
        straddling_start = STANDARD_END - 5

        with pytest.raises(BedTypeMismatch) as excinfo:
            save_placements(
                solution,
                [
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=straddling_start
                    )
                ],
            )

        assert "cross out of the Standard 50 m block" in excinfo.value.message
        assert excinfo.value.details["allowed_start_ranges"] == [[0, 10]]

    def test_batch_longer_than_every_block_of_its_type_is_rejected(
        self, solution, plot, vegetable, bed_types
    ):
        _standard, short = bed_types
        # 3 short beds = 15 cells, but the short block only holds 10. Started at
        # cell 0 the run is comfortably inside the plot, so the bounds check
        # passes and only the bed-type rule can catch it.
        batch = make_batch(vegetable, short, beds="3.00")

        with pytest.raises(BedTypeMismatch) as excinfo:
            save_placements(
                solution,
                [ProposedPlacement(batch_id=batch.pk, plot_id=plot.pk, start_cell=0)],
            )

        assert "no block of Short 25 m" in excinfo.value.message
        assert excinfo.value.details["allowed_start_ranges"] == []


class TestUntypedBatchPlacement:
    """``used_bed_type`` NULL — the gardener's filler crop goes anywhere."""

    def test_may_start_in_either_block(self, solution, plot, vegetable):
        batch = make_batch(vegetable, None)

        for start_cell in (0, STANDARD_END):
            details = save_placements(
                solution,
                [
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=start_cell
                    )
                ],
            )
            assert details[0].start_cell == start_cell

    def test_may_straddle_the_block_boundary(self, solution, plot, vegetable):
        batch = make_batch(vegetable, None)
        straddling_start = STANDARD_END - 5

        details = save_placements(
            solution,
            [
                ProposedPlacement(
                    batch_id=batch.pk, plot_id=plot.pk, start_cell=straddling_start
                )
            ],
        )

        assert details[0].start_cell == straddling_start
        assert details[0].end_cell > STANDARD_END


class TestGeometryGuardsStillFire:
    def test_running_past_the_end_of_the_plot_is_out_of_bounds(
        self, solution, plot, vegetable, bed_types
    ):
        _standard, short = bed_types
        batch = make_batch(vegetable, short)

        with pytest.raises(PlacementOutOfBounds) as excinfo:
            save_placements(
                solution,
                [
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=CAPACITY - 5
                    )
                ],
            )

        assert excinfo.value.details["capacity"] == CAPACITY

    def test_untyped_batch_past_the_end_is_out_of_bounds_too(
        self, solution, plot, vegetable
    ):
        batch = make_batch(vegetable, None)

        with pytest.raises(PlacementOutOfBounds):
            save_placements(
                solution,
                [
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=CAPACITY
                    )
                ],
            )

    def test_the_same_batch_twice_is_rejected(
        self, solution, plot, vegetable, bed_types
    ):
        standard, _short = bed_types
        batch = make_batch(vegetable, standard)

        with pytest.raises(BatchPlacedTwice) as excinfo:
            save_placements(
                solution,
                [
                    ProposedPlacement(batch_id=batch.pk, plot_id=plot.pk, start_cell=0),
                    ProposedPlacement(
                        batch_id=batch.pk, plot_id=plot.pk, start_cell=10
                    ),
                ],
            )

        assert excinfo.value.details["batch"] == batch.pk
        assert not solution.details.exists()
