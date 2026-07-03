import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useCommissioningSharesDeliveryDaysList } from '@shared/api/generated/commissioning/commissioning';
import type { SharesDeliveryDay, CommissioningSharesDeliveryDaysListParams } from '@shared/api/generated/models';
import { toOptions, type Option } from '@hooks/internal/toOptions';

export type ShareDeliveryDayOption = Option<SharesDeliveryDay>;

const DAY_KEYS = ['delivery.mo', 'delivery.di', 'delivery.mi', 'delivery.do', 'delivery.fr', 'delivery.sa', 'delivery.su'] as const;

// currently and future available delivery_days
export const useShareDeliveryDays = (params: CommissioningSharesDeliveryDaysListParams = {}) => {
  const { t } = useTranslation();

  const { data, isLoading, error, refetch } = useCommissioningSharesDeliveryDaysList(params);

  const shareDeliveryDays: ShareDeliveryDayOption[] = useMemo(() => {
    let filteredData = data ?? [];

    // Filter out options with empty delivery stations if get_delivery_stations param is present
    if (params.get_delivery_stations) {
      filteredData = filteredData.filter(day =>
        day.delivery_stations &&
        Array.isArray(day.delivery_stations) &&
        day.delivery_stations.length > 0
      );
    }

    return toOptions(filteredData, (day) =>
      DAY_KEYS[day.day_number as number]
        ? t(DAY_KEYS[day.day_number as number])
        : String(day.day_number),
    );
  }, [data, params.get_delivery_stations, t]);

  const dayNumbers = useMemo(() => {
    return shareDeliveryDays.map(day => day.day_number);
  }, [shareDeliveryDays]);

  const toursByDay = useMemo(() => {
    const toursMap: Record<string, number> = {};
    shareDeliveryDays.forEach(day => {
      toursMap[day.id!] = day.number_of_tours || 1;
    });
    return toursMap;
  }, [shareDeliveryDays]);

  return {
    shareDeliveryDays,
    dayNumbers,
    shareDeliveryDaysCount: shareDeliveryDays.length,
    toursExist: shareDeliveryDays.some(day => (day.number_of_tours ?? 0) > 1),
    toursByDay,
    loading: isLoading,
    error,
    refetch,
  };
};