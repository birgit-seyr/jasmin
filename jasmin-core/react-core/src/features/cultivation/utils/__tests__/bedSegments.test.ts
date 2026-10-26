/**
 * Parity tests for the bed-type geometry.
 *
 * These deliberately mirror the backend suite
 * (`apps/cultivation/tests/tests_optimizer/test_bed_types.py`) case for case and
 * number for number. The two implementations exist because the grid has to grey
 * out illegal cells *before* a drop while `save_placements` is the authority
 * *after* one — and if they ever disagree, the UI either offers drops the server
 * rejects or hides drops the server would accept. Same plot, same expectations,
 * both sides.
 */

import { describe, expect, it } from "vitest";
import type { BedSegment } from "@shared/api/generated/models";
import {
  allowedStartRanges,
  segmentBedCount,
  segmentForCell,
  segmentStartBed,
  startAllowed,
} from "../bedSegments";

const STANDARD = "bedtype-standard";
const SHORT = "bedtype-short";
const ABSENT = "bedtype-greenhouse";

/** Standard beds occupy cells [0, 80), short beds [80, 120). */
const SEGMENTS: BedSegment[] = [
  {
    bed_type: STANDARD,
    bed_type_name: "Standard 50 m",
    start_cell: 0,
    cell_count: 80,
  },
  {
    bed_type: SHORT,
    bed_type_name: "Short 25 m",
    start_cell: 80,
    cell_count: 40,
  },
];
const CAPACITY = 120;

describe("allowedStartRanges — no bed type (the unconstrained branch)", () => {
  it("may start anywhere it still fits", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, null, 10)).toEqual([
      [0, 110],
    ]);
  });

  it("treats undefined the same as null", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, undefined, 10)).toEqual([
      [0, 110],
    ]);
  });

  it("exactly filling the plot leaves one start", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, null, 120)).toEqual([[0, 0]]);
  });

  it("one cell too big fits nowhere", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, null, 121)).toEqual([]);
  });

  it("a zero-cell batch fits nowhere", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, null, 0)).toEqual([]);
    expect(allowedStartRanges(SEGMENTS, CAPACITY, STANDARD, 0)).toEqual([]);
  });
});

describe("allowedStartRanges — typed (the branch a null FK never reaches)", () => {
  it("stops short of the block boundary so the run cannot spill over", () => {
    // 80 - 10: starting at 71 would put cells 71..80 partly on short beds.
    expect(allowedStartRanges(SEGMENTS, CAPACITY, STANDARD, 10)).toEqual([
      [0, 70],
    ]);
  });

  it("starts at the block, not at cell 0", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, SHORT, 10)).toEqual([
      [80, 110],
    ]);
  });

  it("a batch exactly filling its block has exactly one start", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, SHORT, 40)).toEqual([
      [80, 80],
    ]);
  });

  it("one cell longer than its block fits nowhere — though it fits the plot", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, SHORT, 41)).toEqual([]);
    // The control: the same size is placeable when the bed type is unset, so
    // the empty result above is the bed-type rule and not plot size.
    expect(allowedStartRanges(SEGMENTS, CAPACITY, null, 41)).toEqual([[0, 79]]);
  });

  it("a bed type absent from the plot fits nowhere", () => {
    expect(allowedStartRanges(SEGMENTS, CAPACITY, ABSENT, 1)).toEqual([]);
  });

  it("a plot with no blocks at all fits nothing typed", () => {
    expect(allowedStartRanges([], CAPACITY, STANDARD, 1)).toEqual([]);
  });
});

describe("startAllowed", () => {
  it("accepts the bounds inclusively and rejects just outside them", () => {
    const ranges = allowedStartRanges(SEGMENTS, CAPACITY, STANDARD, 10);
    expect(startAllowed(ranges, 0)).toBe(true);
    expect(startAllowed(ranges, 70)).toBe(true);
    expect(startAllowed(ranges, 71)).toBe(false);
    expect(startAllowed(ranges, -1)).toBe(false);
  });

  it("rejects everything when there are no ranges", () => {
    expect(startAllowed([], 0)).toBe(false);
  });
});

describe("segmentForCell", () => {
  it("resolves the boundary cells to the right block", () => {
    expect(segmentForCell(SEGMENTS, 0)?.bed_type).toBe(STANDARD);
    expect(segmentForCell(SEGMENTS, 79)?.bed_type).toBe(STANDARD);
    // 80 is the FIRST short cell — end_cell is exclusive.
    expect(segmentForCell(SEGMENTS, 80)?.bed_type).toBe(SHORT);
    expect(segmentForCell(SEGMENTS, 119)?.bed_type).toBe(SHORT);
  });

  it("returns undefined outside the plot", () => {
    expect(segmentForCell(SEGMENTS, 120)).toBeUndefined();
    expect(segmentForCell(SEGMENTS, -1)).toBeUndefined();
  });
});

describe("segment geometry in beds", () => {
  it("maps blocks onto the bed rows the grid draws", () => {
    expect(segmentStartBed(SEGMENTS[0], 5)).toBe(0);
    expect(segmentBedCount(SEGMENTS[0], 5)).toBe(16);
    expect(segmentStartBed(SEGMENTS[1], 5)).toBe(16);
    expect(segmentBedCount(SEGMENTS[1], 5)).toBe(8);
  });
});
