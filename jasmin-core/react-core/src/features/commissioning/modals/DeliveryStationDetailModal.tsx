import { useQueryClient } from "@tanstack/react-query";
import { Button, Flex, Modal, Spin } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import { useCallback, useMemo, useState } from "react";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  commissioningDeliveryStationsDaysCreate,
  commissioningDeliveryStationsDaysDestroy,
  commissioningDeliveryStationsDaysPartialUpdate,
  getCommissioningDeliveryStationsDaysListQueryKey,
  useCommissioningDeliveryStationsDaysList,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStationDay } from "@shared/api/generated/models/deliveryStationDay";
import type { CommissioningDeliveryStationsDaysListParams } from "@shared/api/generated/models";
import {
  useActiveStatusColumn,
  useDateFormat,
  useTimeBoundColumns,
  useTimeFormat,
} from "@hooks/index";
import {
  capacityFloorParams,
  capacityFloorWeekKeys,
  formatWeekKey,
  stationDayTermCapacity,
} from "@features/abos/utils/stationCapacity";
import type { CapacityWeekEntry } from "@features/abos/utils/stationCapacity";
import {
  useShareDeliveryDays,
  useStationDayTakeover,
} from "@features/commissioning/hooks";
import StationDayPickupInfoCell from "@features/commissioning/components/StationDayPickupInfoCell";
import { useStationDayEarlierStart } from "@features/commissioning/hooks/useStationDayEarlierStart";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import { getStatusColor, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { getWeekdayChoices } from "@shared/utils/weekdayChoices";
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend, StatusButton, ToolTipIcon } from "@shared/ui";
import RichTextEditorModal from "@shared/modals/RichTextEditorModal";
import { useRoles } from "@shared/auth";

interface DeliveryStation {
  id: string;
  short_name?: string;
  contact?: { name?: string };
  [key: string]: unknown;
}

interface StationDayRecord extends TableRecord {
  delivery_day?: string;
  valid_from?: string;
  valid_until?: string | null;
  tour_assignment_missing?: boolean;
  capacity?: number;
  capacity_by_week?: Record<string, CapacityWeekEntry> | null;
  pickup_time_begin?: string;
  pickup_time_end?: string;
  additional_pickup_days?: number;
  special_instructions?: string;
  can_be_deleted?: boolean;
  [key: string]: unknown;
}

interface DeliveryStationDetailModalProps {
  visible: boolean;
  onClose: () => void;
  deliveryStation: DeliveryStation | null;
  onSave?: () => void;
}

