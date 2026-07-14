import type { CSSProperties, KeyboardEvent } from "react";
import { useDrag } from "react-dnd";

import { useDndGrid } from "./DndGridContext";
import type { DndChip } from "./types";

export interface DraggableChipProps {
  chip: DndChip;
  canDrag?: boolean;
  /** Extra context appended to the chip's accessible name (e.g. a "press Enter
   *  to select" hint). Supply already-translated text. */
  ariaHint?: string;
  /** Optional small trailing count badge (e.g. how many times this chip is in
   *  use). Purely visual — convey its meaning to assistive tech via ``ariaHint``. */
  count?: number;
}

/**
 * A palette chip: draggable with the mouse and selectable with click / Enter /
 * Space for keyboard users. Selecting a chip then activating a cell places it
 * there (handled by {@link DroppableCell} via the grid context).
 */
export default function DraggableChip({
  chip,
  canDrag = true,
  ariaHint,
  count,
}: DraggableChipProps) {
  const { selected, select, itemType } = useDndGrid();
  // "Selected from the palette" = same chip, no source cell.
  const isSelected = selected?.chip.id === chip.id && !selected.from;

  const [{ isDragging }, drag] = useDrag<
    { chip: DndChip },
    void,
    { isDragging: boolean }
  >(
    () => ({
      type: itemType,
      item: { chip },
      canDrag,
      collect: (monitor) => ({ isDragging: monitor.isDragging() }),
    }),
    [chip, canDrag, itemType],
  );

  const style: CSSProperties | undefined = chip.color
    ? { backgroundColor: chip.color }
    : undefined;

  const toggleSelect = () => {
    if (!canDrag) return;
    select(isSelected ? null : { chip });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleSelect();
    }
  };

  return (
    <div
      ref={(node) => {
        drag(node);
      }}
      className={
        "dnd-chip" +
        (isDragging ? " dnd-chip--dragging" : "") +
        (isSelected ? " dnd-chip--selected" : "")
      }
      style={style}
      role="button"
      tabIndex={canDrag ? 0 : -1}
      aria-pressed={isSelected}
      aria-label={ariaHint ? `${chip.label}. ${ariaHint}` : chip.label}
      onClick={toggleSelect}
      onKeyDown={onKeyDown}
    >
      <span className="dnd-chip-label">{chip.label}</span>
      {count !== undefined && (
        <span className="dnd-chip-count" aria-hidden="true">
          {count}
        </span>
      )}
    </div>
  );
}
