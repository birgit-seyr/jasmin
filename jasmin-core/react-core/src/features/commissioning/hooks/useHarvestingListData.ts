/**
 * Data pipeline for the HarvestingList page.
 *
 * Owns everything between the API and the table rows:
 *
 *   summary query → row filter → computed amount fields (total /
 *   share_content / order_content variants) → optional round-up to
 *   full VPE → gardener filter+sort → crate summary aggregation
 *
 * plus the related-days / variations-totals wiring for the selected
 * harvest day. The page component only holds UI state (selected
 * year/week/day, view toggle) and rendering.
 */

import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { activeAtDateForWeek } from "@shared/utils";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey,
  useCommissioningDocumentationSummarySummaryRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationSummarySummaryRetrieveParams,
  CommissioningSharesDeliveryDaysListParams,
} from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { useAggregatedVariationsTotals } from "./useAggregatedVariationsTotals";
import type { DocumentationSummaryRecord } from "./useDocumentationSummaryPage";
import { useCurrentDays } from "./useCurrentDays";
import { useInvalidateAfterTableMutation } from "@hooks/useInvalidateAfterTableMutation";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useVegetableSizeOptions } from "@hooks/useVegetableSizeOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";
import type { ShareDeliveryDayOption } from "./useShareDeliveryDays";
import { useShareDeliveryDays } from "./useShareDeliveryDays";

const currentWeekFallback = dayjs().isoWeek();

function parseNumber(value: unknown): number {
  const num = parseFloat(value as string);
  return isNaN(num) ? 0 : num;
}

// Variants of the same calculation: total / share_content / order_content.
// Each variant has its own set of fields on the API record (suffixed) and
// its own set of computed fields. Looping over them keeps the math defined
// once instead of 3× copy/paste.
const AMOUNT_VARIANTS = [
  { suffix: "", computedSuffix: "" },
  { suffix: "_share_content", computedSuffix: "_share_content" },
  { suffix: "_order_content", computedSuffix: "_order_content" },
] as const;

export interface CrateSummaryEntry {
  key: string;
  crate_name: string;
  quantity: number;
}

