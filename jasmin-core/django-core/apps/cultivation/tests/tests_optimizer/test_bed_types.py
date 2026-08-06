"""The optimizer's bed-type rule: a batch sized in beds of one type must sit
wholly inside a block of that type.

Two layers, both DB-free:

* pure unit tests over :func:`allowed_start_ranges` / :func:`segment_at`, built
  from hand-made ``PlotInput`` / ``BatchInput`` dataclasses;
* tiny CP-SAT models solved end to end, so the assertion is on what the SOLVER
  actually does rather than on the helper the solver is supposed to consult.

Both the present and the absent case of ``bed_type_id`` are covered: an untyped
batch never touches the bed-type branch at all, so a suite testing only ``None``
would pass against a version of the code with the rule removed.
"""

from __future__ import annotations

import pytest
from ortools.sat.python import cp_model

from apps.cultivation.errors import BatchDoesNotFit
from apps.cultivation.optimizer.config import SolverConfig
from apps.cultivation.optimizer.loading import (
    BatchInput,
    BedSegment,
    PlotInput,
    allowed_start_ranges,
    segment_at,
)
from apps.cultivation.optimizer.model import build_model

STANDARD = "bedtype-standard"
SHORT = "bedtype-short"
GREENHOUSE = "bedtype-greenhouse"

# Standard beds occupy cells [0, 80), short beds [80, 120).
MIXED_PLOT = PlotInput(
    id="plot-mixed",
    name="Brook field",
    cell_capacity=120,
    segments=(
        BedSegment(
            bed_type_id=STANDARD,
            bed_type_name="Standard 50 m",
            start_cell=0,
            cell_count=80,
        ),
        BedSegment(
            bed_type_id=SHORT,
            bed_type_name="Short 25 m",
            start_cell=80,
            cell_count=40,
        ),
    ),
)


def make_batch(
    cell_count: int,
    bed_type_id: str | None = None,
    *,
    batch_id: str = "batch-1",
    planting_week: int = 10,
    end_week: int = 20,
    planting_lines: int = 1,
) -> BatchInput:
    """A minimal batch — only ``cell_count`` and ``bed_type_id`` matter here."""
    return BatchInput(
        id=batch_id,
        cell_count=cell_count,
        planting_week=planting_week,
        end_week=end_week,
        family_id=None,
        break_years=0,
        planting_lines=planting_lines,
        fleece_until=None,
        bed_type_id=bed_type_id,
    )


class TestAllowedStartRangesUntyped:
    """A batch with no ``used_bed_type`` may start anywhere it still fits."""

    def test_untyped_batch_spans_the_whole_plot(self):
        ranges = allowed_start_ranges(make_batch(10), MIXED_PLOT)

        assert ranges == [(0, 110)]

    def test_untyped_batch_may_start_inside_the_second_block(self):
        # 110 is deep inside the Short block — an untyped batch is not confined
        # to the first block, and it may straddle the boundary between them.
        lo, hi = allowed_start_ranges(make_batch(10), MIXED_PLOT)[0]

        assert lo <= 75 <= hi  # a run crossing cell 80 is legal
        assert hi == MIXED_PLOT.cell_capacity - 10

    def test_untyped_batch_exactly_filling_the_plot_has_one_start(self):
        assert allowed_start_ranges(make_batch(120), MIXED_PLOT) == [(0, 0)]

    def test_untyped_batch_bigger_than_the_plot_fits_nowhere(self):
        assert allowed_start_ranges(make_batch(121), MIXED_PLOT) == []

    def test_zero_cell_batch_fits_nowhere(self):
        assert allowed_start_ranges(make_batch(0), MIXED_PLOT) == []
        assert allowed_start_ranges(make_batch(0, STANDARD), MIXED_PLOT) == []


