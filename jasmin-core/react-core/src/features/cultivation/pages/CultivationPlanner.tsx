import { PlayCircleOutlined, SaveOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Select, Slider, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationPlanSolutionsChooseCreate,
  cultivationPlanSolutionsRunCreate,
  cultivationPlanSolutionsSavePlacementsCreate,
  getCultivationPlanSolutionsListQueryKey,
  useCultivationCultivationBatchesList,
  useCultivationPlanSolutionsList,
  useCultivationPlanSolutionsRetrieve,
  useCultivationPlotsList,
} from "@shared/api/generated/cultivation/cultivation";
import type {
  CultivationBatch,
  CultivationPlanSolutionDetail,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { YearSelector } from "@shared/selectors";
import { DndGrid, DraggableChip, usePastelColorMap } from "@shared/ui";
import { ExplainerText } from "@shared/ui";
import { JobProgressDrawer } from "@shared/ui/JobProgressDrawer";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import PlotGrid, { type GridPlacement } from "../components/PlotGrid";
import { CELLS_PER_BED, occupiesWeek } from "../utils/serpentine";

const { Text } = Typography;

/** A batch placed by the gardener/solver: batch id -> where it sits. */
type PlacementMap = Record<string, { plotId: string; startCell: number }>;

export default function CultivationPlanner() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const queryClient = useQueryClient();

  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState<number>(currentYear);
  const [week, setWeek] = useState<number>(20);
  const [solutionId, setSolutionId] = useState<string | undefined>();
  const [jobId, setJobId] = useState<string | null>(null);
  const [edits, setEdits] = useState<PlacementMap | null>(null);
  const [saving, setSaving] = useState(false);

  const { data: plots, isLoading: plotsLoading } = useCultivationPlotsList();
  const { data: batches } = useCultivationCultivationBatchesList();
  const { data: solutions, isFetching: solutionsFetching } =
    useCultivationPlanSolutionsList({ year });
  const { data: solution, isFetching: solutionFetching } =
    useCultivationPlanSolutionsRetrieve(solutionId ?? "", {
      query: { enabled: !!solutionId },
    });

  // Pick the chosen plan (else the newest) whenever the year's list changes.
  useEffect(() => {
    if (!solutions?.length) {
      setSolutionId(undefined);
      return;
    }
    const stillThere = solutions.some((s) => s.id === solutionId);
    if (stillThere) return;
    setSolutionId((solutions.find((s) => s.chosen) ?? solutions[0]).id);
  }, [solutions, solutionId]);

  // A fresh solution wipes any unsaved hand edits.
  useEffect(() => setEdits(null), [solutionId]);

  const yearBatches = useMemo(
    () => (batches ?? []).filter((b: CultivationBatch) => b.year === year),
    [batches, year],
  );
  const batchById = useMemo(() => {
    const map = new Map<string, CultivationBatch>();
    yearBatches.forEach((b) => b.id && map.set(b.id, b));
    return map;
  }, [yearBatches]);

  const colorMap = usePastelColorMap(
    useMemo(() => yearBatches.map((b) => b.id ?? ""), [yearBatches]),
  );

  const cellsPerBed = solution?.cells_per_bed ?? CELLS_PER_BED;

  const cellCountFor = useCallback(
    (batch: CultivationBatch | undefined): number => {
      const beds = Number(batch?.amount_of_beds ?? 0);
      return beds > 0 ? Math.ceil(beds * cellsPerBed) : 1;
    },
    [cellsPerBed],
  );

  const labelFor = useCallback(
    (batchId: string, fallback?: string): string =>
      batchById.get(batchId)?.vegetable_name ?? fallback ?? batchId,
    [batchById],
  );

  // The plan as stored, overlaid with any unsaved hand edits.
  const placements = useMemo<GridPlacement[]>(() => {
    const details = (solution?.details ??
      []) as readonly CultivationPlanSolutionDetail[];
    const base: PlacementMap = {};
    const meta = new Map<
      string,
      { label: string; plantingWeek?: number; endWeek?: number; cellCount: number }
    >();
    details.forEach((d) => {
      base[d.batch] = { plotId: d.plot, startCell: d.start_cell };
      meta.set(d.batch, {
        label: d.vegetable_name ?? d.batch,
        plantingWeek: d.planting_week,
        endWeek: d.end_week,
        cellCount: d.cell_count,
      });
    });
    const effective = edits ?? base;
    return Object.entries(effective).map(([batchId, pos]) => {
      const info = meta.get(batchId);
      const batch = batchById.get(batchId);
      return {
        batchId,
        plotId: pos.plotId,
        startCell: pos.startCell,
        cellCount: info?.cellCount ?? cellCountFor(batch),
        label: labelFor(batchId, info?.label),
        color: colorMap.get(batchId),
        plantingWeek: info?.plantingWeek ?? batch?.planting_week,
        endWeek: info?.endWeek ?? batch?.end_week,
      };
    });
  }, [solution, edits, batchById, colorMap, cellCountFor, labelFor]);

  const placedIds = useMemo(
    () => new Set(placements.map((p) => p.batchId)),
    [placements],
  );
  // Palette = this year's batches that are not placed anywhere yet.
  const unplaced = useMemo(
    () => yearBatches.filter((b) => b.id && !placedIds.has(b.id)),
    [yearBatches, placedIds],
  );

  const activeInWeek = useMemo(
    () =>
      placements.filter((p) =>
        occupiesWeek(p.plantingWeek, p.endWeek, week),
      ),
    [placements, week],
  );

  const currentMap = useCallback((): PlacementMap => {
    if (edits) return edits;
    const base: PlacementMap = {};
    placements.forEach((p) => {
      base[p.batchId] = { plotId: p.plotId, startCell: p.startCell };
    });
    return base;
  }, [edits, placements]);

  const handleDropBatch = useCallback(
    (batchId: string, plotId: string, startCell: number) => {
      setEdits({ ...currentMap(), [batchId]: { plotId, startCell } });
    },
    [currentMap],
  );

  const handleUnplace = useCallback(
    (batchId: string) => {
      const next = { ...currentMap() };
      delete next[batchId];
      setEdits(next);
    },
    [currentMap],
  );

  const handleRun = useCallback(async () => {
    try {
      const response = (await cultivationPlanSolutionsRunCreate({
        year,
      })) as unknown as { job_id?: string };
      if (response?.job_id) setJobId(response.job_id);
    } catch (error) {
      notify.error(getErrorMessage(error, t("cultivation.solver_run_failed")));
    }
  }, [year, t]);

  const invalidateSolutions = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCultivationPlanSolutionsListQueryKey(),
    });
  }, [queryClient]);

  const handleChoose = useCallback(async () => {
    if (!solutionId) return;
    try {
      await cultivationPlanSolutionsChooseCreate(solutionId);
      notify.success(t("cultivation.solution_chosen"));
      invalidateSolutions();
    } catch (error) {
      notify.error(getErrorMessage(error, t("common.error_saving")));
    }
  }, [solutionId, invalidateSolutions, t]);

  const handleSaveEdits = useCallback(async () => {
    if (!solutionId || !edits) return;
    setSaving(true);
    try {
      await cultivationPlanSolutionsSavePlacementsCreate(solutionId, {
        placements: Object.entries(edits).map(([batch, pos]) => ({
          batch,
          plot: pos.plotId,
          start_cell: String(pos.startCell),
        })),
      });
      notify.success(t("common.saved_successfully"));
      setEdits(null);
      invalidateSolutions();
      queryClient.invalidateQueries({ queryKey: ["cultivation", "plan_solutions"] });
    } catch (error) {
      notify.error(getErrorMessage(error, t("common.error_saving")));
    } finally {
      setSaving(false);
    }
  }, [solutionId, edits, invalidateSolutions, queryClient, t]);

  const solutionOptions = useMemo(
    () =>
      (solutions ?? []).map((s) => ({
        value: s.id as string,
        label: `${t("cultivation.version_short", { version: s.version })}${
          s.chosen ? " ★" : ""
        } · ${t("cultivation.n_placements", { count: s.placement_count ?? 0 })}`,
      })),
    [solutions, t],
  );

  return (
    <div>
      <h1>{t("cultivation.planner")}</h1>
      <h5>{t("cultivation.planner_description")}</h5>

      <div className="cultivation-planner__toolbar">
        <YearSelector selectedYear={year} setSelectedYear={setYear} />
        <Select
          style={{ minWidth: "18em" }}
          placeholder={t("cultivation.select_solution")}
          aria-label={t("cultivation.select_solution")}
          value={solutionId}
          onChange={setSolutionId}
          options={solutionOptions}
          loading={solutionsFetching}
          notFoundContent={t("cultivation.no_solutions_yet")}
        />
        {isGardener && (
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={handleRun}
          >
            {t("cultivation.run_solver")}
          </Button>
        )}
        {isGardener && solutionId && !solution?.chosen && (
          <Button onClick={handleChoose}>{t("cultivation.choose_solution")}</Button>
        )}
        {solution?.chosen && <Tag color="green">{t("cultivation.chosen")}</Tag>}
        {isGardener && edits && (
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSaveEdits}
          >
            {t("cultivation.save_adjustments")}
          </Button>
        )}
        {edits && (
          <Button onClick={() => setEdits(null)}>{t("common.cancel")}</Button>
        )}
      </div>

      <div className="cultivation-planner__toolbar">
        <Text>{t("cultivation.show_week", { week })}</Text>
        <Slider
          style={{ flex: "1 1 20em", minWidth: "14em" }}
          min={1}
          max={52}
          value={week}
          onChange={setWeek}
          aria-label={t("cultivation.show_week", { week })}
        />
        <Text type="secondary">
          {t("cultivation.n_crops_in_week", { count: activeInWeek.length })}
        </Text>
      </div>

      {edits && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: "1em" }}
          message={t("cultivation.unsaved_adjustments")}
        />
      )}

      {plotsLoading || solutionFetching ? (
        <Spin />
      ) : (
        <DndGrid onPlace={() => undefined}>
          <div className="cultivation-planner__layout">
            <div className="cultivation-planner__palette">
              <div className="cultivation-planner__palette-title">
                {t("cultivation.unplaced_batches")}
              </div>
              {unplaced.length === 0 ? (
                <p className="cultivation-planner__hint">
                  {t("cultivation.all_batches_placed")}
                </p>
              ) : (
                <div className="cultivation-planner__palette-list">
                  {unplaced.map((batch) => (
                    <DraggableChip
                      key={batch.id}
                      chip={{
                        id: batch.id as string,
                        label: `${labelFor(batch.id as string)} · KW ${
                          batch.planting_week
                        }`,
                        color: colorMap.get(batch.id as string),
                      }}
                      canDrag={isGardener}
                      ariaHint={t("cultivation.drag_to_place")}
                    />
                  ))}
                </div>
              )}
              {isGardener && (
                <p className="cultivation-planner__hint" style={{ marginTop: "0.75em" }}>
                  {t("cultivation.click_placed_to_unplace")}
                </p>
              )}
            </div>

            <div className="cultivation-planner__plots">
              {(plots ?? []).length === 0 ? (
                <p className="cultivation-planner__empty">
                  {t("cultivation.no_plots_yet")}
                </p>
              ) : (
                (plots ?? []).map((plot) => (
                  <PlotGrid
                    key={plot.id}
                    plot={plot}
                    placements={placements}
                    week={week}
                    cellsPerBed={cellsPerBed}
                    editable={isGardener}
                    onDropBatch={handleDropBatch}
                    onSelectPlacement={(p) => handleUnplace(p.batchId)}
                  />
                ))
              )}
            </div>
          </div>
        </DndGrid>
      )}

      <ExplainerText title={t("common.info")}>
        {t("explainers.cultivation_planner")}
      </ExplainerText>

      <JobProgressDrawer
        jobId={jobId}
        title={t("cultivation.run_solver")}
        onClose={() => {
          invalidateSolutions();
          setJobId(null);
        }}
      />
    </div>
  );
}
