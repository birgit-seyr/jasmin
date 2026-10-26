import { useMemo } from "react";
import { useDragLayer } from "react-dnd";
import { useTranslation } from "react-i18next";
import type { CultivationPlot } from "@shared/api/generated/models";
import { useDndGrid } from "@shared/ui";
import type { DndDragPayload } from "@shared/ui";
import PlotGrid, { type BlockInfo, type GridPlacement } from "./PlotGrid";
import { occupiesWeek } from "../utils/serpentine";

/** Everything needed to judge a placement: how wide, for which weeks, on what. */
export interface BatchWindow {
  cellCount: number;
  plantingWeek?: number | null;
  endWeek?: number | null;
  /** Bed type the batch was sized for; null/undefined = may go anywhere. */
  bedTypeId?: string | null;
}

interface PlannerGridsProps {
  plots: CultivationPlot[];
  placements: GridPlacement[];
  week: number;
  cellsPerBed: number;
  editable: boolean;
  /** Window + width for every batch, placed or still in the palette. */
  windows: Map<string, BatchWindow>;
  onDropBatch: (batchId: string, plotId: string, startCell: number) => void;
  onSelectPlacement: (placement: GridPlacement) => void;
}

/**
 * The plot grids, plus the drag-time feasibility shading.
 *
 * Why this exists: the grid shows ONE week, but a crop holds its cells for its
 * whole window. A spot that is visibly empty in week 20 can be occupied in week
 * 30, so "drag it wherever it looks free" quietly produces impossible plans —
 * the save endpoint would reject them, which is late and unhelpful feedback.
 *
 * So while a crop is being dragged (or picked up by keyboard) this computes,
 * per plot, every cell that is unavailable at ANY point in that crop's window,
 * and the grids shade legal vs illegal start cells. The drop itself is refused
 * on an illegal cell, so an invalid plan cannot be built by dragging at all.
 *
 * Must render inside `<DndGrid>` — it uses react-dnd's drag monitor.
 */
export default function PlannerGrids({
  plots,
  placements,
  week,
  cellsPerBed,
  editable,
  windows,
  onDropBatch,
  onSelectPlacement,
}: PlannerGridsProps) {
  const { t } = useTranslation();
  const { selected } = useDndGrid();

  // Mouse drag (react-dnd) or keyboard pick-up (the kit's own selection).
  const draggedId = useDragLayer<string | null>((monitor) => {
    if (!monitor.isDragging()) return null;
    const item = monitor.getItem() as DndDragPayload | null;
    return item?.chip?.id ?? null;
  });
  const activeId = draggedId ?? selected?.chip?.id ?? null;
  const activeWindow = activeId ? windows.get(activeId) : undefined;

  // plot id -> cell -> WHY it is unavailable to the dragged crop. Keeping the
  // reason (which crop, and the weeks they collide) is what lets the grid answer
  // "why can't I put it here?" instead of just greying the cell out.
  const blockedByPlot = useMemo(() => {
    const map = new Map<string, Map<number, BlockInfo>>();
    if (!activeId || !activeWindow) return map;
    for (const other of placements) {
      if (other.batchId === activeId) continue; // moving itself frees its own cells
      // Carryover blocks for its stated weeks; a normal crop only where windows meet.
      const clash = overlapWeeks(activeWindow, {
        cellCount: other.cellCount,
        plantingWeek: other.plantingWeek,
        endWeek: other.endWeek,
      });
      if (!clash) continue;
      let cells = map.get(other.plotId);
      if (!cells) {
        cells = new Map<number, BlockInfo>();
        map.set(other.plotId, cells);
      }
      const info: BlockInfo = {
        label: other.label,
        fromWeek: clash[0],
        toWeek: clash[1],
      };
      for (let i = 0; i < other.cellCount; i++) {
        // First writer wins — an earlier-listed crop is as good an explanation
        // as any, and one clear reason beats a list.
        if (!cells.has(other.startCell + i)) {
          cells.set(other.startCell + i, info);
        }
      }
    }
    return map;
  }, [activeId, activeWindow, placements]);

  const EMPTY: ReadonlyMap<number, BlockInfo> = useMemo(
    () => new Map<number, BlockInfo>(),
    [],
  );

  return (
    <>
      {plots.map((plot) => (
        <PlotGrid
          key={plot.id}
          plot={plot}
          placements={placements}
          week={week}
          cellsPerBed={cellsPerBed}
          editable={editable}
          onDropBatch={onDropBatch}
          onSelectPlacement={onSelectPlacement}
          highlightBatchId={activeId}
          blockedForDrag={
            activeWindow
              ? (blockedByPlot.get(plot.id ?? "") ?? EMPTY)
              : undefined
          }
          dragCellCount={activeWindow?.cellCount}
          dragBedTypeId={activeWindow?.bedTypeId}
        />
      ))}
      {activeWindow ? (
        <p className="cultivation-planner__hint">
          {t("cultivation.drag_feasibility_hint")}
        </p>
      ) : null}
    </>
  );
}

/**
 * The weeks two crops would both be in the ground, as `[first, last]`, or null
 * if they never coincide. Week-by-week over 52 weeks: trivial to reason about,
 * and it inherits the grid's own wrap rule for free.
 */
function overlapWeeks(a: BatchWindow, b: BatchWindow): [number, number] | null {
  if (a.plantingWeek == null || b.plantingWeek == null) return [1, 52];
  let first: number | null = null;
  let last: number | null = null;
  for (let w = 1; w <= 52; w++) {
    if (
      occupiesWeek(a.plantingWeek, a.endWeek, w) &&
      occupiesWeek(b.plantingWeek, b.endWeek, w)
    ) {
      if (first === null) first = w;
      last = w;
    }
  }
  return first === null || last === null ? null : [first, last];
}