export function useHarvestingListData({
  selectedYear,
  selectedWeek,
  selectedDay,
  isPast,
  isGardenerView,
  roundUpToFullPU,
}: {
  selectedYear: number;
  selectedWeek: number | null;
  selectedDay: number | null;
  isPast: boolean;
  isGardenerView: boolean;
  roundUpToFullPU: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { getUnitLabel } = useUnitOptions();
  const { format } = useNumberFormat();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  // ── Related days + variations totals for the selected harvest day ──

  const { getRelatedDays, isLoaded: daysLoaded } = useCurrentDays(
    selectedWeek ?? currentWeekFallback,
    selectedYear,
  );

  const deliveryDaysForHarvesting = useMemo(() => {
    if (
      !daysLoaded ||
      selectedDay === null ||
      !getRelatedDays?.getDeliveryDaysForHarvesting
    ) {
      return [];
    }
    return getRelatedDays.getDeliveryDaysForHarvesting(selectedDay);
  }, [daysLoaded, getRelatedDays, selectedDay]);

  // Resolve all delivery_days for the selected harvest day to their DB ids
  // so VariationsTotalsCard can fetch & aggregate totals across them.
  const shareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({
        active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
      }),
      [selectedYear, selectedWeek],
    );
  const { shareDeliveryDays } = useShareDeliveryDays(shareDeliveryDaysParams);
  const variationsTotalsFilters = useMemo(() => {
    if (deliveryDaysForHarvesting.length === 0) return undefined;
    const ids = deliveryDaysForHarvesting
      .map((dayNumber) => {
        const match = shareDeliveryDays.find(
          (d: ShareDeliveryDayOption) =>
            Number(d.day_number) === Number(dayNumber),
        );
        return match?.id;
      })
      .filter((id): id is string => !!id);
    if (ids.length === 0) return undefined;
    return {
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeekFallback,
      delivery_day: ids,
      sending_share_type_id: true,
      physical_share_type_variations: true,
    };
  }, [
    deliveryDaysForHarvesting,
    shareDeliveryDays,
    selectedYear,
    selectedWeek,
  ]);

  // Same totals the on-screen ``VariationsTotalsCard`` shows; pulled here
  // raw (and filtered to non-zero, matching the card's hideZero default)
  // so the PDF first-page card displays identical numbers.
  const { entries: aggregatedVariationsTotals } = useAggregatedVariationsTotals(
    variationsTotalsFilters,
  );
  const variationsTotals = useMemo(
    () => aggregatedVariationsTotals.filter((v) => v.totalQuantity > 0),
    [aggregatedVariationsTotals],
  );

  // ── Summary query + row pipeline ──

  const listParams =
    useMemo<CommissioningDocumentationSummarySummaryRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek!,
        day_number: selectedDay!,
        is_past: isPast,
        model: "harvest",
        is_preparation_lists: true,
      }),
      [selectedYear, selectedWeek, isPast, selectedDay],
    );

  // ``isFetching`` drives the grid spinner: with the global
  // ``staleTime: 0`` a revisited year/week/day key has
  // ``isLoading === false``, so a refetch would otherwise render
  // stale rows with no indicator. ``loading`` (initial load only)
  // still gates the mobile card.
  const {
    data: rawData,
    isLoading: loading,
    isFetching,
  } = useCommissioningDocumentationSummarySummaryRetrieve(listParams);

  const data = useMemo(() => {
    // Directional cast at the orval boundary: raw rows lack the table-only
    // ``key`` (EditableTable derives it from ``id``).
    const items = (rawData ?? []) as DocumentationSummaryRecord[];
    return items.filter(
      (item) =>
        !!(
          item.theoretical_harvest_amount ||
          item.additional_theoretical_harvest_amount ||
          item.harvest_amount
        ),
    );
  }, [rawData]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey:
        getCommissioningDocumentationSummarySummaryRetrieveQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onDeleteSuccess } = useInvalidateAfterTableMutation(invalidateData);

  // Save returns an ``AdditionalTheoretical*`` row; the list is the
  // joined summary shape. The optimistic-add can't reconcile that —
  // explicit invalidate so the new row appears in the right shape.
  // See CleaningList.tsx for the same rationale.
  const onSaveSuccess = useCallback(() => {
    invalidateData();
  }, [invalidateData]);

  const processedData = useMemo(() => {
    return data.map((record) => {
      const unitLabel = getUnitLabel(record.unit as string);
      const puLabel = t("commissioning.pu");
      const amountPerPu = parseNumber(record.amount_per_pu);
      const computed: Record<string, unknown> = {};

      for (const { suffix, computedSuffix } of AMOUNT_VARIANTS) {
        const theoretical = parseNumber(
          record[`theoretical_harvest_amount${suffix}`],
        );
        const inStock = parseNumber(
          record[`theoretical_current_stock${suffix}`],
        );
        const additional = parseNumber(
          record[`additional_theoretical_harvest_amount${suffix}`],
        );

        const stillInStock = Math.max(inStock, 0);
        const toHarvest = Math.max(theoretical - stillInStock, 0);
        const total = Math.max(toHarvest + additional, 0);

        const amountPu =
          amountPerPu > 0 && total > 0
            ? Number((total / amountPerPu).toFixed(1))
            : 0;

        const totalText = total ? `${format(total, 0)} ${unitLabel}` : "";
        const amountPuText =
          amountPu > 0 ? `${format(amountPu, 1)} ${puLabel}` : "";
        const combined = [totalText, amountPuText].filter(Boolean).join(" - ");

        computed[`computed_still_in_stock${computedSuffix}`] = stillInStock;
        computed[`computed_to_harvest${computedSuffix}`] = toHarvest;
        computed[`computed_total_amount${computedSuffix}`] = total;
        computed[`computed_amount_pu${computedSuffix}`] = amountPu;
        computed[`computed_amount_combined${computedSuffix}`] = combined;
        computed[`computed_total_amount_text${computedSuffix}`] = totalText;
        computed[`computed_amount_pu_text${computedSuffix}`] = amountPuText;
      }

      const amountPerPuText =
        amountPerPu > 0
          ? `${format(amountPerPu, 1)} ${unitLabel}/${puLabel}`
          : "";

      const noteInfo: string[] = [];
      if (record.note) noteInfo.push(record.note as string);
      if (record.forecast_note) noteInfo.push(record.forecast_note as string);

      const plotInfo: string[] = [];
      if (record.forecast_plot_name) {
        plotInfo.push(
          `${t("commissioning.plot")}: ${record.forecast_plot_name}`,
        );
      }
      if (record.forecast_bed_number) {
        plotInfo.push(
          `${t("commissioning.bed_number")}: ${record.forecast_bed_number}`,
        );
      }

      const sizeLabel =
        record.size && record.size !== "M"
          ? ` (${getVegetableSizeLabel(record.size as string)})`
          : "";

      return {
        ...record,
        ...computed,
        computed_amount_per_pu: amountPerPu,
        computed_amount_per_pu_text: amountPerPuText,
        computed_article_with_size: `${record.share_article_name}${sizeLabel}`,
        computed_note_line: noteInfo.join(", "),
        computed_plot_line: plotInfo.join(", "),
        computed_unit_label: unitLabel,
      } as TableRecord;
    });
  }, [data, getUnitLabel, getVegetableSizeLabel, t, format]);

  const roundedData = useMemo(() => {
    if (!roundUpToFullPU) return processedData;
    const puLabel = t("commissioning.pu");
    return processedData.map((record) => {
      const amountPerPu = record.computed_amount_per_pu as number;
      if (!(amountPerPu > 0)) return record;
      const unitLabel = record.computed_unit_label as string;
      const updates: Record<string, unknown> = {};
      for (const suffix of ["", "_share_content", "_order_content"] as const) {
        const total = record[`computed_total_amount${suffix}`] as number;
        if (!(total > 0)) continue;
        const roundedPu = Math.ceil(total / amountPerPu);
        const roundedTotal = roundedPu * amountPerPu;
        const totalText = `${format(roundedTotal, 0)} ${unitLabel}`;
        const puText = `${format(roundedPu, 0)} ${puLabel}`;
        updates[`computed_total_amount${suffix}`] = roundedTotal;
        updates[`computed_amount_pu${suffix}`] = roundedPu;
        updates[`computed_total_amount_text${suffix}`] = totalText;
        updates[`computed_amount_pu_text${suffix}`] = puText;
        updates[`computed_amount_combined${suffix}`] =
          `${totalText} - ${puText}`;
      }
      return { ...record, ...updates } as TableRecord;
    });
  }, [processedData, roundUpToFullPU, t, format]);

  // Filter + sort used by the gardener view AND by the PDF (which is
  // always rendered in gardener layout). Drops rows where there's nothing
  // to harvest so the gardener doesn't see a wall of empty "—" cells.
  const applyGardenerFilter = useCallback(
    (rows: TableRecord[]): TableRecord[] => {
      const filtered = rows.filter((record) => {
        const shareContentAmount =
          record.computed_amount_combined_share_content;
        const orderContentAmount =
          record.computed_amount_combined_order_content;
        const combinedAmount = record.computed_amount_combined;

        const hasShareContent =
          shareContentAmount &&
          shareContentAmount !== 0 &&
          shareContentAmount !== "0" &&
          shareContentAmount !== "";

        const hasOrderContent =
          orderContentAmount &&
          orderContentAmount !== 0 &&
          orderContentAmount !== "0" &&
          orderContentAmount !== "";

        const hasCombinedAmount =
          combinedAmount &&
          combinedAmount !== "0" &&
          combinedAmount !== "" &&
          combinedAmount !== 0;

        return hasShareContent || hasOrderContent || hasCombinedAmount;
      });

      return [...filtered].sort((a, b) => {
        const plotA = (a.forecast_plot_name as string) || "";
        const plotB = (b.forecast_plot_name as string) || "";
        const cmp = plotA.localeCompare(plotB);
        if (cmp !== 0) return cmp;
        const bedA = (a.forecast_bed_number as number) ?? Infinity;
        const bedB = (b.forecast_bed_number as number) ?? Infinity;
        return bedA - bedB;
      });
    },
    [],
  );

  const filteredData = useMemo(() => {
    return isGardenerView ? applyGardenerFilter(roundedData) : roundedData;
  }, [roundedData, isGardenerView, applyGardenerFilter]);

  // PDF always uses the gardener-view filter, regardless of which view the
  // user has selected on screen — the PDF columns are fixed to the flat
  // layout, so the same "hide rows with nothing to harvest" rule applies.
  const pdfData = useMemo(
    () => applyGardenerFilter(roundedData),
    [roundedData, applyGardenerFilter],
  );

  // Pre-compute which record IDs start a new plot group (for mobile headers)
  // Uses record.id because EditableTable remaps key to id internally
  const plotGroupFirstIds = useMemo(() => {
    const ids = new Set<unknown>();
    let lastPlot: string | null = null;
    for (const record of filteredData) {
      const plot = (record.forecast_plot_name as string) || "";
      if (plot !== lastPlot) {
        ids.add(record.id);
        lastPlot = plot;
      }
    }
    return ids;
  }, [filteredData]);

  const crateSummary = useMemo<CrateSummaryEntry[]>(() => {
    const crateMap = new Map<string, number>();

    roundedData.forEach((record) => {
      if (
        (record.computed_total_amount as number) > 0 &&
        (record.computed_amount_per_pu as number) > 0 &&
        record.harvesting_crate_name &&
        record.harvesting_crate_name !== "-"
      ) {
        const amountPu = Math.ceil(
          (record.computed_total_amount as number) /
            (record.computed_amount_per_pu as number),
        );
        const crateName = record.harvesting_crate_name as string;
        crateMap.set(crateName, (crateMap.get(crateName) ?? 0) + amountPu);
      }
    });

    return Array.from(crateMap.entries())
      .map(([crateName, quantity]) => ({
        key: crateName,
        crate_name: crateName,
        quantity: quantity,
      }))
      .sort((a, b) => a.crate_name.localeCompare(b.crate_name));
  }, [roundedData]);

  return {
    loading,
    isFetching,
    filteredData,
    pdfData,
    plotGroupFirstIds,
    crateSummary,
    deliveryDaysForHarvesting,
    variationsTotalsFilters,
    variationsTotals,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
  };
}
