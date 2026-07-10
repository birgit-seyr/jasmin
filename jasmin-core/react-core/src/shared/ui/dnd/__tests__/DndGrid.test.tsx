import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import DndGrid from "../DndGrid";
import DraggableChip from "../DraggableChip";
import DroppableCell from "../DroppableCell";
import type { DndChip } from "../types";
import { pastelColorForIndex, PASTEL_PALETTE } from "../usePastelColorMap";

const CHIP: DndChip = { id: "s1", label: "Station 1" };

function renderGrid({
  onPlace = vi.fn(),
  onRemove = vi.fn(),
  cell0 = null as DndChip | null,
  cell1 = null as DndChip | null,
  withPalette = true,
}: {
  onPlace?: Mock;
  onRemove?: Mock;
  cell0?: DndChip | null;
  cell1?: DndChip | null;
  withPalette?: boolean;
} = {}) {
  render(
    <DndGrid onPlace={onPlace} onRemove={onRemove}>
      {withPalette ? <DraggableChip chip={CHIP} /> : null}
      <DroppableCell
        pos={{ row: 0, col: 0 }}
        occupant={cell0}
        emptyLabel="empty-0"
        removeAriaLabelFor={(label) => `remove ${label}`}
      />
      <DroppableCell
        pos={{ row: 0, col: 1 }}
        occupant={cell1}
        emptyLabel="empty-1"
        removeAriaLabelFor={(label) => `remove ${label}`}
      />
    </DndGrid>,
  );
  return { onPlace, onRemove };
}

describe("DnD grid — click/keyboard placement", () => {
  it("selects a palette chip then places it into an empty cell", async () => {
    const user = userEvent.setup();
    const { onPlace } = renderGrid();

    await user.click(screen.getByRole("button", { name: "Station 1" }));
    await user.click(screen.getByRole("button", { name: "empty-0" }));

    expect(onPlace).toHaveBeenCalledTimes(1);
    const [payload, to] = onPlace.mock.calls[0];
    expect(payload.chip.id).toBe("s1");
    expect(payload.from).toBeUndefined(); // came from the palette
    expect(to).toEqual({ row: 0, col: 0 });
  });

  it("picks up a filled cell's occupant and moves it to another cell", async () => {
    const user = userEvent.setup();
    // No palette chip so "Station 1" unambiguously refers to the filled cell.
    const { onPlace } = renderGrid({ cell0: CHIP, withPalette: false });

    await user.click(screen.getByRole("button", { name: "Station 1" }));
    await user.click(screen.getByRole("button", { name: "empty-1" }));

    expect(onPlace).toHaveBeenCalledTimes(1);
    const [payload, to] = onPlace.mock.calls[0];
    expect(payload.chip.id).toBe("s1");
    expect(payload.from).toEqual({ row: 0, col: 0 }); // a move, not a palette drop
    expect(to).toEqual({ row: 0, col: 1 });
  });

  it("cancels the pick-up when the source cell is activated again", async () => {
    const user = userEvent.setup();
    const { onPlace } = renderGrid({ cell0: CHIP, withPalette: false });

    const filled = screen.getByRole("button", { name: "Station 1" });
    await user.click(filled); // pick up
    await user.click(filled); // activate source again -> cancel

    expect(onPlace).not.toHaveBeenCalled();
  });

  it("removes an occupant via the remove button without selecting it", async () => {
    const user = userEvent.setup();
    const { onRemove, onPlace } = renderGrid({ cell0: CHIP, withPalette: false });

    await user.click(screen.getByRole("button", { name: "remove Station 1" }));

    expect(onRemove).toHaveBeenCalledWith({ row: 0, col: 0 });
    expect(onPlace).not.toHaveBeenCalled(); // stopPropagation kept the cell inert
  });

  it("supports keyboard placement (Enter to select, Enter to place)", () => {
    const { onPlace } = renderGrid();

    fireEvent.keyDown(screen.getByRole("button", { name: "Station 1" }), {
      key: "Enter",
    });
    fireEvent.keyDown(screen.getByRole("button", { name: "empty-1" }), {
      key: "Enter",
    });

    expect(onPlace).toHaveBeenCalledTimes(1);
    const [payload, to] = onPlace.mock.calls[0];
    expect(payload.chip.id).toBe("s1");
    expect(to).toEqual({ row: 0, col: 1 });
  });

  it("does not allow editing a read-only cell", async () => {
    const user = userEvent.setup();
    const onPlace = vi.fn();
    render(
      <DndGrid onPlace={onPlace}>
        <DraggableChip chip={CHIP} />
        <DroppableCell
          pos={{ row: 0, col: 0 }}
          occupant={null}
          canEdit={false}
          emptyLabel="empty-0"
        />
      </DndGrid>,
    );

    await user.click(screen.getByRole("button", { name: "Station 1" }));
    await user.click(screen.getByRole("button", { name: "empty-0" }));

    expect(onPlace).not.toHaveBeenCalled();
  });
});

describe("pastelColorForIndex", () => {
  it("cycles through the palette", () => {
    expect(pastelColorForIndex(0)).toBe(PASTEL_PALETTE[0]);
    expect(pastelColorForIndex(PASTEL_PALETTE.length)).toBe(PASTEL_PALETTE[0]);
    expect(pastelColorForIndex(PASTEL_PALETTE.length + 1)).toBe(PASTEL_PALETTE[1]);
  });
});
