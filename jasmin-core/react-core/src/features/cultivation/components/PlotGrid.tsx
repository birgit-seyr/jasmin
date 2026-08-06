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
import {
  allowedStartRanges,
  segmentBedCount,
  segmentForCell,
  segmentStartBed,
  startAllowed,
} from "../utils/bedSegments";

/** Why a cell is unavailable to the crop being dragged. */
export interface BlockInfo {
  /** The crop in the way. */
  label: string;
  /** The weeks the two crops would both be in the ground. */
  fromWeek: number;
  toWeek: number;
}

/**
 * Why the dragged crop cannot START on a given cell.
 *
 * The three bed-type cases mirror the server's (`_check_bed_type`) so the grid
 * and the save endpoint explain a refusal the same way. Telling them apart
 * matters: "these are 25 m beds" and "your crop would run off the end of the
 * 50 m block" are different problems with different fixes, and collapsing them
 * produces the nonsense of naming the crop's own, correct bed type as the reason.
 */
type StartBlocker =
  | { kind: "occupied"; info: BlockInfo }
  /** The run would pass the end of the plot. */
  | { kind: "capacity" }
  /** These are not the beds the crop was sized for. */
  | { kind: "bed_type"; bedTypeName: string }
  /** Right block, but the run would cross out of it into the next one. */
  | { kind: "bed_type_overrun" }
  /** No block of the crop's own type in this plot is long enough. */
  | { kind: "bed_type_none" };

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
  /** Ground held by LAST year's overwintering crop: shown, but not editable —
   *  it belongs to the previous plan, and the solver treated it as occupied. */
  isCarryover?: boolean;
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
  /**
   * Cells in THIS plot that the crop currently being dragged may not use,
   * because something occupies them at some point during that crop's week
   * window — not necessarily the week on screen. Empty when nothing is being
   * dragged.
   */
  blockedForDrag?: ReadonlyMap<number, BlockInfo>;
  /** Cell width of the crop being dragged, so a start cell can be judged. */
  dragCellCount?: number;
  /**
   * Bed type the dragged crop was sized for, or null when it has none and may
   * go anywhere. `amount_of_beds` counts beds of THIS type, so dropping it on
   * another type would silently give it a different area.
   */
  dragBedTypeId?: string | null;
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
  blockedForDrag,
  dragCellCount,
  dragBedTypeId,
}: PlotGridProps) {
  const { t } = useTranslation();
  const capacity = plot.cell_capacity ?? 0;
  const beds = bedCount(capacity, cellsPerBed);
  const segments = useMemo(() => plot.bed_segments ?? [], [plot.bed_segments]);

  // Where the dragged crop's bed type lets it begin. Computed once per drag
  // rather than per cell — a plot can be hundreds of cells.
  const bedTypeStarts = useMemo(
    () =>
      dragCellCount == null
        ? []
        : allowedStartRanges(segments, capacity, dragBedTypeId, dragCellCount),
    [segments, capacity, dragBedTypeId, dragCellCount],
  );

  /**
   * Why can the dragged crop NOT start here? `null` means it can.
   *
   * It must fit inside the plot, land on beds of its own type, AND have every
   * cell of its run free for its whole week window — a spot that looks empty in
   * the displayed week can be taken in week 30, and dropping there would build
   * an impossible plan. The first obstacle found is returned so the cell can
   * explain itself instead of just going grey.
   */
  const startBlocker = (cell: number): StartBlocker | null => {
    if (!blockedForDrag || dragCellCount == null) return null;
    if (cell + dragCellCount > capacity) return { kind: "capacity" };
    if (dragBedTypeId != null && !startAllowed(bedTypeStarts, cell)) {
      if (bedTypeStarts.length === 0) return { kind: "bed_type_none" };
      const here = segmentForCell(segments, cell);
      // Standing in the right block already means the run, not the spot, is the
      // problem — it would cross out into the next block.
      if (here?.bed_type === dragBedTypeId) return { kind: "bed_type_overrun" };
      return { kind: "bed_type", bedTypeName: here?.bed_type_name ?? "" };
    }
    for (let i = 0; i < dragCellCount; i++) {
      const info = blockedForDrag.get(cell + i);
      if (info) return { kind: "occupied", info };
    }
    return null;
  };
  const dragging = !!blockedForDrag && dragCellCount != null;

  // A plot with one bed type needs no bands — the type belongs in the header.
  // With several, each block is announced where it starts.
  const bandByBed = useMemo(() => {
    const map = new Map<number, { name: string; beds: number }>();
    if (segments.length < 2) return map;
    for (const segment of segments) {
      map.set(segmentStartBed(segment, cellsPerBed), {
        name: segment.bed_type_name,
        beds: segmentBedCount(segment, cellsPerBed),
      });
    }
    return map;
  }, [segments, cellsPerBed]);

  // Bed type per bed row, for the row headers' accessible names. Only worth
  // saying when the plot actually mixes types.
  const bedTypeByBed = useMemo(() => {
    const map = new Map<number, string>();
    if (segments.length < 2) return map;
    for (const segment of segments) {
      const first = segmentStartBed(segment, cellsPerBed);
      for (let i = 0; i < segmentBedCount(segment, cellsPerBed); i++) {
        map.set(first + i, segment.bed_type_name);
      }
    }
    return map;
  }, [segments, cellsPerBed]);

  // linear cell index -> the placement occupying it in `week`
  const occupancy = useMemo(() => {
    const map = new Map<number, GridPlacement>();
    for (const placement of placements) {
      if (placement.plotId !== plot.id) continue;
      if (!occupiesWeek(placement.plantingWeek, placement.endWeek, week))
        continue;
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
          {segments.length === 1 ? ` · ${segments[0].bed_type_name}` : ""}
        </span>
      </div>
      <div
        className="cultivation-planner__grid"
        style={{
          // Fixed tracks, not minmax(...,1fr): the grid is width:max-content, so
          // a flexible track still sizes to its content and one long crop name
          // made its column wider than the rest of the bed. Every cell is the
          // same width now; the name overflows across its own crop's cells.
          // Only the repeat COUNT has to be inline — the width itself is a CSS
          // variable, so it stays tunable from the stylesheet.
          gridTemplateColumns: `2.5em repeat(${cellsPerBed}, var(--cultivation-cell-width))`,
        }}
        role="grid"
        aria-label={t("cultivation.plot_grid_label", {
          plot: plot.name || plot.id,
          week,
        })}
      >
        {Array.from({ length: beds }, (_, bed) => {
          const band = bandByBed.get(bed);
          return (
            <div key={bed} className="cultivation-planner__row" role="row">
              {/* `__row` is display:contents, so this lands directly in the grid
                and can span it — a banner naming the block of beds below. */}
              {band ? (
                // Decorative: a text node inside role="row" would be announced as
                // stray row content. Screen readers get the bed type from each
                // row's header instead, where it is more useful anyway.
                <div
                  className={
                    "cultivation-planner__band" +
                    (bed === 0 ? " cultivation-planner__band--first" : "")
                  }
                  aria-hidden="true"
                >
                  {t("cultivation.bed_type_band", {
                    bedType: band.name,
                    count: band.beds,
                  })}
                </div>
              ) : null}
              <div
                className="cultivation-planner__bed-label"
                role="rowheader"
                aria-label={
                  bedTypeByBed.get(bed)
                    ? t("cultivation.bed_label_with_type", {
                        bed: bed + 1,
                        bedType: bedTypeByBed.get(bed),
                      })
                    : undefined
                }
              >
                {bed + 1}
              </div>
              {Array.from({ length: cellsPerBed }, (_, column) => {
                const cell = linearIndex(bed, column, cellsPerBed);
                const occupant = occupancy.get(cell);
                // Compare against the previous VISUAL column, not the previous
                // linear cell: odd beds are drawn right-to-left, so a linear
                // comparison puts the label in the middle of a reversed row (or
                // drops it entirely on the next bed), which made a 9-cell crop
                // look like one labelled cell and eight blank ones.
                const previous =
                  column > 0
                    ? occupancy.get(linearIndex(bed, column - 1, cellsPerBed))
                    : undefined;
                // Label the leftmost cell of each run within this bed row, so a
                // crop spanning two beds is named on both.
                const isRunStart =
                  !!occupant && previous?.batchId !== occupant.batchId;
                const blocker = startBlocker(cell);
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
                    dragging={dragging}
                    validTarget={blocker === null}
                    blockReason={describeBlocker(blocker, dragCellCount, t)}
                  />
                );
              })}
            </div>
          );
        })}
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
  /** A drag is in progress, so target validity is worth showing. */
  dragging: boolean;
  /** The dragged crop's whole run fits here, free for its whole week window. */
  validTarget: boolean;
  /** Already-translated explanation shown while dragging over a blocked cell. */
  blockReason?: string;
}

/** The blocker as a sentence a gardener can act on, or undefined if unblocked. */
function describeBlocker(
  blocker: StartBlocker | null,
  dragCellCount: number | undefined,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | undefined {
  if (blocker === null) return undefined;
  switch (blocker.kind) {
    case "capacity":
      return t("cultivation.blocked_no_room", { cells: dragCellCount });
    case "bed_type":
      return blocker.bedTypeName
        ? t("cultivation.blocked_wrong_bed_type", {
            bedType: blocker.bedTypeName,
          })
        : t("cultivation.blocked_wrong_bed_type_unknown");
    case "bed_type_overrun":
      return t("cultivation.blocked_bed_type_overrun");
    case "bed_type_none":
      return t("cultivation.blocked_bed_type_none");
    case "occupied":
      return t("cultivation.blocked_by", {
        crop: blocker.info.label,
        from: blocker.info.fromWeek,
        to: blocker.info.toWeek,
      });
  }
}

/** "Cabbage (19-40) 15 cells" — one string for the tooltip and the a11y name. */
function describe(occupant: GridPlacement): string {
  const weeks =
    occupant.plantingWeek != null && occupant.endWeek != null
      ? ` (${occupant.plantingWeek}\u2013${occupant.endWeek})`
      : "";
  return `${occupant.label}${weeks} \u00b7 ${occupant.cellCount}`;
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
  dragging,
  validTarget,
  blockReason,
}: PlannerCellProps) {
  const { itemType, selected } = useDndGrid();

  const [{ isOver }, drop] = useDrop<DndDragPayload, void, { isOver: boolean }>(
    () => ({
      accept: itemType,
      // Carryover ground is physically occupied by last year's crop — it can be
      // seen but never planted into or dragged away.
      canDrop: () => editable && !occupant?.isCarryover && validTarget,
      drop: (item) => onDropBatch?.(item.chip.id, plotId, cell),
      collect: (monitor) => ({ isOver: monitor.isOver() && monitor.canDrop() }),
    }),
    [
      itemType,
      editable,
      onDropBatch,
      plotId,
      cell,
      occupant?.isCarryover,
      validTarget,
    ],
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
      canDrag: () => editable && !!occupant && !occupant.isCarryover,
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
    if (!editable || occupant?.isCarryover) return;
    // Keyboard / click path: a chip "picked up" in the palette lands here.
    if (selected) {
      // Same gate the mouse path gets from `canDrop`. Without it the keyboard
      // route could place a crop on a cell the grid is visibly greying out —
      // wrong bed type, occupied later in the season, or past the plot's end —
      // leaving the accessible path strictly weaker than the pointer one.
      if (!validTarget) return;
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
    occupant?.isCarryover ? "cultivation-planner__cell--carryover" : "",
    showLabel && occupant ? "cultivation-planner__cell--labelled" : "",
    dragging && !validTarget ? "cultivation-planner__cell--blocked" : "",
    dragging && validTarget ? "cultivation-planner__cell--available" : "",
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
      aria-label={
        dragging && blockReason
          ? blockReason
          : occupant
            ? describe(occupant)
            : emptyLabel
      }
      tabIndex={editable && !occupant?.isCarryover ? 0 : -1}
      onClick={handleActivate}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          handleActivate();
        }
      }}
    >
      {showLabel && occupant ? (
        <span className="cultivation-planner__cell-label">
          {occupant.label}
          {occupant.plantingWeek != null && occupant.endWeek != null ? (
            <span className="cultivation-planner__cell-meta">
              {" "}
              ({occupant.plantingWeek}–{occupant.endWeek})
            </span>
          ) : null}
          <span className="cultivation-planner__cell-meta">
            {" "}
            {occupant.cellCount}
          </span>
        </span>
      ) : null}
    </div>
  );

  // No tooltip: with hundreds of cells on screen, one popping up under the
  // pointer on every pass across the grid is noise, and it lands right where you
  // are trying to drop. The same text is still the cell's `aria-label`, so
  // screen readers keep the explanation.
  return cellNode;
}
