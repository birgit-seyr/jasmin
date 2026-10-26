/**
 * Serpentine (boustrophedon) cell geometry — the TS mirror of the backend's
 * `apps/cultivation/optimizer/serpentine.py`.
 *
 * The solver works in a plain linear cell index per plot. Physically the tractor
 * drives one bed to its end, then the next bed back-to-front, so consecutive
 * linear cells follow the tractor path: even beds run left→right, odd beds
 * right→left. Only the display needs to know that.
 */

/** How many optimizer cells make up one gardener's bed (backend CELLS_PER_BED). */
export const CELLS_PER_BED = 5;

/** Linear (serpentine) index → `{ bed, column }` where `column` is the visual
 *  left-to-right position inside the bed. */
export function physicalCell(
  linearIndex: number,
  cellsPerBed: number = CELLS_PER_BED,
): { bed: number; column: number } {
  const bed = Math.floor(linearIndex / cellsPerBed);
  const offset = linearIndex % cellsPerBed;
  return { bed, column: bed % 2 === 1 ? cellsPerBed - 1 - offset : offset };
}

/** Inverse of {@link physicalCell}: visual `{bed, column}` → linear index. */
export function linearIndex(
  bed: number,
  column: number,
  cellsPerBed: number = CELLS_PER_BED,
): number {
  const offset = bed % 2 === 1 ? cellsPerBed - 1 - column : column;
  return bed * cellsPerBed + offset;
}

/** Beds a plot holds, given its total cell capacity. */
export function bedCount(
  cellCapacity: number,
  cellsPerBed: number = CELLS_PER_BED,
): number {
  return Math.floor(cellCapacity / cellsPerBed);
}

/**
 * Does a batch occupy its cells during `week` **of its own planning year**?
 *
 * `endWeek < plantingWeek` means the crop overwinters. Within THIS year's plan it
 * holds the ground only from `plantingWeek` to the end of the year — the
 * `[1..endWeek]` tail belongs to the NEXT year, where it is handled as carryover.
 *
 * Wrapping it back into the same year is wrong and visibly so: garlic planted in
 * KW43 would be drawn on top of the peas that legitimately occupied those cells
 * in KW13-26, making a valid succession look like two crops in one bed. (The
 * solver never had this problem — it unwraps onto an absolute axis, where
 * [13,27) and [43,79) plainly do not overlap.)
 */
export function occupiesWeek(
  plantingWeek: number | null | undefined,
  endWeek: number | null | undefined,
  week: number,
): boolean {
  if (plantingWeek == null || endWeek == null) return false;
  if (endWeek >= plantingWeek) return week >= plantingWeek && week <= endWeek;
  return week >= plantingWeek;
}
