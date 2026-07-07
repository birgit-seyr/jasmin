import { useMemo } from "react";
import type { ShareTypeEnum } from "@shared/api/generated/models";
import { activeAtDateForWeek } from "@shared/utils";
import {
  useShareDeliveryDays,
  type ShareDeliveryDayOption,
} from "./useShareDeliveryDays";
import {
  useShareTypeVariations,
  type ShareTypeVariationOption,
} from "./useShareTypeVariations";

export interface UsePlanningAxesParams {
  year: number;
  /** ISO week. */
  week: number;
  shareOption?: string | null;
  /**
   * Require each day to have a DeliveryStationDay. When true (the default),
   * ``useShareDeliveryDays`` drops days whose ``delivery_stations`` array is
   * empty AND attaches the stations prefetch. Planning grids want this true so
   * their day axis is identical everywhere; it is the single knob that used to
   * be the overloaded ``get_delivery_stations`` flag.
   */
  requireStations?: boolean;
  /** Attach per-day tour info (``used_tours``) for tour-granularity columns. */
  needTours?: boolean;
}

export interface PlanningAxes {
  shareDeliveryDays: ShareDeliveryDayOption[];
  shareTypeVariations: ShareTypeVariationOption[];
  toursExist: boolean;
  activeAtDate: string;
  daysLoading: boolean;
  variationsLoading: boolean;
}

/**
 * SINGLE SOURCE OF TRUTH for the (days × share_type_variations) AXES of every
 * planning / backup grid. Guarantees the base planning page, the backup modal,
 * and any other consumer resolve the SAME day and variation sets — same
 * ``active_at_date``, same station-presence filtering, same variation filter.
 * Before this hook each caller hand-built its filter object and they drifted
 * (see docs/day-variation-columns-audit.md — the modal-shows-station-less-day
 * bug came from exactly that).
 */
export function usePlanningAxes({
  year,
  week,
  shareOption,
  requireStations = true,
  needTours = false,
}: UsePlanningAxesParams): PlanningAxes {
  // The canonical week→date resolution (Saturday of the ISO week), shared with
  // every other week-scoped lookup (share types, order price date, …).
  const activeAtDate = useMemo(
    () => activeAtDateForWeek(year, week),
    [year, week],
  );

  const dayParams = useMemo(
    () => ({
      active_at_date: activeAtDate,
      get_delivery_stations: requireStations,
      need_info_on_tours: needTours,
    }),
    [activeAtDate, requireStations, needTours],
  );

  // The variation query is gated by a null param (see useShareTypeVariations):
  // no share_option -> no fetch, empty set.
  const variationParams = useMemo(
    () =>
      shareOption
        ? {
            physical: true,
            active_at_date: activeAtDate,
            share_option: shareOption as ShareTypeEnum,
          }
        : null,
    [activeAtDate, shareOption],
  );

  const {
    shareDeliveryDays,
    toursExist,
    loading: daysLoading,
  } = useShareDeliveryDays(dayParams);
  const { shareTypeVariations, loading: variationsLoading } =
    useShareTypeVariations(variationParams);

  // Present the day × variation grid in the office-defined ``sort_order``
  // (S/M/L given 1/2/3 → S, M, L), consistent with the delivery-station
  // columns. Falls back to size only to break ties when sort_order is unset.
  const orderedShareTypeVariations = useMemo(
    () =>
      [...shareTypeVariations].sort(
        (a, b) =>
          (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
          (a.size ?? "").localeCompare(b.size ?? ""),
      ),
    [shareTypeVariations],
  );

  return {
    shareDeliveryDays,
    shareTypeVariations: orderedShareTypeVariations,
    toursExist,
    activeAtDate,
    daysLoading,
    variationsLoading,
  };
}
