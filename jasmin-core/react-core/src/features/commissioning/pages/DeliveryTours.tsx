import dayjs from "dayjs";
import { toApiDate } from "@shared/utils";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DndProvider, useDrag, useDrop } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { useTranslation } from "react-i18next";
import {
  commissioningDeliveryToursUpdateToursCreate,
  useCommissioningDeliveryToursList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDeliveryToursListParams,
  CommissioningSharesDeliveryDaysListParams,
  DeliveryTourResponse,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { SharesDeliveryDaySelector } from '@features/commissioning/selectors';
import { DateRangeStatusLegend } from "@shared/ui";
import { useDeliveryStations, useShareDeliveryDays } from '@features/commissioning/hooks';
import type { DeliveryStationOption } from "@features/commissioning/hooks/useDeliveryStations";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";

// Drag item types
const ItemTypes = {
  DELIVERY_STATION: "delivery_station",
};

interface DragItem {
  station: DeliveryStationOption;
  fromPosition?: { tourIndex: number; positionIndex: number };
}

type StationSlot = DeliveryStationOption | null;

const PASTEL_COLORS = [
  "#FFE5E5",
  "#E5F3FF",
  "#E5FFE5",
  "#FFF5E5",
  "#F0E5FF",
  "#E5FFFF",
  "#FFFFE5",
  "#FFE5F5",
  "#F5FFE5",
  "#E5F0FF",
  "#FFE5CC",
  "#E5CCFF",
];

const generatePastelColor = (index: number): string => {
  return PASTEL_COLORS[index % PASTEL_COLORS.length];
};

// Drop zone for tour positions - also draggable
interface TourPositionProps {
  tourIndex: number;
  positionIndex: number;
  station: StationSlot;
  onDrop: (
    tourIndex: number,
    positionIndex: number,
    station: DeliveryStationOption,
  ) => void;
  onRemove: (tourIndex: number, positionIndex: number) => void;
  onDragFromPosition: (
    fromTourIndex: number,
    fromPositionIndex: number,
    toTourIndex: number,
    toPositionIndex: number,
  ) => void;
  isSaving: boolean;
  backgroundColor: string | null;
}

const TourPosition = ({
  tourIndex,
  positionIndex,
  station,
  onDrop,
  onRemove,
  onDragFromPosition,
  isSaving,
  backgroundColor,
}: TourPositionProps) => {
  const [{ isOver }, drop] = useDrop<DragItem, void, { isOver: boolean }>(
    () => ({
      accept: ItemTypes.DELIVERY_STATION,
      drop: (item) => {
        if (item.fromPosition) {
          onDragFromPosition(
            item.fromPosition.tourIndex,
            item.fromPosition.positionIndex,
            tourIndex,
            positionIndex,
          );
        } else {
          onDrop(tourIndex, positionIndex, item.station);
        }
      },
      collect: (monitor) => ({
        isOver: monitor.isOver(),
      }),
    }),
    [tourIndex, positionIndex, onDragFromPosition, onDrop],
  );

  const [{ isDragging }, drag] = useDrag<
    DragItem,
    void,
    { isDragging: boolean }
  >(
    {
      type: ItemTypes.DELIVERY_STATION,
      item: station
        ? {
            station,
            fromPosition: { tourIndex, positionIndex },
          }
        : ({ station: null as unknown as DeliveryStationOption } as DragItem),
      canDrag: !!station && !isSaving,
      collect: (monitor) => ({
        isDragging: monitor.isDragging(),
      }),
    },
    [station, tourIndex, positionIndex, isSaving],
  );

  const { t } = useTranslation();

  // Combine drag and drop refs
  const dragDropRef = useCallback(
    (node: HTMLDivElement | null) => {
      drag(node);
      drop(node);
    },
    [drag, drop],
  );

  return (
    <div
      ref={dragDropRef}
      className={`tour-position ${isOver ? "drop-over" : ""} ${
        isDragging ? "dragging" : ""
      } flex-between`}
      style={{
        height: "40px",
        padding: "8px",
        border: "2px dashed #ccc",
        borderColor: isOver ? "#007bff" : "var(--color-text-tertiary)",
        backgroundColor: isOver
          ? "#f0f8ff"
          : station
            ? backgroundColor || "#e8f5e9"
            : "var(--color-bg-elevated)",
        borderRadius: "4px",
        opacity: isSaving ? 0.7 : isDragging ? 0.5 : 1,
        cursor: station && !isSaving ? "move" : "default",
      }}
    >
      {station ? (
        <>
          <span>{station.label}</span>
          <button
            onClick={() => onRemove(tourIndex, positionIndex)}
            disabled={isSaving}
            aria-label={t("commissioning.remove_station", {
              station: station.label,
            })}
            className="text-error"
            style={{
              background: "none",
              border: "none",
              cursor: isSaving ? "not-allowed" : "pointer",
              fontSize: "16px",
            }}
          >
            ×
          </button>
        </>
      ) : (
        <span className="text-muted">
          {t("commissioning.drop_station_here")}
        </span>
      )}
    </div>
  );
};

// Draggable station in the available stations list
interface DraggableStationProps {
  station: DeliveryStationOption;
  onDragEnd: (station: DeliveryStationOption) => void;
  backgroundColor: string | undefined;
  canDrag?: boolean;
}

const DraggableStation = ({
  station,
  onDragEnd,
  backgroundColor,
  canDrag = true,
}: DraggableStationProps) => {
  const [{ isDragging }, drag] = useDrag<
    DragItem,
    void,
    { isDragging: boolean }
  >(
    () => ({
      type: ItemTypes.DELIVERY_STATION,
      item: { station },
      canDrag,
      end: (item, monitor) => {
        if (monitor.didDrop() && item) {
          onDragEnd(item.station);
        }
      },
      collect: (monitor) => ({
        isDragging: monitor.isDragging(),
      }),
    }),
    [station, canDrag, onDragEnd],
  );

  return (
    <div
      ref={(node) => {
        drag(node);
      }}
      className={`delivery-station-item ${isDragging ? "dragging" : ""}`}
      style={{
        padding: "8px 12px",
        margin: "4px 0",
        backgroundColor: backgroundColor || "var(--color-bg-subtle)",
        border: "1px solid var(--color-border-soft)",
        borderRadius: "4px",
        cursor: "move",
        opacity: isDragging ? 0.5 : 1,
      }}
    >
      {station.label}
    </div>
  );
};

export default function DeliveryTours() {
  const { isOffice } = useRoles();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [, setSaveStatus] = useState<"" | "saving" | "success" | "error">("");
  const [numberOfTours, setNumberOfTours] = useState(1);

  const deliveryStationsFilters = useMemo(() => {
    return selectedDay !== null ? { delivery_day: selectedDay } : {};
  }, [selectedDay]);
  const { deliveryStations } = useDeliveryStations(deliveryStationsFilters);

  // Ref to avoid putting deliveryStations in transform effect deps (the hook returns a new array ref every render)
  const deliveryStationsRef = useRef<DeliveryStationOption[]>([]);
  deliveryStationsRef.current = deliveryStations;

  // Tour planning state
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

  const { t } = useTranslation();

  const stationColorMap = useMemo(() => {
    const colorMap = new Map<string, string>();
    deliveryStations.forEach((station, index) => {
      colorMap.set(station.value, generatePastelColor(index));
    });
    return colorMap;
  }, [deliveryStations]);

  const listParams = useMemo<CommissioningDeliveryToursListParams>(
    () => ({
      delivery_day: selectedDay!,
    }),
    [selectedDay],
  );

  const shareDeliveryDaysParams = useMemo<CommissioningSharesDeliveryDaysListParams>(
    () => ({ active_at_date: toApiDate(dayjs())! }),
    [],
  );
  const futureShareDeliveryDaysParams = useMemo<CommissioningSharesDeliveryDaysListParams>(
    () => ({ active_at_date: toApiDate(dayjs())!, future: true }),
    [],
  );

  const {
    shareDeliveryDays: currentlyActiveDeliveryDays,
    toursByDay: currentToursByDay,
  } = useShareDeliveryDays(shareDeliveryDaysParams);

  const {
    shareDeliveryDays: futureDeliveryDays,
    toursByDay: futureToursByDay,
  } = useShareDeliveryDays(futureShareDeliveryDaysParams);

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

  const { data: toursData } = useCommissioningDeliveryToursList(listParams, {
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

  // Auto-save tour plans to backend
  const autoSaveTourPlans = useCallback(
    async (updatedTourPlans: StationSlot[][]) => {
      if (!selectedDay) return;
      const tourData = updatedTourPlans
        .map((tour, tourIndex) => ({
          tour_number: tourIndex + 1,
          positions: tour
            .map((station, positionIndex) =>
              station
                ? {
                    position: positionIndex + 1,
                    delivery_station_id: station.value,
                  }
                : null,
            )
            .filter(Boolean),
        }))
        .filter((tour) => tour.positions.length > 0);

      try {
        setIsSaving(true);
        setSaveStatus("saving");

        await commissioningDeliveryToursUpdateToursCreate({
          delivery_day: selectedDay!,
          tours: tourData as {
            tour_number: number;
            positions: { position: number; delivery_station_id: string }[];
          }[],
        });

        setSaveStatus("success");
        setTimeout(() => setSaveStatus(""), 3000);
      } catch (error) {
        console.error("Failed to save tour plans:", error);
        setSaveStatus("error");
        setTimeout(() => setSaveStatus(""), 3000);
      } finally {
        setIsSaving(false);
      }
    },
    [selectedDay],
  );

  // Only a genuine user edit (drop / remove / reorder) should POST. The other
  // writers of tourPlans — padding the grid when the station or tour count
  // changes, and loading the saved plan from the API — must NOT trigger a
  // save. We flag real edits with a ref the user handlers set, rather than
  // trying to time-gate the load/reshape effects (which is racy: a queued
  // microtask flips before React's deferred passive effect runs).
  const userEditedRef = useRef(false);

  useEffect(() => {
    if (!userEditedRef.current) return;
    userEditedRef.current = false;
    autoSaveTourPlans(tourPlans);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tourPlans]);

  // Handle dropping a station into a tour position
  const handleDrop = useCallback(
    (
      tourIndex: number,
      positionIndex: number,
      station: DeliveryStationOption,
    ) => {
      userEditedRef.current = true;
      setTourPlans((prev) => {
        const newPlans = prev.map((tour) => [...tour]);

        // Remove station from its current position if it exists
        newPlans.forEach((tour, tIndex) => {
          tour.forEach((pos, pIndex) => {
            if (pos && pos.value === station.value) {
              newPlans[tIndex][pIndex] = null;
            }
          });
        });

        // Add station to new position
        newPlans[tourIndex][positionIndex] = station;

        return newPlans;
      });
    },
    [],
  );

  // Handle removing a station from a tour position
  const handleRemove = useCallback(
    (tourIndex: number, positionIndex: number) => {
      const station = tourPlans[tourIndex][positionIndex];
      if (station) {
        userEditedRef.current = true;
        setTourPlans((prev) => {
          const newPlans = prev.map((tour) => [...tour]);
          newPlans[tourIndex][positionIndex] = null;
          return newPlans;
        });
      }
    },
    [tourPlans],
  );

  const handleDragFromPosition = useCallback(
    (
      fromTourIndex: number,
      fromPositionIndex: number,
      toTourIndex: number,
      toPositionIndex: number,
    ) => {
      const station = tourPlans[fromTourIndex]?.[fromPositionIndex];
      if (station) {
        userEditedRef.current = true;
        setTourPlans((prev) => {
          const newPlans = prev.map((tour) => [...tour]);

          const targetStation = newPlans[toTourIndex][toPositionIndex];

          newPlans[fromTourIndex][fromPositionIndex] = null;
          newPlans[toTourIndex][toPositionIndex] = station;

          if (targetStation) {
            newPlans[fromTourIndex][fromPositionIndex] = targetStation;
          }

          return newPlans;
        });
      }
    },
    [tourPlans],
  );

  const handleStationDragEnd = useCallback(() => {
    // Station will be handled by drop zones
  }, []);

  const tableWidth = `${numberOfTours * 15 + 5}em`;
  const tableContainerStyle: CSSProperties = {
    width: tableWidth,
    borderCollapse: "collapse",
    marginTop: "0em",
  };

  return (
    <DndProvider backend={HTML5Backend}>
      <div style={{ padding: "20px" }}>
        <h1>{t("commissioning.delivery_tours")}</h1>

        <SharesDeliveryDaySelector
          selectedSharesDeliveryDay={selectedDay}
          setSelectedSharesDeliveryDay={setSelectedDay}
          onSharesDeliveryDayChange={setSelectedDay}
          preserveSelection={true}
        />
        <DateRangeStatusLegend />

        <div style={{ display: "flex", gap: "20px", marginTop: "2em" }}>
          {/* Available Delivery Stations */}
          <div style={{ flex: "0 0 15em" }}>
            <h3>{t("commissioning.available_delivery_stations")}</h3>
            <div
              style={{
                border: "1px solid var(--color-border-soft)",
                borderRadius: "4px",
                padding: "1em",
                maxHeight: "100em",
                overflowY: "auto",
                opacity: isSaving ? 0.7 : 1,
              }}
            >
              {availableStations.length === 0 ? (
                <p className="text-muted text-center">
                  {deliveryStations.length === 0
                    ? t("commissioning.no_stations_available")
                    : t("commissioning.all_stations_assigned")}
                </p>
              ) : (
                availableStations.map((station) => (
                  <DraggableStation
                    key={station.value}
                    station={station}
                    onDragEnd={handleStationDragEnd}
                    backgroundColor={stationColorMap.get(station.value)}
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
            </div>

            <table style={tableContainerStyle}>
              <thead>
                <tr>
                  <th
                    style={{
                      border: "1px solid var(--color-border-soft)",
                      padding: "8px",
                      backgroundColor: "#f8f9fa",
                      width: "5em",
                    }}
                  >
                    {t("delivery_stations.position")}
                  </th>
                  {Array.from({ length: numberOfTours }, (_, index) => (
                    <th
                      key={`tour-${index}`}
                      style={{
                        border: "1px solid var(--color-border-soft)",
                        padding: "0.5em",
                        backgroundColor: "#f8f9fa",
                        width: "14em",
                      }}
                    >
                      Tour {index + 1}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tourPlans[0]?.map((_, positionIndex) => (
                  <tr key={positionIndex}>
                    <td
                      style={{
                        border: "1px solid var(--color-border-soft)",
                        padding: "8px",
                        textAlign: "center",
                        fontWeight: "bold",
                      }}
                    >
                      {positionIndex + 1}
                    </td>
                    {Array.from({ length: numberOfTours }, (_, tourIndex) => (
                      <td
                        key={`tour-${tourIndex}`}
                        style={{
                          border: "1px solid var(--color-border-soft)",
                          padding: "4px",
                        }}
                      >
                        <TourPosition
                          tourIndex={tourIndex}
                          positionIndex={positionIndex}
                          station={tourPlans[tourIndex]?.[positionIndex]}
                          onDrop={handleDrop}
                          onRemove={handleRemove}
                          onDragFromPosition={handleDragFromPosition}
                          isSaving={isSaving || !isOffice}
                          backgroundColor={
                            tourPlans[tourIndex]?.[positionIndex]
                              ? (stationColorMap.get(
                                  tourPlans[tourIndex][positionIndex]!.value,
                                ) ?? null)
                              : null
                          }
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </DndProvider>
  );
}
