/**
 * Data sources for the Abos page.
 *
 * Owns the subscriptions list query + invalidation and every select-
 * option source the columns need (members, payment cycles, share type
 * variations, delivery-station days), including the per-row station-
 * day option computation (validity window + capacity greying). The
 * page component only holds UI state (modals, row selection) and
 * rendering.
 */

import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import {
  getCommissioningAbosListQueryKey,
  useCommissioningAbosList,
} from "@shared/api/generated/commissioning/commissioning";
import type { AboRecord } from "@features/abos/pages/types";
import {
  capacityWindowParams,
  stationDayTermCapacity,
} from "@features/abos/utils/stationCapacity";
import { useAllShareTypeVariations } from "@hooks/useAllShareTypeVariations";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { useDeliveryStationDays } from "@hooks/useDeliveryStationDays";
import { useInvalidateAfterTableMutation } from "@hooks/useInvalidateAfterTableMutation";
import { useMembers } from "@hooks/useMembers";
import { usePaymentCycles } from "@hooks/usePaymentCycles";
import { useShareTypes } from "@hooks/useShareTypes";

export function useAbosData() {
  const queryClient = useQueryClient();
  const { dateFormat } = useDateFormat();

  const { members } = useMembers();

  const { paymentCycles } = usePaymentCycles();

  const shareTypeParams = useMemo(
    () => ({
      active_at_date: dayjs().format("YYYY-MM-DD"),
      include_future: true,
    }),
    [],
  );
  const { shareTypes } = useShareTypes(shareTypeParams);
  // Fetch capacity for a wide window (this year + next) so each row can grey
  // out station-days that are full anywhere in its subscription period. Weeks
  // outside the window read as available; the backend save is the authority.
  const deliveryStationDayParams = useMemo(() => capacityWindowParams(), []);
  const { deliveryStationDays: allDeliveryStationDays } =
    useDeliveryStationDays(deliveryStationDayParams);

  // Literal-typed alias: the interface-based ``ShareTypeOption`` has no
  // implicit index signature, which the hook's index-signed ``ShareTypeRef``
  // parameter requires — this bridges the two without a cast.
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const { shareTypeVariations: allShareTypeVariations } =
    useAllShareTypeVariations(shareTypeRefs, shareTypeParams);

  // ``variation.share_type`` is the FK id; ``shareTypes`` carries
  // the ``delivery_cycle`` we need for cycle-aware trial-term math.
  // Build it once per render-of-inputs as a flat ``{ variationId →
  // delivery_cycle }`` map so the field-change handlers can read it
  // without a nested ``find()`` per keystroke. Unknown variation
  // (legacy row, race with refetch) falls back to WEEKLY via
  // ``weeksPerDelivery``.
  const variationDeliveryCycleById = useMemo(() => {
    const cycleByShareType = new Map<string, string | null | undefined>();
    for (const shareType of shareTypes) {
      cycleByShareType.set(
        String(shareType.value),
        shareType.delivery_cycle ?? null,
      );
    }
    const out = new Map<string, string | null | undefined>();
    for (const variation of allShareTypeVariations) {
      const shareTypeId = variation.share_type;
      if (shareTypeId == null) continue;
      out.set(
        String(variation.value),
        cycleByShareType.get(String(shareTypeId)),
      );
    }
    return out;
  }, [shareTypes, allShareTypeVariations]);

  // Fetch abos data using Orval-generated hook. ``isFetching`` (not
  // ``isLoading``) so the grid overlay shows on every refetch — with the
  // global ``staleTime: 0`` a cached remount has ``isLoading === false``.
  // Waitlisted drafts are excluded — they live on the WaitingListAbos page
  // until the office promotes them via confirm.
  const { data: abosData, isFetching } = useCommissioningAbosList({
    on_waiting_list: false,
  });

  const data = useMemo(
    () => (abosData ?? []) as unknown as AboRecord[],
    [abosData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningAbosListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess, recentlyAddedIds } =
    useInvalidateAfterTableMutation(invalidateData);

  // Pre-parse DSD validity windows ONCE per change of
  // ``allDeliveryStationDays`` (instead of re-parsing every dsd
  // ``valid_from`` / ``valid_until`` string per row, per render).
  // 4 dayjs parses per DSD × O(rows) per render is wasted work
  // because the DSD list rarely changes inside an edit flow.
  // We keep the original DSD object as ``ref`` so the consumer
  // (``EditableTable``'s select column) still gets the unmodified
  // SelectOption shape (``label`` / ``value`` + window fields).
  type DSDOption = (typeof allDeliveryStationDays)[number];
  const parsedDeliveryStationDays = useMemo(() => {
    interface ParsedDSD {
      ref: DSDOption;
      from: number;
      // ``Number.POSITIVE_INFINITY`` when valid_until is null —
      // turns the upper-bound check into a single ``rowMs <= until``
      // numeric compare instead of a null-guard branch.
      until: number;
    }
    const out: ParsedDSD[] = [];
    for (const dsd of allDeliveryStationDays) {
      const fromDay = dayjs(dsd.valid_from);
      if (!fromDay.isValid()) continue;
      out.push({
        ref: dsd,
        from: fromDay.startOf("day").valueOf(),
        until: dsd.valid_until
          ? dayjs(dsd.valid_until).endOf("day").valueOf()
          : Number.POSITIVE_INFINITY,
      });
    }
    return out;
  }, [allDeliveryStationDays]);

  const getDeliveryStationDaysForRow = useCallback(
    (record: AboRecord) => {
      if (!record.valid_from) return allDeliveryStationDays;

      const rowDate = dayjs(record.valid_from, dateFormat, true).isValid()
        ? dayjs(record.valid_from, dateFormat, true)
        : dayjs(record.valid_from, "YYYY-MM-DD", true);

      if (!rowDate.isValid()) return allDeliveryStationDays;

      // Single numeric comparison per DSD against the pre-parsed
      // window. ~1 µs per row vs ~50 µs with the previous
      // 4-dayjs-parses-per-DSD shape.
      const rowMs = rowDate.startOf("day").valueOf();
      const result: DSDOption[] = [];
      for (const p of parsedDeliveryStationDays) {
        if (rowMs >= p.from && rowMs <= p.until) {
          result.push(p.ref);
        }
      }

      // Grey out station-days that are full in ANY week of this row's period
      // (valid_from → valid_until, year-rollover correct via isoWeekYear). The
      // currently-assigned one stays selectable so an edit isn't blocked.
      const endDate = record.valid_until
        ? dayjs(record.valid_until, dateFormat, true).isValid()
          ? dayjs(record.valid_until, dateFormat, true)
          : dayjs(record.valid_until, "YYYY-MM-DD", true)
        : rowDate.add(1, "year");
      const periodWeekKeys: string[] = [];
      let cursor = rowDate.startOf("isoWeek");
      const periodEnd = endDate.isValid() ? endDate : rowDate.add(1, "year");
      while (cursor.isSameOrBefore(periodEnd, "day")) {
        periodWeekKeys.push(`${cursor.isoWeekYear()}-${cursor.isoWeek()}`);
        cursor = cursor.add(1, "week");
      }

      return result.map((dsd) => {
        const isAssigned =
          dsd.value === record.default_delivery_station_day;
        // Peak occupancy across the row's period — the binding constraint and
        // what the greying (full in ANY week) keys off. Shown as (peak/total),
        // mirroring the per-week (occupied/total) label in ShareDeliveries.
        // SAME evaluator as the NewSubscriptionModal tag/waitlist flag — one
        // source of truth for "full for this term".
        const { total, peakOccupied, isFull } = stationDayTermCapacity(
          dsd.capacity,
          dsd.capacity_by_week,
          periodWeekKeys,
        );

        const label =
          total != null ? `${dsd.label} (${peakOccupied}/${total})` : dsd.label;

        return {
          ...dsd,
          label,
          // The currently-assigned station-day stays selectable even when full
          // so editing other fields on the row isn't blocked.
          disabled: isFull && !isAssigned,
        };
      });
    },
    [allDeliveryStationDays, parsedDeliveryStationDays, dateFormat],
  );

  return {
    data,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
    recentlyAddedIds,
    members,
    paymentCycles,
    allShareTypeVariations,
    variationDeliveryCycleById,
    getDeliveryStationDaysForRow,
  };
}
