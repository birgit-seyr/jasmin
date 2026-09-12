import { message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toApiDate } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import {
  useCommissioningDeliveryToursList,
  useCommissioningDeliveryToursUpdateToursCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDeliveryToursListParams,
  CommissioningSharesDeliveryDaysListParams,
  DeliveryTourResponse,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { SharesDeliveryDaySelector } from "@features/commissioning/selectors";
import {
  AutoSaveIndicator,
  DateRangeStatusLegend,
  DndGrid,
  DraggableChip,
  DroppableCell,
  ExplainerText,
  usePastelColorMap,
} from "@shared/ui";
import type { DndDragPayload, GridPos } from "@shared/ui";
import {
  useDeliveryStations,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import type { DeliveryStationOption } from "@features/commissioning/hooks/useDeliveryStations";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";

type StationSlot = DeliveryStationOption | null;

// tourPlans is indexed [tourIndex (col)][positionIndex (row)]; a GridPos maps
// to tourPlans[pos.col][pos.row].
function buildTourData(tourPlans: StationSlot[][]) {
  return tourPlans
    .map((tour, tourIndex) => ({
      tour_number: tourIndex + 1,
      positions: tour
        .map((station, positionIndex) =>
          station
            ? { position: positionIndex + 1, delivery_station_id: station.value }
            : null,
        )
        .filter(Boolean) as { position: number; delivery_station_id: string }[],
    }))
    .filter((tour) => tour.positions.length > 0);
}

export default function DeliveryTours() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [numberOfTours, setNumberOfTours] = useState(1);

  const deliveryStationsFilters = useMemo(() => {
    return selectedDay !== null ? { delivery_day: selectedDay } : {};
  }, [selectedDay]);
  const { deliveryStations } = useDeliveryStations(deliveryStationsFilters);

  // Ref to avoid putting deliveryStations in the transform/handler deps (the
  // hook returns a new array ref every render).
  const deliveryStationsRef = useRef<DeliveryStationOption[]>([]);
  deliveryStationsRef.current = deliveryStations;

  const [tourPlans, setTourPlans] = useState<StationSlot[][]>([[], []]);

  useEffect(() => {
    if (deliveryStations.length > 0) {
      const totalPositions = deliveryStations.length + 5;
      setTourPlans((prev) =>
        Array(numberOfTours)
          .fill(null)
          .map((_, tourIndex) =>
            Array(totalPositions)
              .fill(null)
              .map((_, i) => prev[tourIndex]?.[i] || null),
          ),
      );
    }
  }, [deliveryStations.length, selectedDay, numberOfTours]);

  const assignedStationIds = useMemo(() => {
    const assignedIds = new Set<string>();
    tourPlans.forEach((tour) => {
      tour.forEach((station) => {
        if (station) {
          assignedIds.add(station.value);
        }
      });
    });
    return assignedIds;
  }, [tourPlans]);

  const stationIds = useMemo(
    () => deliveryStations.map((station) => station.value),
    [deliveryStations],
  );
  const stationColorMap = usePastelColorMap(stationIds);

  const listParams = useMemo<CommissioningDeliveryToursListParams>(
    () => ({
      delivery_day: selectedDay!,
    }),
    [selectedDay],
  );

  const shareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({ active_at_date: toApiDate(dayjs())! }),
      [],
    );
  const futureShareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({ active_at_date: toApiDate(dayjs())!, future: true }),
      [],
    );

  const {
    shareDeliveryDays: currentlyActiveDeliveryDays,
    toursByDay: currentToursByDay,
  } = useShareDeliveryDays(shareDeliveryDaysParams);

  const { shareDeliveryDays: futureDeliveryDays, toursByDay: futureToursByDay } =
    useShareDeliveryDays(futureShareDeliveryDaysParams);

  const shareDeliveryDays = useMemo(() => {
    return [
      ...(currentlyActiveDeliveryDays || []),
      ...(futureDeliveryDays || []),
    ];
  }, [currentlyActiveDeliveryDays, futureDeliveryDays]);

  // Make distinct by day_number, prioritizing records with valid_until null/blank
  const distinctShareDeliveryDays = useMemo(() => {
    const dayNumberMap = new Map<
      number | string | undefined,
      ShareDeliveryDayOption
    >();

    shareDeliveryDays.forEach((day) => {
      const existing = dayNumberMap.get(day.day_number);

      if (!existing) {
        dayNumberMap.set(day.day_number, day);
      } else {
        const currentHasNoValidUntil = !day.valid_until;
        const existingHasNoValidUntil = !existing.valid_until;

        if (currentHasNoValidUntil && !existingHasNoValidUntil) {
          dayNumberMap.set(day.day_number, day);
        }
      }
    });

    return Array.from(dayNumberMap.values());
  }, [shareDeliveryDays]);

  useEffect(() => {
    if (distinctShareDeliveryDays.length > 0 && selectedDay === null) {
      setSelectedDay(distinctShareDeliveryDays[0].id ?? null);
    }
  }, [distinctShareDeliveryDays, selectedDay]);

  useEffect(() => {
    // Merge toursByDay: prefer current, fallback to future
    const mergedToursByDay = { ...futureToursByDay, ...currentToursByDay };

    if (Object.keys(mergedToursByDay).length > 0 && selectedDay) {
      const tours = mergedToursByDay[selectedDay] || 1;
      setNumberOfTours(tours);
    } else {
      setNumberOfTours(2);
    }
  }, [selectedDay, currentToursByDay, futureToursByDay]);

  // Filter out already assigned stations
  const availableStations = useMemo(() => {
    return deliveryStations.filter(
      (station) => !assignedStationIds.has(station.value),
    );
  }, [deliveryStations, assignedStationIds]);

  const { data: toursData, refetch: refetchTours } =
    useCommissioningDeliveryToursList(listParams, {
      query: {
        enabled: !!selectedDay,
      },
    });

  // Transform API response into tour plans
  useEffect(() => {
    const stations = deliveryStationsRef.current;
    if (!toursData || stations.length === 0) return;

    const tours = toursData as DeliveryTourResponse[];
    const maxPositions = (stations.length || 10) + 5;
    const emptyTourPlans: StationSlot[][] = Array(numberOfTours)
      .fill(null)
      .map(() => Array(maxPositions).fill(null));

    if (tours && tours.length > 0) {
      tours.forEach((tour) => {
        const tourIndex = tour.tour_number - 1;
        if (tourIndex >= 0 && tourIndex < emptyTourPlans.length) {
          tour.positions.forEach((position) => {
            const positionIndex = position.position - 1;
            if (
              positionIndex >= 0 &&
              positionIndex < emptyTourPlans[tourIndex].length
            ) {
              const station = stations.find(
                (s) => s.value === position.delivery_station_id,
              );
              if (station) {
                emptyTourPlans[tourIndex][positionIndex] = station;
              }
            }
          });
        }
      });
    }

    setTourPlans(emptyTourPlans);
  }, [toursData, numberOfTours, deliveryStations.length]);

  // Auto-save via TanStack mutation. The grid is optimistic local state; on a
  // failure we surface it AND refetch so the UI can't keep showing a plan that
  // wasn't persisted. The whole-day payload is a full replace, so last write wins.
  const { mutate: saveTours, isPending: isSaving } =
    useCommissioningDeliveryToursUpdateToursCreate({
      mutation: {
        onError: (error) => {
          message.error(
            getErrorMessage(error, t("commissioning.tour_save_failed")),
          );
          refetchTours();
        },
      },
    });

  // Only a genuine user edit (place / remove / move) should POST. The other
  // writers of tourPlans — padding the grid when the station or tour count
  // changes, and loading the saved plan from the API — must NOT trigger a
  // save. A ref the edit handlers set flags real edits, rather than trying to
  // time-gate the load/reshape effects (which is racy).
  const userEditedRef = useRef(false);

  useEffect(() => {
    if (!userEditedRef.current) return;
    userEditedRef.current = false;
    if (!selectedDay) return;
    saveTours({
      data: { delivery_day: selectedDay, tours: buildTourData(tourPlans) },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tourPlans]);

  // Place a chip: from the palette (unique — clears any existing copy) or moved
  // between cells (swaps if the target is occupied).
  const handlePlace = useCallback((payload: DndDragPayload, to: GridPos) => {
    userEditedRef.current = true;
    setTourPlans((prev) => {
      const next = prev.map((tour) => [...tour]);
      if (payload.from) {
        const moved = next[payload.from.col]?.[payload.from.row] ?? null;
        const target = next[to.col]?.[to.row] ?? null;
        if (next[payload.from.col]) {
          next[payload.from.col][payload.from.row] = null;
        }
        if (next[to.col]) {
          next[to.col][to.row] = moved;
        }
        if (target && next[payload.from.col]) {
          next[payload.from.col][payload.from.row] = target;
        }
      } else {
        const station = deliveryStationsRef.current.find(
          (s) => s.value === payload.chip.id,
        );
        if (!station) return prev;
        next.forEach((tour, col) =>
          tour.forEach((slot, row) => {
            if (slot && slot.value === station.value) {
              next[col][row] = null;
            }
          }),
        );
        if (next[to.col]) {
          next[to.col][to.row] = station;
        }
      }
      return next;
    });
  }, []);

  const handleRemove = useCallback((pos: GridPos) => {
    userEditedRef.current = true;
    setTourPlans((prev) => {
      const next = prev.map((tour) => [...tour]);
      if (next[pos.col]) {
        next[pos.col][pos.row] = null;
      }
      return next;
    });
  }, []);

  const tableWidth = `${numberOfTours * 15 + 5}em`;

  return (
    <DndGrid onPlace={handlePlace} onRemove={handleRemove}>
      <div className="delivery-tours-page">
        <h1>{t("commissioning.delivery_tours")}</h1>

        <SharesDeliveryDaySelector
          selectedSharesDeliveryDay={selectedDay}
          setSelectedSharesDeliveryDay={setSelectedDay}
          onSharesDeliveryDayChange={setSelectedDay}
          preserveSelection={true}
        />
        <DateRangeStatusLegend />

        <div className="delivery-tours-layout">
          {/* Available Delivery Stations */}
          <div className="delivery-tours-palette">
            <h3>{t("commissioning.available_delivery_stations")}</h3>
            <div className="delivery-tours-palette-box">
              {availableStations.length === 0 ? (
                <p className="text-muted text-center">
                  {deliveryStations.length === 0
                    ? t("commissioning.no_stations_available")
                    : t("commissioning.all_stations_assigned")}
                </p>
              ) : (
                availableStations.map((station) => (
                  <DraggableChip
                    key={station.value}
                    chip={{
                      id: station.value,
                      label: station.label,
                      color: stationColorMap.get(station.value),
                    }}
                    canDrag={isOffice}
                  />
                ))
              )}
            </div>
          </div>

          {/* Tour Planning Table */}
          <div className="flex-1">
            <div className="flex-between">
              <h3>{t("commissioning.tour_planning")}</h3>
              <AutoSaveIndicator saving={isSaving} hasChanges={false} />
            </div>

            <table
              className="delivery-tours-grid-table"
              style={{ width: tableWidth }}
            >
              <thead>
                <tr>
                  <th className="delivery-tours-th-position">
                    {t("delivery_stations.position")}
                  </th>
                  {Array.from({ length: numberOfTours }, (_, index) => (
                    <th key={`tour-${index}`} className="delivery-tours-th-tour">
                      {t("commissioning.tour_label", { number: index + 1 })}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tourPlans[0]?.map((_, positionIndex) => (
                  <tr key={positionIndex}>
                    <td className="delivery-tours-pos-number">
                      {positionIndex + 1}
                    </td>
                    {Array.from({ length: numberOfTours }, (_, tourIndex) => {
                      const station =
                        tourPlans[tourIndex]?.[positionIndex] ?? null;
                      return (
                        <td key={`tour-${tourIndex}`} className="delivery-tours-cell">
                          <DroppableCell
                            pos={{ row: positionIndex, col: tourIndex }}
                            occupant={
                              station
                                ? {
                                    id: station.value,
                                    label: station.label,
                                    color: stationColorMap.get(station.value),
                                  }
                                : null
                            }
                            canEdit={isOffice}
                            emptyLabel={t("commissioning.drop_station_here")}
                            removeAriaLabelFor={(label) =>
                              t("commissioning.remove_station", { station: label })
                            }
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <ExplainerText title={t("common.info")}>
          {t("explainers.delivery_tours")}
        </ExplainerText>
      </div>
    </DndGrid>
  );
}
