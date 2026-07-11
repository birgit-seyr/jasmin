/**
 * Storage-scoped documentation page scaffold.
 *
 * Wraps {@link useDocumentationSummaryPage} and owns the page-level storage
 * dimension shared by DocumentationHarvest + DocumentationPurchase: the
 * ``selectedStorage`` selector state, the storage-gated summary query, the
 * storage-filtered grid rows, the storage-stamped ``customSave``, and the
 * storage-aware table remount key.
 *
 * Each page keeps only what genuinely differs: its columns, mutation
 * ``apiFunctions``, ``customEdit``, bulk actions, and JSX. The only per-page
 * knobs here are ``withDay`` (harvest is day-scoped, purchase week-scoped), an
 * ``extraQueryEnabled`` gate (harvest also waits for async columns), and a
 * ``rowHasData`` predicate (the "is this storage-matched row worth showing?"
 * check, which reads model-specific amount fields).
 */

import { useCallback, useMemo, useState } from "react";

import { currentWeek } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

import {
  useDocumentationSummaryPage,
  type DocumentationModel,
  type DocumentationSummaryRecord,
} from "./useDocumentationSummaryPage";
import { useStorages } from "./useStorages";

interface UseStorageDocumentationPageOptions {
  /** The documentation model the summary query reports on. */
  model: DocumentationModel;
  /** Day-scoped (harvest) vs week-scoped (purchase). Default true. */
  withDay?: boolean;
  /**
   * AND-ed with ``!!selectedStorage`` to gate the summary query — e.g. a page
   * that also waits for async columns to load. Default true.
   */
  extraQueryEnabled?: boolean;
  /**
   * Does a storage-matched summary row carry real data worth showing? Runs
   * AFTER the storage filter. MUST be referentially stable (useCallback at the
   * call site) — it feeds the ``data`` memo.
   */
  rowHasData: (row: DocumentationSummaryRecord) => boolean;
}

export function useStorageDocumentationPage({
  model,
  withDay = true,
  extraQueryEnabled = true,
  rowHasData,
}: UseStorageDocumentationPageOptions) {
  const [selectedStorage, setSelectedStorage] = useState<string | null>(null);
  const { storages } = useStorages();

  const summary = useDocumentationSummaryPage({
    model,
    withDay,
    queryEnabled: !!selectedStorage && extraQueryEnabled,
  });

  const { rawData, selectedYear, selectedWeek, selectedDay } = summary;

  const data = useMemo<TableRecord[]>(() => {
    // Directional cast at the orval boundary: raw rows lack the table-only
    // ``key`` until the map below adds it.
    const items = (rawData ?? []) as DocumentationSummaryRecord[];
    return items
      .filter((item) => {
        // Only rows for the page-level selected storage, then the page's own
        // "has real data" predicate.
        if (!item[`storage_${selectedStorage}`]) return false;
        return rowHasData(item);
      })
      .map((item) => ({ ...item, key: item.id ?? "" }));
  }, [rawData, selectedStorage, rowHasData]);

  // The whole grid is scoped to one page-level storage; stamp it (and the
  // year/week/[day] context) on every create/update, coercing a blank amount
  // to 0. Identical payload to what each page previously built inline.
  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      storage: selectedStorage,
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeek,
      ...(withDay ? { day_number: selectedDay ?? 0 } : {}),
      amount:
        transformedData.amount === null ||
        transformedData.amount === "" ||
        transformedData.amount === undefined
          ? 0
          : transformedData.amount,
    }),
    [selectedStorage, selectedYear, selectedWeek, selectedDay, withDay],
  );

  return {
    ...summary,
    selectedStorage,
    setSelectedStorage,
    storages,
    data,
    tableKey: `${summary.tableKey}-${selectedStorage}`,
    customSave,
  };
}
