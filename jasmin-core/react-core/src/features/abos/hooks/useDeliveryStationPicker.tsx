/**
 * The delivery-station picker's presentation for the new-subscription flow:
 * the Select's options and the map's markers.
 *
 * Both views answer the same question — is this station-day full for the
 * chosen term? — so the fullness is computed ONCE per station-day here and
 * fed to both, rather than evaluated twice from the same inputs.
 */

import { Button, Flex } from "antd";
import type { FormInstance } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { DeliveryStationDayOption } from "@hooks/useDeliveryStationDays";
import type { DeliveryStationMapMarker } from "@shared/ui";
import { stationDayTermCapacity } from "../utils/stationCapacity";

/** One station-day's fullness for the term, as both views render it. */
interface StationDayCapacity {
  /** Station-day capacity (null = unlimited / unknown). */
  total: number | null;
  /** Tightest term week's free slots (null when unknown). */
  free: number | null;
  isFull: boolean;
}

/** A station-day as the Select renders it — ``optionRender`` reads ``total`` /
 *  ``free`` / ``isFull`` back off ``option.data``. */
export interface StationDayOption extends StationDayCapacity {
  value: string;
  label: string;
  disabled: boolean;
}

export interface DeliveryStationPickerParams {
  deliveryStationDays: DeliveryStationDayOption[];
  /** Every ``"<iso-year>-<iso-week>"`` key in the subscription's term. */
  periodWeekKeys: string[];
  /** Shares the order needs — the fullness check is quantity-aware. */
  quantity: number;
  /** Capacity is only DEFINED relative to a known term, and only applies to
   *  standalone shares — false means make no capacity claims at all. */
  showCapacity: boolean;
  allowsWaitingList: boolean;
  /** Member self-service or public registration (the simplified view). */
  simplified: boolean;
  /** Narrows both views to a single delivery weekday. */
  dayFilter: number | "all";
  /** The picked ``default_delivery_station_day``, for the marker highlight. */
  selectedStationDay: string | undefined;
  /** The details form — the popup's day buttons write the picked station-day
   *  into the same field the Select drives. */
  form: FormInstance;
}

export interface DeliveryStationPicker {
  stationOptions: StationDayOption[];
  stationMarkers: DeliveryStationMapMarker[];
}

