/**
 * Bed-type blocks — the TS mirror of the backend's
 * `apps/cultivation/optimizer/loading.py` (`BedSegment`, `allowed_start_ranges`).
 *
 * A plot's beds are grouped into blocks of one bed type, laid out along the
 * plot's existing cell axis in `PlotContent.position` order. A batch's
 * `amount_of_beds` counts beds of ITS bed type, so the same number of beds is a
 * different area on a different type — which is why a typed batch has to sit
 * wholly inside one block rather than merely somewhere in the plot.
 *
 * Keep this in step with the Python: the grid uses it to decide what to grey out
 * while dragging, and `save_placements` re-checks the same rule server-side. The
 * two disagreeing means a drop the UI allowed comes back as an error.
 */

import type { BedSegment } from "@shared/api/generated/models";

/** The block containing `cell`, or undefined when the cell is out of range. */
export function segmentForCell(
  segments: readonly BedSegment[],
  cell: number,
): BedSegment | undefined {
  return segments.find(
    (segment) =>
      cell >= segment.start_cell &&
      cell < segment.start_cell + segment.cell_count,
  );
}

/**
 * Inclusive `[lo, hi]` start cells at which a batch may begin in this plot.
 * Empty means it cannot go here at all.
 *
 * With no `bedTypeId` the batch is unconstrained and may start anywhere it fits.
 * Requiring the whole run inside one block falls out of the bounds — no separate
 * "does it straddle?" check is needed.
 */
export function allowedStartRanges(
  segments: readonly BedSegment[],
  capacity: number,
  bedTypeId: string | null | undefined,
  cellCount: number,
): Array<[number, number]> {
  if (cellCount <= 0) return [];
  if (bedTypeId == null) {
    return cellCount > capacity ? [] : [[0, capacity - cellCount]];
  }
  return segments
    .filter(
      (segment) =>
        segment.bed_type === bedTypeId && segment.cell_count >= cellCount,
    )
    .map(
      (segment) =>
        [
          segment.start_cell,
          segment.start_cell + segment.cell_count - cellCount,
        ] as [number, number],
    );
}

/** Does `cell` sit in one of the ranges {@link allowedStartRanges} returned? */
export function startAllowed(
  ranges: ReadonlyArray<readonly [number, number]>,
  cell: number,
): boolean {
  return ranges.some(([lo, hi]) => cell >= lo && cell <= hi);
}

/** The bed index a segment begins at, for drawing its band in the grid. */
export function segmentStartBed(
  segment: BedSegment,
  cellsPerBed: number,
): number {
  return Math.floor(segment.start_cell / cellsPerBed);
}

/** How many beds a segment covers. */
export function segmentBedCount(
  segment: BedSegment,
  cellsPerBed: number,
): number {
  return Math.floor(segment.cell_count / cellsPerBed);
}
