import type { ReactNode } from "react";
import { useCallback, useMemo, useState } from "react";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";

import { DndGridContext } from "./DndGridContext";
import type { DndDragPayload, GridPos } from "./types";
import { DND_CHIP_TYPE } from "./types";

export interface DndGridProps {
  /** Commit a placement. ``payload.from`` set = move between cells; unset =
   *  placed from the palette. The consumer owns the grid state / reducer. */
  onPlace: (payload: DndDragPayload, to: GridPos) => void;
  /** Optional cell-clear handler; enables the remove affordance on filled cells. */
  onRemove?: (pos: GridPos) => void;
  /** Override the react-dnd item type (only needed if two grids coexist). */
  itemType?: string;
  children: ReactNode;
}

/**
 * Provides a drag-and-drop grid: the react-dnd HTML5 backend for mouse users
 * AND a keyboard/click "pick up then place" fallback, both funnelling into the
 * same ``onPlace``/``onRemove``. Render {@link DraggableChip}s in a palette and
 * {@link DroppableCell}s in the grid inside this provider — consumers never
 * import react-dnd directly.
 */
export default function DndGrid({
  onPlace,
  onRemove,
  itemType = DND_CHIP_TYPE,
  children,
}: DndGridProps) {
  const [selected, setSelected] = useState<DndDragPayload | null>(null);

  const place = useCallback(
    (payload: DndDragPayload, to: GridPos) => {
      onPlace(payload, to);
      setSelected(null); // a placement always ends the keyboard "pick up"
    },
    [onPlace],
  );

  const value = useMemo(
    () => ({ place, remove: onRemove, itemType, selected, select: setSelected }),
    [place, onRemove, itemType, selected],
  );

  return (
    <DndProvider backend={HTML5Backend}>
      <DndGridContext.Provider value={value}>
        {children}
      </DndGridContext.Provider>
    </DndProvider>
  );
}