export function useDeliveryStationPicker({
  deliveryStationDays,
  periodWeekKeys,
  quantity,
  showCapacity,
  allowsWaitingList,
  simplified,
  dayFilter,
  selectedStationDay,
  form,
}: DeliveryStationPickerParams): DeliveryStationPicker {
  const { t } = useTranslation();

  // Fullness from the RAW station-days — the member-filtered options below
  // drop full days, so deriving the map from those would let a hidden full day
  // reappear on the map reading as available.
  const capacityByStationDay = useMemo(() => {
    const byStationDay = new Map<string, StationDayCapacity>();
    for (const stationDay of deliveryStationDays) {
      const { total, minFree, isFull } = showCapacity
        ? stationDayTermCapacity(
            stationDay.capacity,
            stationDay.capacity_by_week,
            periodWeekKeys,
            quantity,
          )
        : { total: null, minFree: null, isFull: false };
      byStationDay.set(stationDay.value, { total, free: minFree, isFull });
    }
    return byStationDay;
  }, [deliveryStationDays, showCapacity, periodWeekKeys, quantity]);

  // Station options: the smaller secondary line shows the tightest term week's
  // free slots as "freie Plätze (free/total)".
  const stationOptions = useMemo<StationDayOption[]>(() => {
    const options = deliveryStationDays
      .filter(
        (stationDay) =>
          dayFilter === "all" ||
          Number(stationDay.delivery_day_number) === dayFilter,
      )
      .map((stationDay) => {
        const capacity = capacityByStationDay.get(stationDay.value);
        const isFull = capacity?.isFull ?? false;
        return {
          value: stationDay.value,
          label: stationDay.label,
          total: capacity?.total ?? null,
          free: capacity?.free ?? null,
          isFull,
          // Office sees a full station greyed when the waiting list is off.
          disabled: !allowsWaitingList && isFull,
        };
      });
    // Members / public don't see full stations at all when the list is off.
    if (simplified && !allowsWaitingList) {
      return options.filter((option) => !option.isFull);
    }
    return options;
  }, [
    deliveryStationDays,
    capacityByStationDay,
    allowsWaitingList,
    simplified,
    dayFilter,
  ]);

  // Map markers: ONE per delivery station (a station can host several days).
  // Only stations with coordinates appear; the popup lists that station's days
  // as buttons that set the same ``default_delivery_station_day`` field the
  // Select drives. A station is greyed only when EVERY one of its days is full.
  const stationMarkers = useMemo<DeliveryStationMapMarker[]>(() => {
    const byStation = new Map<
      string,
      {
        stationId: string;
        lat: number;
        lon: number;
        name: string;
        days: {
          value: string;
          label: string;
          free: number | null;
          total: number | null;
          isFull: boolean;
        }[];
      }
    >();

    for (const stationDay of deliveryStationDays) {
      // Mirror the Select's day filter so the map shows the same stations.
      if (
        dayFilter !== "all" &&
        Number(stationDay.delivery_day_number) !== dayFilter
      ) {
        continue;
      }
      const lat =
        stationDay.coords_lat != null ? Number(stationDay.coords_lat) : NaN;
      const lon =
        stationDay.coords_lon != null ? Number(stationDay.coords_lon) : NaN;
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;

      const stationId = String(stationDay.delivery_station ?? "");
      if (!stationId) continue;
      const capacity = capacityByStationDay.get(stationDay.value);
      // Members / public don't see full stations at all when the list is off.
      if (simplified && !allowsWaitingList && capacity?.isFull) continue;
      const entry = byStation.get(stationId) ?? {
        stationId,
        lat,
        lon,
        name:
          stationDay.delivery_station_name ??
          stationDay.delivery_station_short_name ??
          "",
        days: [],
      };
      entry.days.push({
        value: stationDay.value,
        label: stationDay.label,
        free: capacity?.free ?? null,
        total: capacity?.total ?? null,
        isFull: capacity?.isFull ?? false,
      });
      byStation.set(stationId, entry);
    }

    return Array.from(byStation.values())
      .filter((station) => station.days.length > 0)
      .map((station) => ({
        id: station.stationId,
        lat: station.lat,
        lon: station.lon,
        label: station.name,
        selected: station.days.some((day) => day.value === selectedStationDay),
        disabled: station.days.every((day) => day.isFull),
        popup: (
          <div>
            <strong>{station.name}</strong>
            <Flex vertical gap={4} style={{ marginTop: 8 }}>
              {station.days.map((day) => (
                <Button
                  key={day.value}
                  size="small"
                  // Office sees a full day greyed when the waiting list is off.
                  disabled={!allowsWaitingList && day.isFull}
                  type={
                    day.value === selectedStationDay ? "primary" : "default"
                  }
                  onClick={() =>
                    form.setFieldsValue({
                      default_delivery_station_day: day.value,
                    })
                  }
                >
                  {day.label}
                  {day.isFull
                    ? ` · ${t("abos.station_full_waiting_list")}`
                    : day.total != null && day.free != null
                      ? ` · ${t("delivery.free_spots_of_total", {
                          free: day.free,
                          total: day.total,
                        })}`
                      : ""}
                </Button>
              ))}
            </Flex>
          </div>
        ),
      }));
  }, [
    deliveryStationDays,
    capacityByStationDay,
    allowsWaitingList,
    simplified,
    selectedStationDay,
    dayFilter,
    form,
    t,
  ]);

  return { stationOptions, stationMarkers };
}