class TestAllowedStartRangesTyped:
    """A typed batch is confined to its own block, run included."""

    def test_first_block_upper_bound_stops_short_of_the_boundary(self):
        # Standard is [0, 80); a 10-cell run may start at 70 (ends at 80) but not
        # at 71, which would spill into the Short block.
        assert allowed_start_ranges(make_batch(10, STANDARD), MIXED_PLOT) == [(0, 70)]

    def test_second_block_range_starts_at_the_block_not_the_plot(self):
        # Short is [80, 120): starts run 80..110, never 0.
        assert allowed_start_ranges(make_batch(10, SHORT), MIXED_PLOT) == [(80, 110)]

    def test_upper_bound_is_segment_end_minus_cell_count(self):
        segment = MIXED_PLOT.segments[1]
        lo, hi = allowed_start_ranges(make_batch(7, SHORT), MIXED_PLOT)[0]

        assert lo == segment.start_cell
        assert hi == segment.end_cell - 7
        assert hi + 7 == segment.end_cell  # the last legal run ends ON the border

    def test_batch_exactly_filling_its_segment_has_exactly_one_start(self):
        assert allowed_start_ranges(make_batch(40, SHORT), MIXED_PLOT) == [(80, 80)]

    def test_batch_one_cell_longer_than_its_segment_fits_nowhere(self):
        # The plot has 120 free cells, so an untyped batch of 41 would fit; the
        # bed-type rule is what rules this out.
        assert allowed_start_ranges(make_batch(41, SHORT), MIXED_PLOT) == []
        assert allowed_start_ranges(make_batch(41), MIXED_PLOT) == [(0, 79)]

    def test_bed_type_absent_from_the_plot_fits_nowhere(self):
        assert allowed_start_ranges(make_batch(5, GREENHOUSE), MIXED_PLOT) == []

    def test_plot_without_any_blocks_fits_nothing(self):
        empty = PlotInput(id="plot-empty", name="Fallow", cell_capacity=0)

        assert allowed_start_ranges(make_batch(5, STANDARD), empty) == []
        assert allowed_start_ranges(make_batch(5), empty) == []


class TestSegmentAt:
    """Boundary behaviour of the cell → block lookup."""

    def test_first_cell_of_a_block_belongs_to_it(self):
        assert segment_at(MIXED_PLOT, 0).bed_type_id == STANDARD
        assert segment_at(MIXED_PLOT, 80).bed_type_id == SHORT

    def test_last_cell_of_a_block_belongs_to_it(self):
        assert segment_at(MIXED_PLOT, 79).bed_type_id == STANDARD
        assert segment_at(MIXED_PLOT, 119).bed_type_id == SHORT

    def test_end_cell_is_exclusive(self):
        # end_cell is one PAST the block, so cell 80 is already the next one.
        standard = MIXED_PLOT.segments[0]

        assert standard.end_cell == 80
        assert segment_at(MIXED_PLOT, standard.end_cell).bed_type_id == SHORT

    def test_cell_past_the_plot_has_no_segment(self):
        assert segment_at(MIXED_PLOT, 120) is None

    def test_negative_cell_has_no_segment(self):
        assert segment_at(MIXED_PLOT, -1) is None


# --------------------------------------------------------------------------- #
# Solver-level: the same rule, asserted on what CP-SAT returns
# --------------------------------------------------------------------------- #

# Small enough to solve instantly: 2 standard beds [0, 10) + 2 short beds
# [10, 20), at the default 5 cells per bed.
TINY_PLOT = PlotInput(
    id="plot-tiny",
    name="Home field",
    cell_capacity=20,
    segments=(
        BedSegment(
            bed_type_id=STANDARD,
            bed_type_name="Standard 50 m",
            start_cell=0,
            cell_count=10,
        ),
        BedSegment(
            bed_type_id=SHORT,
            bed_type_name="Short 25 m",
            start_cell=10,
            cell_count=10,
        ),
    ),
)

TEST_SETTINGS = SolverConfig(max_time_seconds=5, workers=1)


def solve(batches: list[BatchInput], plots: list[PlotInput]):
    """Build and solve a tiny model, returning ``(status, solver, variables)``."""
    model, variables = build_model(batches, plots, [], (), TEST_SETTINGS)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TEST_SETTINGS.max_time_seconds
    solver.parameters.num_search_workers = TEST_SETTINGS.workers
    return solver.Solve(model), solver, variables


def placement_of(solver, variables, batch_index: int) -> tuple[int, int]:
    """``(plot index, start cell)`` the solver chose for a batch."""
    for (b, p), present in variables.present.items():
        if b == batch_index and solver.Value(present):
            return p, solver.Value(variables.start[(b, p)])
    raise AssertionError(f"batch {batch_index} was not placed")


