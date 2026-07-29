import { Tooltip } from "antd";
import { useMemo } from "react";
import { useDrag, useDrop } from "react-dnd";
import { useTranslation } from "react-i18next";
import { useDndGrid } from "@shared/ui";
import type { DndDragPayload } from "@shared/ui";
import type { CultivationPlot } from "@shared/api/generated/models";
import {
  CELLS_PER_BED,
  bedCount,
  linearIndex,
  occupiesWeek,
} from "../utils/serpentine";

/** A placement rendered on the grid — the fields the grid actually needs. */
export interface GridPlacement {
  batchId: string;
  plotId: string;
  startCell: number;
  cellCount: number;
  label: string;
  color?: string;
  plantingWeek?: number | null;
  endWeek?: number | null;
}

interface PlotGridProps {
  plot: CultivationPlot;
  placements: GridPlacement[];
  /** Only crops occupying this ISO week are drawn. */
  week: number;
  cellsPerBed?: number;
  /** Enables drop targets. Requires an enclosing `<DndGrid>` either way. */
  editable?: boolean;
  /** Called when a batch is dropped/placed on a cell (that cell becomes its
   *  FIRST cell). Carries the plot because `GridPos` cannot express it. */
  onDropBatch?: (batchId: string, plotId: string, startCell: number) => void;
  /** Clicking an occupied cell — used to pick a crop back up / inspect it. */
  onSelectPlacement?: (placement: GridPlacement) => void;
  highlightBatchId?: string | null;
}

/**
 * One plot drawn as rows of beds × cells.
 *
 * The stored coordinate is a linear serpentine index; here it is laid out
 * physically, so bed 0 reads left→right, bed 1 right→left — the tractor's path.
 * A crop is drawn only in the weeks it actually occupies its cells, so the week
 * selector turns the grid into "what is in the ground right now".
 *
 * Cells are individual drop targets: dropping a batch sets its FIRST cell and it
 * then covers `cellCount` consecutive cells. The shared dnd kit has no spanning
 * concept, so the span lives in our placement state and the covered cells render
 * as one continuous run — this component funnels into the same
 * `useDndGrid()` contract the kit exposes for exactly that purpose.
 *
 * NOTE: always render inside `<DndGrid>` (even read-only) — `useDndGrid()`
 * throws without a provider.
 */
