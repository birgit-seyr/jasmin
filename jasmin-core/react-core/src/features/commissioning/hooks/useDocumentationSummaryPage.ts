/**
 * Shared data/state scaffold for the documentation-summary pages
 * (washing, cleaning, harvest, purchase preparation lists).
 *
 * Every one of those pages drives the SAME summary endpoint
 * (``commissioningDocumentationSummarySummaryRetrieve``) off the same
 * year/week/[day]/is_past selectors, with the same invalidate-on-mutation
 * wiring and table-remount key. Only the ``model`` discriminator and a
 * couple of optional extra params differ. This hook owns that boilerplate
 * so each page keeps only its own columns / mutation endpoints / extras.
 *
 * What stays in the PAGE (deliberately not here): the mutation
 * ``apiFunctions`` (harvest/purchase use model-specific CRUD endpoints
 * while washing/cleaning use the shared add-additional-amount endpoint),
 * the ``customSave`` body (it diverges per page — harvest omits ``model``
 * and coerces amount, purchase validates storage), the columns, and any
 * page-specific row filtering / computed fields.
 */

import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import {
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey,
  useCommissioningDocumentationSummarySummaryRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationSummarySummaryRetrieveParams,
  DocumentationSummaryRow,
} from "@shared/api/generated/models";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { isWeekInPast } from "@shared/utils";
import { useInvalidateAfterTableMutation } from "@hooks/useInvalidateAfterTableMutation";

/**
 * A documentation-summary row as the pages consume it: the API row plus the
 * EditableTable bookkeeping fields (``key``) and the client-side
 * ``next_week_theoretical`` augmentation (purchase preparation list only).
 */
export type DocumentationSummaryRecord = DocumentationSummaryRow &
  TableRecord & { next_week_theoretical?: number };

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();
const currentDay = dayjs().isoWeekday();

export type DocumentationModel =
  | "harvest"
  | "purchase"
  | "washamount"
  | "cleanamount"
  | "waste";

interface UseDocumentationSummaryPageOptions {
  /** The documentation model the summary query reports on. */
  model: DocumentationModel;
  /**
   * Whether the page is day-scoped. When true (default) ``day_number`` is
   * part of the params, the customSaveBase, and the remount key; purchase
   * preparation lists pass ``false``.
   */
  withDay?: boolean;
  /**
   * Extra params merged into the summary query (e.g. ``seller``,
   * ``is_preparation_lists``). MUST be referentially stable (memoize at the
   * call site) — it feeds the query key.
   */
  extraListParams?: Record<string, unknown>;
  /** Gate the summary query (e.g. until dynamic columns have loaded). */
  queryEnabled?: boolean;
}

export function useDocumentationSummaryPage({
  model,
  withDay = true,
  extraListParams,
  queryEnabled = true,
}: UseDocumentationSummaryPageOptions) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDay, setSelectedDay] = useState<number | null>(
    withDay ? currentDay - 1 : null,
  );
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const queryClient = useQueryClient();

  const listParams =
    useMemo<CommissioningDocumentationSummarySummaryRetrieveParams>(
      () =>
        ({
          year: selectedYear,
          delivery_week: selectedWeek!,
          is_past: isPast,
          ...(withDay ? { day_number: selectedDay! } : {}),
          model,
          ...extraListParams,
        }) as CommissioningDocumentationSummarySummaryRetrieveParams,
      [
        selectedYear,
        selectedWeek,
        selectedDay,
        isPast,
        model,
        withDay,
        extraListParams,
      ],
    );

  // ``isFetching`` (not ``isLoading``) so a revisited cached year/week/day
  // key still shows the grid overlay on refetch — with the global
  // ``staleTime: 0`` a cached remount has ``isLoading === false``.
  const { data: rawData, isFetching } =
    useCommissioningDocumentationSummarySummaryRetrieve(listParams, {
      query: { enabled: queryEnabled },
    });

  // Directional cast at the orval boundary: the raw rows don't carry the
  // table-only ``key`` yet (EditableTable derives it from ``id``).
  const rows = useMemo<DocumentationSummaryRecord[]>(
    () => (rawData ?? []) as DocumentationSummaryRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey:
        getCommissioningDocumentationSummarySummaryRetrieveQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  // Composable base for a page's ``customSave`` — pages spread this and add
  // their own fields (storage, coerced amount, …). NOT a complete payload.
  const customSaveBase = useMemo<Record<string, unknown>>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
      ...(withDay ? { day_number: selectedDay } : {}),
      model,
    }),
    [selectedYear, selectedWeek, selectedDay, model, withDay],
  );

  const tableKey = withDay
    ? `${selectedYear}-${selectedWeek}-${selectedDay}`
    : `${selectedYear}-${selectedWeek}`;

  return {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    selectedDay,
    setSelectedDay,
    isPast,
    listParams,
    rawData,
    rows,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
    customSaveBase,
    tableKey,
  };
}