class TestSolverHonoursBedTypes:
    def test_typed_batch_lands_inside_its_own_block(self):
        # Only constraint in play is the bed type: one batch, one plot.
        batches = [make_batch(5, SHORT, batch_id="short-batch")]

        status, solver, variables = solve(batches, [TINY_PLOT])

        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        plot_index, start = placement_of(solver, variables, 0)
        segment = TINY_PLOT.segments[1]
        assert plot_index == 0
        assert segment.start_cell <= start
        assert start + 5 <= segment.end_cell

    def test_typed_batch_ignores_free_cells_of_the_wrong_type(self):
        # The short block is fully taken for the same weeks, so the only free
        # cells are standard ones — a solver ignoring bed types would use them.
        batches = [
            make_batch(10, SHORT, batch_id="occupier"),
            make_batch(5, SHORT, batch_id="latecomer"),
        ]

        status, _solver, _variables = solve(batches, [TINY_PLOT])

        assert status == cp_model.INFEASIBLE

    def test_more_demand_than_the_bed_type_offers_is_infeasible(self):
        # Two 10-cell standard batches share the season; the standard block holds
        # exactly one of them, while the plot as a whole has room for both.
        batches = [
            make_batch(10, STANDARD, batch_id="standard-a"),
            make_batch(10, STANDARD, batch_id="standard-b"),
        ]

        status, _solver, _variables = solve(batches, [TINY_PLOT])

        assert status == cp_model.INFEASIBLE

    def test_the_same_two_batches_fit_when_they_are_untyped(self):
        # Control for the test above: without a bed type the identical demand
        # fits, which proves the INFEASIBLE above comes from the bed-type rule
        # and not from the plot simply being too small.
        batches = [
            make_batch(10, batch_id="anywhere-a"),
            make_batch(10, batch_id="anywhere-b"),
        ]

        status, solver, variables = solve(batches, [TINY_PLOT])

        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        starts = sorted(placement_of(solver, variables, b)[1] for b in (0, 1))
        assert starts == [0, 10]

    def test_untyped_batch_uses_the_short_block_when_standard_is_taken(self):
        batches = [
            make_batch(10, STANDARD, batch_id="fills-standard"),
            make_batch(5, batch_id="filler"),
        ]

        status, solver, variables = solve(batches, [TINY_PLOT])

        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        _plot_index, start = placement_of(solver, variables, 1)
        assert start >= TINY_PLOT.segments[1].start_cell

    def test_untyped_batch_uses_the_standard_block_when_short_is_taken(self):
        batches = [
            make_batch(10, SHORT, batch_id="fills-short"),
            make_batch(5, batch_id="filler"),
        ]

        status, solver, variables = solve(batches, [TINY_PLOT])

        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        _plot_index, start = placement_of(solver, variables, 1)
        assert start + 5 <= TINY_PLOT.segments[0].end_cell


class TestBatchThatFitsNowhereIsRejectedAtBuildTime:
    """``batch_plot_options`` raises rather than handing the solver an empty
    domain, so these surface as ``BatchDoesNotFit`` from ``build_model`` — a
    domain error the background job can report, not INFEASIBLE and not a bare
    ValueError."""

    def test_typed_batch_longer_than_every_block_of_its_type(self):
        batches = [make_batch(15, STANDARD, batch_id="too-long")]

        with pytest.raises(BatchDoesNotFit, match="contiguous cells of its bed type"):
            build_model(batches, [TINY_PLOT], [], (), TEST_SETTINGS)

    def test_typed_batch_whose_bed_type_is_nowhere_to_be_found(self):
        batches = [make_batch(5, GREENHOUSE, batch_id="wrong-type")]

        with pytest.raises(BatchDoesNotFit, match="block of that bed type"):
            build_model(batches, [TINY_PLOT], [], (), TEST_SETTINGS)

    def test_untyped_batch_larger_than_the_plot_reports_plain_size(self):
        batches = [make_batch(25, batch_id="huge")]

        with pytest.raises(BatchDoesNotFit, match="no plot is large enough"):
            build_model(batches, [TINY_PLOT], [], (), TEST_SETTINGS)