export default function PlotGrid({
  plot,
  placements,
  week,
  cellsPerBed = CELLS_PER_BED,
  editable = false,
  onDropBatch,
  onSelectPlacement,
  highlightBatchId = null,
}: PlotGridProps) {
  const { t } = useTranslation();
  const capacity = plot.cell_capacity ?? 0;
  const beds = bedCount(capacity, cellsPerBed);

  // linear cell index -> the placement occupying it in `week`
  const occupancy = useMemo(() => {
    const map = new Map<number, GridPlacement>();
    for (const placement of placements) {
      if (placement.plotId !== plot.id) continue;
      if (!occupiesWeek(placement.plantingWeek, placement.endWeek, week)) continue;
      for (let i = 0; i < placement.cellCount; i++) {
        map.set(placement.startCell + i, placement);
      }
    }
    return map;
  }, [placements, plot.id, week]);

  if (beds === 0) {
    return (
      <div className="cultivation-planner__plot">
        <div className="cultivation-planner__plot-title">
          {plot.name || plot.id}
        </div>
        <p className="cultivation-planner__empty">
          {t("cultivation.plot_has_no_beds")}
        </p>
      </div>
    );
  }

  return (
    <div className="cultivation-planner__plot">
      <div className="cultivation-planner__plot-title">
        {plot.name || plot.id}
        <span className="cultivation-planner__plot-meta">
          {t("cultivation.beds_and_cells", { beds, cells: capacity })}
        </span>
      </div>
      <div
        className="cultivation-planner__grid"
        style={{
          gridTemplateColumns: `2.5em repeat(${cellsPerBed}, minmax(2.4em, 1fr))`,
        }}
        role="grid"
        aria-label={t("cultivation.plot_grid_label", {
          plot: plot.name || plot.id,
          week,
        })}
      >
        {Array.from({ length: beds }, (_, bed) => (
          <div key={bed} className="cultivation-planner__row" role="row">
            <div className="cultivation-planner__bed-label" role="rowheader">
              {bed + 1}
            </div>
            {Array.from({ length: cellsPerBed }, (_, column) => {
              const cell = linearIndex(bed, column, cellsPerBed);
              const occupant = occupancy.get(cell);
              const previous = occupancy.get(cell - 1);
              // Continuation cells drop the label so a multi-cell crop reads as
              // one block instead of a repeated name.
              const isRunStart =
                !!occupant && previous?.batchId !== occupant.batchId;
              return (
                <PlannerCell
                  key={cell}
                  cell={cell}
                  plotId={plot.id ?? ""}
                  occupant={occupant}
                  showLabel={isRunStart}
                  editable={editable}
                  highlighted={
                    !!occupant &&
                    !!highlightBatchId &&
                    occupant.batchId === highlightBatchId
                  }
                  emptyLabel={t("cultivation.empty_cell", { cell: cell + 1 })}
                  onDropBatch={onDropBatch}
                  onSelectPlacement={onSelectPlacement}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

interface PlannerCellProps {
  cell: number;
  plotId: string;
  occupant?: GridPlacement;
  showLabel: boolean;
  editable: boolean;
  highlighted: boolean;
  emptyLabel: string;
  onDropBatch?: (batchId: string, plotId: string, startCell: number) => void;
  onSelectPlacement?: (placement: GridPlacement) => void;
}

function PlannerCell({
  cell,
  plotId,
  occupant,
  showLabel,
  editable,
  highlighted,
  emptyLabel,
  onDropBatch,
  onSelectPlacement,
}: PlannerCellProps) {
  const { itemType, selected } = useDndGrid();

  const [{ isOver }, drop] = useDrop<DndDragPayload, void, { isOver: boolean }>(
    () => ({
      accept: itemType,
      canDrop: () => editable,
      drop: (item) => onDropBatch?.(item.chip.id, plotId, cell),
      collect: (monitor) => ({ isOver: monitor.isOver() && monitor.canDrop() }),
    }),
    [itemType, editable, onDropBatch, plotId, cell],
  );

  // A placed crop is itself draggable, so it can be moved straight to a new
  // cell without being parked in the palette first.
  const [{ isDragging }, drag] = useDrag<
    DndDragPayload,
    void,
    { isDragging: boolean }
  >(
    () => ({
      type: itemType,
      canDrag: () => editable && !!occupant,
      item: {
        chip: {
          id: occupant?.batchId ?? "",
          label: occupant?.label ?? "",
          color: occupant?.color,
        },
      },
      collect: (monitor) => ({ isDragging: monitor.isDragging() }),
    }),
    [itemType, editable, occupant],
  );

  const attachRefs = (node: HTMLDivElement | null) => {
    drop(node);
    if (occupant) drag(node);
  };

  const handleActivate = () => {
    if (!editable) return;
    // Keyboard / click path: a chip "picked up" in the palette lands here.
    if (selected) {
      onDropBatch?.(selected.chip.id, plotId, cell);
      return;
    }
    if (occupant) onSelectPlacement?.(occupant);
  };

  const classes = [
    "cultivation-planner__cell",
    occupant
      ? "cultivation-planner__cell--filled"
      : "cultivation-planner__cell--empty",
    highlighted ? "cultivation-planner__cell--highlighted" : "",
    isOver ? "cultivation-planner__cell--over" : "",
    isDragging ? "cultivation-planner__cell--dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const cellNode = (
    <div
      ref={attachRefs}
      className={classes}
      style={occupant?.color ? { backgroundColor: occupant.color } : undefined}
      role="gridcell"
      aria-label={occupant ? occupant.label : emptyLabel}
      tabIndex={editable ? 0 : -1}
      onClick={handleActivate}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleActivate();
        }
      }}
    >
      {showLabel && occupant ? (
        <span className="cultivation-planner__cell-label">{occupant.label}</span>
      ) : null}
    </div>
  );

  return occupant ? (
    <Tooltip title={occupant.label}>{cellNode}</Tooltip>
  ) : (
    cellNode
  );
}
