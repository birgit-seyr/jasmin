import type { KeyboardEvent } from "react";
import { useDrag, useDrop } from "react-dnd";

import { useDndGrid } from "./DndGridContext";
import type { DndChip, DndDragPayload, GridPos } from "./types";

export interface DroppableCellProps {
  pos: GridPos;
  /** The chip currently in this cell, or null when empty. */
  occupant: DndChip | null;
  /** When false the cell is read-only (no drop, drag, keyboard or remove). */
  canEdit?: boolean;
  /** Placeholder text + accessible name for an empty cell. Supply translated. */
  emptyLabel?: string;
  /** Builds the remove button's accessible name from the occupant label.
   *  When omitted the remove button is not rendered. */
  removeAriaLabelFor?: (label: string) => string;
}

/**
 * One grid cell: a drop target that, when filled, is also a drag source (to
 * move/swap) and can be cleared. Keyboard model: with nothing picked up,
 * activating a filled cell picks up its occupant; with something picked up,
 * activating any cell places it there (activating the source cell cancels).
 */
export default function DroppableCell({
  pos,
  occupant,
  canEdit = true,
  emptyLabel,
  removeAriaLabelFor,
}: DroppableCellProps) {
  const { place, remove, selected, select, itemType } = useDndGrid();

  const [{ isOver }, drop] = useDrop<DndDragPayload, void, { isOver: boolean }>(
    () => ({
      accept: itemType,
      canDrop: () => canEdit,
      drop: (item) => place(item, pos),
      collect: (monitor) => ({ isOver: monitor.isOver() }),
    }),
    [pos, place, canEdit, itemType],
  );

  const [{ isDragging }, drag] = useDrag<
    DndDragPayload,
    void,
    { isDragging: boolean }
  >(
    () => ({
      type: itemType,
      item: occupant
        ? { chip: occupant, from: pos }
        : ({} as DndDragPayload),
      canDrag: !!occupant && canEdit,
      collect: (monitor) => ({ isDragging: monitor.isDragging() }),
    }),
    [occupant, pos, canEdit, itemType],
  );

  // A filled cell is both drop target and drag source; an empty one only a target.
  const attachRef = (node: HTMLDivElement | null) => {
    drop(node);
    if (occupant) drag(node);
  };

  const isPickedFromHere =
    selected?.from?.row === pos.row && selected.from.col === pos.col;

  const onActivate = () => {
    if (!canEdit) return;
    if (selected) {
      if (isPickedFromHere) {
        select(null); // activating the source cell cancels the pick-up
      } else {
        place(selected, pos);
      }
      return;
    }
    if (occupant) {
      select({ chip: occupant, from: pos });
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onActivate();
    }
  };

  const className =
    "dnd-cell" +
    (occupant ? " dnd-cell--filled" : " dnd-cell--empty") +
    (isOver ? " dnd-cell--over" : "") +
    (isDragging ? " dnd-cell--dragging" : "") +
    (isPickedFromHere ? " dnd-cell--selected" : "");

  return (
    <div
      ref={attachRef}
      className={className}
      style={occupant?.color ? { backgroundColor: occupant.color } : undefined}
      role="button"
      tabIndex={canEdit ? 0 : -1}
      aria-label={occupant ? occupant.label : emptyLabel}
      onClick={onActivate}
      onKeyDown={onKeyDown}
    >
      {occupant ? (
        <>
          <span className="dnd-cell-label">{occupant.label}</span>
          {remove && canEdit && removeAriaLabelFor ? (
            <button
              type="button"
              className="dnd-cell-remove"
              aria-label={removeAriaLabelFor(occupant.label)}
              onClick={(event) => {
                event.stopPropagation();
                remove(pos);
              }}
            >
              ×
            </button>
          ) : null}
        </>
      ) : (
        <span className="dnd-cell-placeholder">{emptyLabel}</span>
      )}
    </div>
  );
}
