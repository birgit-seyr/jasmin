import { useMemo } from 'react';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import { useCommissioningDeliveryStationsDaysList } from '@shared/api/generated/commissioning/commissioning';
import type { DeliveryStationDay, CommissioningDeliveryStationsDaysListParams } from '@shared/api/generated/models';
import { toOptions, type Option } from './internal/toOptions';

// ``capacity_by_week`` is fully typed on the generated model
// (Record<string, CapacityWeekEntry> | null), so no local shape is needed.
export type DeliveryStationDayOption = Option<DeliveryStationDay>;

type DeliveryStationDayParams = Partial<CommissioningDeliveryStationsDaysListParams>;

const DAY_KEYS = ['delivery.mo', 'delivery.di', 'delivery.mi', 'delivery.do', 'delivery.fr', 'delivery.sa', 'delivery.su'] as const;

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
      toOptions(data, (p) =>
        `${
          DAY_KEYS[Number(p.delivery_day_number)]
            ? t(DAY_KEYS[Number(p.delivery_day_number)])
            : p.delivery_day_number
        } - ${p.delivery_station_short_name}`,
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
