import { useMemo } from 'react';
import { useCommissioningSharesList } from '@shared/api/generated/commissioning/commissioning';
import type { Share } from '@shared/api/generated/models';
import dayjs from 'dayjs';

// Extend Share to account for nested fields the API actually returns.
// Share's generated type has `share_type_variation: string`, but the list
// endpoint serializes it as a nested object; use `Omit` so the override wins.
type ShareWithExtras = Omit<Share, "share_type_variation"> & {
  share_type_variation: string | { id: string; [key: string]: unknown };
  [key: string]: unknown;
};

type DayNumber = number | null | undefined;

const activityBelongsToPreviousWeek = (
  activityDay: DayNumber,
  deliveryDay: DayNumber,
) => {
  if (deliveryDay === null || deliveryDay === undefined) return false;
  return (activityDay as number) > (deliveryDay as number);
};

const extractDays = (
  dayField: string,
  shares: ShareWithExtras[],
  currentDeliveryWeek: number | undefined,
): number[] => {
  const days = new Set<number>();
  shares.forEach((share) => {
    const activityDay = (share as Record<string, unknown>)[dayField] as DayNumber;
    const deliveryDay = share.delivery_day_number;
    const isCurrentWeekDelivery = share.delivery_week === currentDeliveryWeek;
    if (activityDay != null) {
      if (
        isCurrentWeekDelivery &&
        !activityBelongsToPreviousWeek(activityDay, deliveryDay)
      ) {
        days.add(activityDay as number);
      } else if (
        !isCurrentWeekDelivery &&
        activityBelongsToPreviousWeek(activityDay, deliveryDay)
      ) {
        days.add(activityDay as number);
      }
    }
  });
  return Array.from(days).sort((a, b) => a - b);
};

