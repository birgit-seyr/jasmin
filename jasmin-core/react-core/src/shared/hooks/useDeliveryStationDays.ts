import { useMemo } from 'react';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useCommissioningDeliveryStationsDaysList } from '@shared/api/generated/commissioning/commissioning';
import type { DeliveryStationDay, CommissioningDeliveryStationsDaysListParams } from '@shared/api/generated/models';
import { toOptions, type Option } from './internal/toOptions';

// ``capacity_by_week`` is fully typed on the generated model
// (Record<string, CapacityWeekEntry> | null), so no local shape is needed.
export type DeliveryStationDayOption = Option<DeliveryStationDay>;

type DeliveryStationDayParams = Partial<CommissioningDeliveryStationsDaysListParams>;

const DAY_KEYS = ['delivery.mo', 'delivery.di', 'delivery.mi', 'delivery.do', 'delivery.fr', 'delivery.sa', 'delivery.su'] as const;

/**
 * Localized weekday name for a delivery ``day_number`` (0=Mon … 6=Sun). Falls
 * back to the raw value when out of range. Exported so day-filter UIs and the
 * station-day option labels share one weekday-name source.
 */
export function deliveryDayLabel(
  t: TFunction,
  dayNumber: number | string | null | undefined,
): string {
  const key = DAY_KEYS[Number(dayNumber)];
  return key ? t(key) : String(dayNumber ?? '');
}

export const useDeliveryStationDays = (params: DeliveryStationDayParams = {}) => {
  const { t } = useTranslation();

  const mergedParams = useMemo(() => ({
    year: dayjs().year(),
    delivery_week: dayjs().isoWeek(),
    ...params,
  }), [params]);

  const { data, isLoading, error, refetch } = useCommissioningDeliveryStationsDaysList(
    mergedParams,
  );

  const deliveryStationDays: DeliveryStationDayOption[] = useMemo(
    () =>
      toOptions(
        data,
        (p) =>
          `${deliveryDayLabel(t, p.delivery_day_number)} - ${p.delivery_station_short_name}`,
      ),
    [data, t],
  );

  return {
    deliveryStationDays,
    loading: isLoading,
    error,
    refetch,
  };
};
