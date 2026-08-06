/**
 * The bed-type gate as the gardener meets it: shading, the reason shown, and —
 * critically — that the keyboard/click route refuses the same cells the pointer
 * route does.
 *
 * That last part is the regression this file exists for. `useDrop.canDrop`
 * guarded the mouse, but the click/Enter handler placed unconditionally, so a
 * cell could render greyed-out with a "wrong bed type" label and still accept
 * the crop when clicked — leaving the accessible path weaker than the pointer
 * one, which is exactly backwards.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CultivationPlot } from "@shared/api/generated/models";
import { DndGrid, DraggableChip } from "@shared/ui";
import PlannerGrids, { type BatchWindow } from "../PlannerGrids";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// 4 beds of "Beet 50m" (cells 0–19) followed by 6 beds of "Beet 25m" (20–49).
const plot = {
  id: "A",
  name: "Plot A",
  cell_capacity: 50,
  is_greenhouse: false,
  bed_segments: [
    {
      bed_type: "bt50",
      bed_type_name: "Beet 50m",
      start_cell: 0,
      cell_count: 20,
    },
    {
      bed_type: "bt25",
      bed_type_name: "Beet 25m",
      start_cell: 20,
      cell_count: 30,
    },
  ],
} as unknown as CultivationPlot;

/** 10 cells wide and sized for the 50 m beds, so its legal starts are 0..10. */
const windows = new Map<string, BatchWindow>([
  [
    "carrots",
    { cellCount: 10, plantingWeek: 20, endWeek: 30, bedTypeId: "bt50" },
  ],
]);

// Cells render bed-major in VISUAL column order, and even beds are not reversed,
// so for the beds used here DOM index == linear cell index.
const LEGAL_START = 0; // inside the 50 m block, run 0..9 stays inside it
const OVERRUN_CELL = 11; // still 50 m beds, but the run would cross into 25 m
const WRONG_TYPE_CELL = 30; // squarely in the 25 m block

function setup(onDropBatch: (b: string, p: string, c: number) => void) {
  return render(
    <DndGrid onPlace={() => undefined}>
      <DraggableChip chip={{ id: "carrots", label: "Carrots" }} />
      <PlannerGrids
        plots={[plot]}
        placements={[]}
        week={20}
        cellsPerBed={5}
        editable
        windows={windows}
        onDropBatch={onDropBatch}
        onSelectPlacement={() => undefined}
      />
    </DndGrid>,
  );
}

/** Pick the chip up the way a keyboard or mouse user does. */
function pickUpChip() {
  fireEvent.click(screen.getByRole("button", { name: /Carrots/ }));
}

describe("bed-type shading", () => {
  it("offers cells where the crop's own block has room", () => {
    setup(vi.fn());
    pickUpChip();

    expect(screen.getAllByRole("gridcell")[LEGAL_START].className).toContain(
      "cultivation-planner__cell--available",
    );
  });

  it("blocks another bed type's cells and names that type", () => {
    setup(vi.fn());
    pickUpChip();

    const cell = screen.getAllByRole("gridcell")[WRONG_TYPE_CELL];
    expect(cell.className).toContain("cultivation-planner__cell--blocked");
    expect(cell.getAttribute("aria-label")).toContain("blocked_wrong_bed_type");
  });

  it("distinguishes overrunning the block from being on the wrong type", () => {
    setup(vi.fn());
    pickUpChip();

    // The crop's OWN type is here — the problem is that the run would not fit
    // before the block ends. Saying "wrong bed type" here would name the very
    // type the gardener asked for.
    const cell = screen.getAllByRole("gridcell")[OVERRUN_CELL];
    expect(cell.className).toContain("cultivation-planner__cell--blocked");
    expect(cell.getAttribute("aria-label")).toContain(
      "blocked_bed_type_overrun",
    );
  });
});

describe("keyboard/click placement honours the same gate as dragging", () => {
  it("refuses a click on a wrong-bed-type cell", () => {
    const onDropBatch = vi.fn();
    setup(onDropBatch);
    pickUpChip();

    fireEvent.click(screen.getAllByRole("gridcell")[WRONG_TYPE_CELL]);

    expect(onDropBatch).not.toHaveBeenCalled();
  });

  it("refuses Enter on a wrong-bed-type cell", () => {
    const onDropBatch = vi.fn();
    setup(onDropBatch);
    fireEvent.keyDown(screen.getByRole("button", { name: /Carrots/ }), {
      key: "Enter",
    });

    fireEvent.keyDown(screen.getAllByRole("gridcell")[WRONG_TYPE_CELL], {
      key: "Enter",
    });

    expect(onDropBatch).not.toHaveBeenCalled();
  });

  it("refuses a cell where the run would overrun the block", () => {
    const onDropBatch = vi.fn();
    setup(onDropBatch);
    pickUpChip();

    fireEvent.click(screen.getAllByRole("gridcell")[OVERRUN_CELL]);

    expect(onDropBatch).not.toHaveBeenCalled();
  });

  it("still places on a legal cell — the gate refuses, it does not disable", () => {
    const onDropBatch = vi.fn();
    setup(onDropBatch);
    pickUpChip();

    fireEvent.click(screen.getAllByRole("gridcell")[LEGAL_START]);

    expect(onDropBatch).toHaveBeenCalledWith("carrots", "A", LEGAL_START);
  });
});