export const useCurrentDays = (delivery_week?: number, year?: number) => {
  const enabled = !!(delivery_week && year);

  // Calculate next week and year
  const { nextWeek, nextYear } = useMemo(() => {
    if (!delivery_week || !year) return { nextWeek: 0, nextYear: 0 };
    const nextWeekDate = dayjs().year(year).isoWeek(delivery_week).add(1, 'week');
    return { nextWeek: nextWeekDate.isoWeek(), nextYear: nextWeekDate.year() };
  }, [delivery_week, year]);

  // Fetch current week shares
  const currentWeekQuery = useCommissioningSharesList(
    { delivery_week: delivery_week!, year: year! },
    { query: { enabled } },
  );

  // Fetch next week shares to get activity days that belong to current week
  const nextWeekQuery = useCommissioningSharesList(
    { delivery_week: nextWeek, year: nextYear },
    { query: { enabled } },
  );

  const loading = currentWeekQuery.isLoading || nextWeekQuery.isLoading;
  const error = currentWeekQuery.error || nextWeekQuery.error;
  const isLoaded = !loading && (currentWeekQuery.isFetched || !enabled);

  const currentDays = useMemo(() => {
    const current = (currentWeekQuery.data ?? []) as ShareWithExtras[];
    const next = (nextWeekQuery.data ?? []) as ShareWithExtras[];
    return [...current, ...next];
  }, [currentWeekQuery.data, nextWeekQuery.data]);

  const refetch = () => {
    currentWeekQuery.refetch();
    nextWeekQuery.refetch();
  };

  const dayNumbersPacking = useMemo(
    () => extractDays('packing_day', currentDays, delivery_week),
    [currentDays, delivery_week],
  );
  const dayNumbersHarvesting = useMemo(
    () => extractDays('harvesting_day', currentDays, delivery_week),
    [currentDays, delivery_week],
  );
  const dayNumbersWashing = useMemo(
    () => extractDays('washing_day', currentDays, delivery_week),
    [currentDays, delivery_week],
  );
  const dayNumbersCleaning = useMemo(
    () => extractDays('cleaning_day', currentDays, delivery_week),
    [currentDays, delivery_week],
  );

  // Extract delivery days (these should only come from current week)
  const dayNumbersDelivery = useMemo(() => {
    return [...new Set(currentDays
      .filter(share => share.delivery_week === delivery_week)
      .map(share => share.delivery_day_number)
      .filter((day): day is number => day != null)
    )].sort((a, b) => a - b);
  }, [currentDays, delivery_week]);

  const uniqueShareTypeVariations = useMemo(() => {
    const variationsMap = new Map<string, unknown>();
    currentDays.forEach(share => {
      const stv = share.share_type_variation;
      if (stv && typeof stv === 'object' && 'id' in stv) {
        variationsMap.set(stv.id, stv);
      }
    });
    return Array.from(variationsMap.values());
  }, [currentDays]);

  // Create lookup maps for activity-delivery relationships
  const dayLookupMaps = useMemo(() => {
    const packingToDelivery = new Map<number, Set<number>>();
    const deliveryToPacking = new Map<number, Set<number>>();
    const harvestingToDelivery = new Map<number, Set<number>>();
    const deliveryToHarvesting = new Map<number, Set<number>>();
    const washingToDelivery = new Map<number, Set<number>>();
    const deliveryToWashing = new Map<number, Set<number>>();
    const cleaningToDelivery = new Map<number, Set<number>>();
    const deliveryToCleaning = new Map<number, Set<number>>();

    const addRelationship = (fromMap: Map<number, Set<number>>, toMap: Map<number, Set<number>>, fromDay: DayNumber, toDay: DayNumber) => {
      if (fromDay != null && toDay != null) {
        if (!fromMap.has(fromDay)) fromMap.set(fromDay, new Set());
        fromMap.get(fromDay)!.add(toDay);
        if (!toMap.has(toDay)) toMap.set(toDay, new Set());
        toMap.get(toDay)!.add(fromDay);
      }
    };

    currentDays.forEach(share => {
      const rec = share as Record<string, unknown>;
      const packingDay = rec.packing_day as DayNumber;
      const harvestingDay = rec.harvesting_day as DayNumber;
      const washingDay = rec.washing_day as DayNumber;
      const cleaningDay = rec.cleaning_day as DayNumber;
      const deliveryDay = share.delivery_day_number;

      addRelationship(packingToDelivery, deliveryToPacking, packingDay, deliveryDay);
      addRelationship(harvestingToDelivery, deliveryToHarvesting, harvestingDay, deliveryDay);
      addRelationship(washingToDelivery, deliveryToWashing, washingDay, deliveryDay);
      addRelationship(cleaningToDelivery, deliveryToCleaning, cleaningDay, deliveryDay);
    });

    const convertSetsToArrays = (map: Map<number, Set<number>>) => {
      const result = new Map<number, number[]>();
      map.forEach((value, key) => {
        result.set(key, Array.from(value).sort((a, b) => a - b));
      });
      return result;
    };

    return {
      packingToDelivery: convertSetsToArrays(packingToDelivery),
      deliveryToPacking: convertSetsToArrays(deliveryToPacking),
      harvestingToDelivery: convertSetsToArrays(harvestingToDelivery),
      deliveryToHarvesting: convertSetsToArrays(deliveryToHarvesting),
      washingToDelivery: convertSetsToArrays(washingToDelivery),
      deliveryToWashing: convertSetsToArrays(deliveryToWashing),
      cleaningToDelivery: convertSetsToArrays(cleaningToDelivery),
      deliveryToCleaning: convertSetsToArrays(deliveryToCleaning),
    };
  }, [currentDays]);

  // Helper functions to get related days
  const getRelatedDays = useMemo(() => ({
    getDeliveryDaysForPacking: (packingDay: number) => dayLookupMaps.packingToDelivery.get(packingDay) || [],
    getPackingDaysForDelivery: (deliveryDay: number) => dayLookupMaps.deliveryToPacking.get(deliveryDay) || [],
    getDeliveryDaysForHarvesting: (harvestingDay: number) => dayLookupMaps.harvestingToDelivery.get(harvestingDay) || [],
    getHarvestingDaysForDelivery: (deliveryDay: number) => dayLookupMaps.deliveryToHarvesting.get(deliveryDay) || [],
    getDeliveryDaysForWashing: (washingDay: number) => dayLookupMaps.washingToDelivery.get(washingDay) || [],
    getWashingDaysForDelivery: (deliveryDay: number) => dayLookupMaps.deliveryToWashing.get(deliveryDay) || [],
    getDeliveryDaysForCleaning: (cleaningDay: number) => dayLookupMaps.cleaningToDelivery.get(cleaningDay) || [],
    getCleaningDaysForDelivery: (deliveryDay: number) => dayLookupMaps.deliveryToCleaning.get(deliveryDay) || [],
  }), [dayLookupMaps]);

  return {
    currentDays,
    dayNumbersPacking,
    dayNumbersDelivery,
    dayNumbersHarvesting,
    dayNumbersWashing,
    dayNumbersCleaning,
    uniqueShareTypeVariations,
    dayLookupMaps,
    getRelatedDays,
    loading,
    error,
    isLoaded,
    refetch,
  };
};