const DeliveryStationDetailModal: FC<DeliveryStationDetailModalProps> = ({
  visible,
  onClose,
  deliveryStation,
  onSave: _onSave,
}) => {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  const navigate = useNavigate();
  const { formatDate } = useDateFormat();
  const { formatTimeOfDay } = useTimeFormat();
  const { shareDeliveryDays } = useShareDeliveryDays();

  const weekdayChoices = useMemo(() => getWeekdayChoices(t), [t]);

  // The Orval-generated `CommissioningDeliveryStationsDaysListParams` marks
  // `year`, `delivery_week`, `delivery_day` as required, but the backend
  // actually accepts just `delivery_station` for this list view. Until the
  // backend schema is corrected, we keep the cast. The runtime payload is
  // exactly { delivery_station } — TS just can't see that.
  // The floor window (current ISO week forward) makes the serializer populate
  // ``capacity_by_week``, which feeds the peak-occupancy column + the
  // client-side capacity floor below.
  const listParams = useMemo(
    () =>
      ({
        delivery_station: deliveryStation?.id ?? "",
        ...capacityFloorParams(),
      }) as unknown as CommissioningDeliveryStationsDaysListParams,
    [deliveryStation?.id],
  );

  // Outer gate uses ``loading`` (isLoading → first-load spinner only); the
  // table's ``loading`` uses ``isFetching`` so a revisit (cached under the
  // global staleTime:0) shows a grid refresh spinner instead of silently
  // swapping stale rows for fresh ones.
  const {
    data: rawData,
    isLoading: loading,
    isFetching,
  } = useCommissioningDeliveryStationsDaysList(listParams, {
    query: { enabled: visible && !!deliveryStation?.id },
  });

  const data = useMemo(
    () => (rawData ?? []) as unknown as StationDayRecord[],
    [rawData],
  );

  const validFromEarlierMove = useStationDayEarlierStart(data, shareDeliveryDays);
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    overlapGroup: ["delivery_station", "delivery_day"],
    width: "7em",
    // A station's opening day can only be scheduled going forward — the backend
    // rejects a past valid_from; this aligns the picker with that rule. A saved
    // one is locked, except for a move back into past weeks in onboarding mode.
    validFromFutureOnly: true,
    validFromLockedOnSave: true,
    validFromEarlierMove,
  });

  // Per station-day: busiest current-or-future week's occupancy — the FLOOR
  // for capacity edits (the backend rejects lower via
  // delivery_station.capacity_below_occupancy; this surfaces it BEFORE save).
  const peakByStationDayId = useMemo(() => {
    const weekKeys = capacityFloorWeekKeys();
    const map = new Map<
      string,
      { peakOccupied: number; peakWeekKey: string | null }
    >();
    for (const record of data) {
      const { peakOccupied, peakWeekKey } = stationDayTermCapacity(
        record.capacity ?? null,
        record.capacity_by_week,
        weekKeys,
      );
      map.set(String(record.id), { peakOccupied, peakWeekKey });
    }
    return map;
  }, [data]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningDeliveryStationsDaysListQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  // A delivery day as its weekday, validity and status colour.
  const deliveryDayLabel = useCallback(
    (day: ShareDeliveryDayOption) => {
      const dayName =
        (weekdayChoices.find((c) => c.value === (day.day_number as number))
          ?.label as string) || `Day ${day.day_number}`;
      const validFrom = formatDate(day.valid_from as string);
      const validUntil = formatDate(day.valid_until as string);
      const statusColor = getStatusColor(
        day.valid_from as string,
        day.valid_until as string,
      );

      let datePart = "";
      if (validFrom) {
        datePart = `${t("commissioning.valid_from")} ${validFrom}`;
      }
      if (validUntil) {
        datePart += ` ${t("commissioning.valid_until")} ${validUntil}`;
      }

      return (
        <Flex align="center" component="span">
          {statusColor && (
            <span
              style={{
                display: "inline-block",
                width: "10px",
                height: "10px",
                backgroundColor: statusColor,
                marginRight: "8px",
                borderRadius: "2px",
              }}
            />
          )}
          <strong>{dayName}</strong>
          {datePart && (
            <span
              style={{
                color: "var(--color-text-muted)",
                fontSize: "0.85em",
                marginLeft: "8px",
              }}
            >
              {datePart}
            </span>
          )}
        </Flex>
      );
    },
    [t, formatDate, weekdayChoices],
  );

  const deliveryDayOptions = useMemo(() => {
    const dayNumberMap = new Map<number, ShareDeliveryDayOption>();

    shareDeliveryDays.forEach((day) => {
      const dayNum = day.day_number as number;
      if (!dayNumberMap.has(dayNum)) {
        dayNumberMap.set(dayNum, day);
      }
    });

    return Array.from(dayNumberMap.keys())
      .sort((a, b) => a - b)
      .map((dayNumber) => {
        const day = dayNumberMap.get(dayNumber)!;
        return {
          value: day.id as string,
          dayNumber,
          label: deliveryDayLabel(day),
        };
      });
  }, [shareDeliveryDays, deliveryDayLabel]);

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });

  // Every delivery day is offered, also one this station already serves: a
  // new station day starting later takes the open one over, once the office
  // agrees; the table refuses one that would overlap it.
  const { confirmTakeover, confirmHolder } = useStationDayTakeover(
    data,
    shareDeliveryDays,
  );

  const [descriptionModalVisible, setDescriptionModalVisible] = useState(false);
  const [selectedDescriptionRecord, setSelectedDescriptionRecord] =
    useState<StationDayRecord | null>(null);

  const renderWeekday = useCallback(
    (value: unknown) => {
      if (!value) return "-";
      const shareDay = shareDeliveryDays.find((d) => d.id === value);
      return shareDay ? deliveryDayLabel(shareDay) : (value as string);
    },
    [shareDeliveryDays, deliveryDayLabel],
  );

  const handleOpenDescriptionModal = useCallback((record: StationDayRecord) => {
    setSelectedDescriptionRecord(record);
    setDescriptionModalVisible(true);
  }, []);

  const handleCloseDescriptionModal = useCallback(() => {
    setDescriptionModalVisible(false);
    setSelectedDescriptionRecord(null);
  }, []);

  const handleSaveDescription = useCallback(
    async (htmlContent: string) => {
      if (!selectedDescriptionRecord?.id) return;

      try {
        await commissioningDeliveryStationsDaysPartialUpdate(
          String(selectedDescriptionRecord.id),
          { special_instructions: htmlContent },
        );
        notify.success(t("common.saved_successfully"));
        invalidateData();
      } catch (error) {
        notify.error(getErrorMessage(error, t("common.error_saving")));
        // Keeps the editor open with the text.
        throw error;
      }
    },
    [selectedDescriptionRecord, t, invalidateData],
  );

  const columns = useMemo(
    () =>
      [
        activeStatusColumn,
        {
          title: (
            <div className="checkbox-column-title">
              {t("delivery_stations.tour_assignment_missing")}
            </div>
          ),
          dataIndex: "tour_assignment_missing",
          key: "tour_assignment_missing",
          inputType: "text",
          required: false,
          disabled: true,
          align: "center",
          width: "3em",
          render: (_: unknown, record: StationDayRecord) => {
            const missing = record.tour_assignment_missing === true;
            return (
              <StatusButton
                variant={missing ? "not_ok" : "ok"}
                tooltip={t(
                  missing
                    ? "delivery_stations.tour_not_assigned"
                    : "delivery_stations.tour_assigned",
                )}
                showTooltip
                onClick={() => navigate("/commissioning/delivery-tours")}
              />
            );
          },
        },
        {
          title: t("configuration.delivery_day"),
          dataIndex: "delivery_day",
          key: "delivery_day",
          inputType: "select",
          required: true,
          align: "center",
          width: "12em",
          disabled: (record: StationDayRecord) => record.key !== -1,
          options: deliveryDayOptions,
          render: renderWeekday,
        },
        validFromColumn,
        validUntilColumn,
        {
          title: (
            <>
              {t("commissioning.capacity")}{" "}
              <ToolTipIcon title={t("tooltip.capacity")} />
            </>
          ),
          dataIndex: "capacity",
          key: "capacity",
          inputType: "positive_integer",
          width: "6em",
          align: "center",
          required: true,
        },
        {
          // Busiest current-or-future week's occupancy — the floor below
          // which the capacity cannot be set (already-booked slots).
          title: (
            <>
              {t("commissioning.peak_occupancy")}{" "}
              <ToolTipIcon title={t("tooltip.peak_occupancy")} />
            </>
          ),
          dataIndex: "peak_occupancy",
          key: "peak_occupancy",
          inputType: "text",
          required: false,
          disabled: true,
          readOnly: true,
          width: "7em",
          align: "center",
          render: (_: unknown, record: StationDayRecord) => {
            if (record.key === -1 || !record.id) return "-";
            const peak = peakByStationDayId.get(String(record.id));
            if (!peak || peak.peakOccupied <= 0) return "0";
            return peak.peakWeekKey
              ? `${peak.peakOccupied} (${t("commissioning.KW")} ${formatWeekKey(peak.peakWeekKey)})`
              : String(peak.peakOccupied);
          },
        },
        {
          title: t("delivery.pickup_time_begin"),
          dataIndex: "pickup_time_begin",
          key: "pickup_time_begin",
          inputType: "time",
          width: "6em",
          align: "center",
          render: (value: unknown) => formatTimeOfDay(value),
        },
        {
          title: t("delivery.pickup_time_end"),
          dataIndex: "pickup_time_end",
          key: "pickup_time_end",
          inputType: "time",
          width: "6em",
          align: "center",
          render: (value: unknown) => formatTimeOfDay(value),
        },
        {
          title: (
            <>
              {t("delivery.additional_pickup_days")}
              <ToolTipIcon title={t("tooltip.additional_pickup_days")} />
            </>
          ),
          dataIndex: "additional_pickup_days",
          key: "additional_pickup_days",
          inputType: "positive_integer",
          width: "6em",
          align: "center",
        },
        {
          title: t("delivery.special_instructions"),
          dataIndex: "special_instructions",
          key: "special_instructions",
          inputType: "text",
          disabled: true,
          width: "6em",
          align: "center",
          render: (_: unknown, record: StationDayRecord) => (
            <StationDayPickupInfoCell
              html={record.special_instructions}
              title={`${t("commissioning.special_instructions")} ${deliveryStation?.short_name ?? ""}`}
              canEdit={isOffice}
              onEdit={() => handleOpenDescriptionModal(record)}
              zIndex={1100}
            />
          ),
        },
      ] as EditableColumnConfig[],
    [
      t,
      activeStatusColumn,
      navigate,
      validFromColumn,
      validUntilColumn,
      deliveryDayOptions,
      handleOpenDescriptionModal,
      renderWeekday,
      peakByStationDayId,
      formatTimeOfDay,
      isOffice,
      deliveryStation?.short_name,
    ],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      // Client-side capacity floor: mirror the backend rejection
      // (delivery_station.capacity_below_occupancy) BEFORE the request, so
      // the office sees the constraint while the row is still in edit mode.
      const capacity = transformedData.capacity;
      const rowId = transformedData.id;
      if (capacity != null && capacity !== "" && rowId) {
        const peak = peakByStationDayId.get(String(rowId));
        if (peak && Number(capacity) < peak.peakOccupied) {
          const message = t("commissioning.capacity_below_peak", {
            peak: peak.peakOccupied,
            week: peak.peakWeekKey ? formatWeekKey(peak.peakWeekKey) : "-",
          });
          notify.validationError(message);
          // Throwing aborts the save; EditableTable keeps the row in edit
          // mode so the office can pick a valid value.
          throw new Error(message);
        }
      }
      return {
        ...transformedData,
        delivery_station: deliveryStation?.id,
      };
    },
    [deliveryStation?.id, peakByStationDayId, t],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<DeliveryStationDay & TableRecord>({
        create: async (newDay) => {
          if (!(await confirmTakeover(newDay))) {
            throw new Error(t("delivery_stations.takeover_not_saved"));
          }
          return commissioningDeliveryStationsDaysCreate(newDay);
        },
        update: (id, data) =>
          commissioningDeliveryStationsDaysPartialUpdate(id, data),
        delete: (id) => commissioningDeliveryStationsDaysDestroy(id),
      }),
    [confirmTakeover, t],
  );

  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  return (
    <>
      {confirmHolder}
      <Modal
        title={`${t("delivery.station_delivery_days_details")} ${
          deliveryStation?.short_name || deliveryStation?.contact?.name || ""
        }`}
        open={visible}
        onCancel={onClose}
        width={1200}
        // Unmount the table on close so reopening for a DIFFERENT station
        // starts fresh — no carry-over of the previous station's rows, draft,
        // or recentlyAddedIds pins.
        destroyOnHidden
        footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
      >
        {loading ? (
          <div className="loading-placeholder">
            <Spin size="large" />
          </div>
        ) : (
          <>
            <EditableTable
              columns={columns}
              apiFunctions={apiFunctions}
              initialData={data}
              loading={isFetching}
              onSaveSuccess={invalidateData}
              onDeleteSuccess={invalidateData}
              permissions={permissions}
              customSave={customSave}
              forceInlineMode={true}
            />
            <DateRangeStatusLegend />
          </>
        )}
      </Modal>
      <RichTextEditorModal
        // Fresh key per record (so the editor fills on first open) + pinned
        // above the parent station modal.
        key={selectedDescriptionRecord?.id ?? "instr"}
        visible={descriptionModalVisible}
        zIndex={1100}
        onClose={handleCloseDescriptionModal}
        value={selectedDescriptionRecord?.special_instructions || ""}
        onSave={handleSaveDescription}
        placeholder={t("commissioning.enter_special_instructions")}
        title={`${t("commissioning.special_instructions")} ${
          deliveryStation?.short_name || ""
        }`}
      />
    </>
  );
};

export default DeliveryStationDetailModal;
