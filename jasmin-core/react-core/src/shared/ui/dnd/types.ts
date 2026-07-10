// Shared drag-and-drop grid primitives — a palette of chips dropped into a 2-D
// grid of cells. Used by the delivery-tours planner and (future) the staff
// weekly plan. The kit is domain-free: consumers map their entities
// (stations / employees) to ``DndChip`` and own the placement reducer.

/** Default react-dnd item type shared by chips and cells within one grid. */
export const DND_CHIP_TYPE = "dnd_grid_chip";

/** A cell coordinate. ``row``/``col`` are consumer-defined axes. */
export interface GridPos {
  row: number;
  col: number;
}

/** The draggable/placeable unit. ``id`` identifies the underlying entity so the
 *  consumer can resolve it; ``color`` is an optional stable background tint. */
export interface DndChip {
  id: string;
  label: string;
  color?: string;
}

/** What a drag/keyboard-pick carries. ``from`` is set only when an
 *  already-placed chip is being moved between cells; a chip picked from the
 *  palette omits it. */
export interface DndDragPayload {
  chip: DndChip;
  from?: GridPos;
}
