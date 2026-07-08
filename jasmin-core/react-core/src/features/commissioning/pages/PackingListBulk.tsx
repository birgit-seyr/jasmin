import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getCommissioningPackingListBulkListQueryKey,
  useCommissioningPackingListBulkList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListBulkListParams,
  CommissioningSharesDeliveryDaysListParams,
  PackingListBulkRow,
} from "@shared/api/generated/models";
import { PackingListBulkMobileCard } from "@features/commissioning/components/mobileCards";
import { PackingListBulkPDFGenerator } from "@features/commissioning/pdfs";
import { RelatedDayInfo } from "@features/commissioning/components";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { DeliveryStationSelector } from "@features/commissioning/selectors";
import {
  EditableTable,
  READ_ONLY_PERMISSION,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, MobileStack, PastWarningMessage } from "@shared/ui";
import {
  useDateFormat,
  useInvalidateAfterTableMutation,
  useIsMobile,
  useNoteColumn,
  useSizeOptions,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useCurrentDays,
  useDeliveryStations,
  useShareArticleColumn,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  isWeekInPast,
} from "@shared/utils";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
};

const widthShareArticle = "30%";
const widthAmountUnitSize = "10%";
const widthTotalAmount = "10%";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();
const currentDay = dayjs().isoWeekday();

// Bulk endpoint accepts ``delivery_station`` and ``is_packed_bulk`` (MIXED-mode
// split); ``share_type`` is now optional — omitting it sums every share_type.
// Generated params type lags until ``npm run generate-api`` is rerun.
type BulkParams = CommissioningPackingListBulkListParams & {
  delivery_station?: string;
  is_packed_bulk?: boolean;
};

/**
 * Per-delivery-station bulk packing list. Answers "how much of each article
 * does this station need on this delivery day" — a warehouse total that sums
 * across ALL share types (there is deliberately no share-type filter). The
 * office picks year/week/delivery-day + a delivery station.
 */
export default function PackingListBulk() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { dateFormat, mobileDateFormat } = useDateFormat();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { noteColumn } = useNoteColumn();
  const { getSetting } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  const showSize = Boolean(getSetting("show_size_column"));

  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    currentDay - 1,
  );
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);

  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );

  // ----- Delivery-day resolution -----------------------------------------
  const shareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({
        active_at_date: dayjs()
          .year(selectedYear)
          .isoWeek(selectedWeek ?? currentWeek)
          .isoWeekday(6)
          .format("YYYY-MM-DD"),
      }),
      [selectedYear, selectedWeek],
    );
  const { shareDeliveryDays } = useShareDeliveryDays(shareDeliveryDaysParams);

  const { getRelatedDays, isLoaded } = useCurrentDays(
    selectedWeek ?? undefined,
    selectedYear,
  );

  // The day selector lists only the tenant's ACTUAL delivery weekdays.
  const deliveryDayOptions = useMemo<number[]>(
    () =>
      Array.from(
        new Set(shareDeliveryDays.map((day) => Number(day.day_number))),
      ).sort((a, b) => a - b),
    [shareDeliveryDays],
  );

  // Keep the selection on a real delivery day.
  useEffect(() => {
    if (deliveryDayOptions.length === 0) return;
    if (
      selectedDeliveryDay !== null &&
      deliveryDayOptions.includes(selectedDeliveryDay)
    ) {
      return;
    }
    setSelectedDeliveryDay(deliveryDayOptions[0]);
  }, [deliveryDayOptions, selectedDeliveryDay]);

  const getDeliveryDayId = useMemo<string | null>(() => {
    if (selectedDeliveryDay === null || !shareDeliveryDays.length) return null;
    const deliveryDay = shareDeliveryDays.find(
      (day: ShareDeliveryDayOption) =>
        Number(day.day_number) === Number(selectedDeliveryDay),
    );
    return deliveryDay?.id ?? null;
  }, [selectedDeliveryDay, shareDeliveryDays]);

  // The packing day(s) derived from the selected delivery day (informational).
  const packingDaysForDelivery = useMemo<number[]>(() => {
    if (
      !isLoaded ||
      selectedDeliveryDay === null ||
      !getRelatedDays?.getPackingDaysForDelivery
    ) {
      return [];
    }
    return getRelatedDays.getPackingDaysForDelivery(selectedDeliveryDay);
  }, [isLoaded, getRelatedDays, selectedDeliveryDay]);

  const calculatePackingDate = useCallback(
    (packingDayNum: number | null) => {
      if (packingDayNum === null) return "";
      const deliveryDays =
        getRelatedDays?.getDeliveryDaysForPacking(packingDayNum) || [];
      const deliveryDay = deliveryDays[0];
      const dayIso = packingDayNum + 1;
      let date = dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? currentWeek)
        .isoWeekday(dayIso);
      if (deliveryDay !== undefined && packingDayNum > deliveryDay) {
        date = date.subtract(1, "week");
      }
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [
      selectedYear,
      selectedWeek,
      getRelatedDays,
      isMobile,
      dateFormat,
      mobileDateFormat,
    ],
  );

  const calculateDeliveryDate = useCallback(
    (deliveryDayNum: number | null) => {
      if (deliveryDayNum === null) return "";
      const date = dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? currentWeek)
        .isoWeekday(deliveryDayNum + 1);
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [selectedYear, selectedWeek, isMobile, dateFormat, mobileDateFormat],
  );

  // ----- Delivery-station auto-default -----------------------------------
  const { deliveryStations } = useDeliveryStations({
    delivery_day: getDeliveryDayId ?? undefined,
  });

  useEffect(() => {
    if (selectedDeliveryStation !== null) return;
    if (deliveryStations.length === 0) return;
    setSelectedDeliveryStation(deliveryStations[0].value);
  }, [selectedDeliveryStation, deliveryStations]);

  // Drop a stale station when it's no longer scheduled (e.g. week change).
  useEffect(() => {
    if (selectedDeliveryStation === null) return;
    if (deliveryStations.length === 0) return;
    const stillValid = deliveryStations.some(
      (s) => s.value === selectedDeliveryStation,
    );
    if (!stillValid) setSelectedDeliveryStation(null);
  }, [selectedDeliveryStation, deliveryStations]);

  const generateFilename = useCallback(
    (prefix: string) =>
      generatePdfFilename([
        prefix,
        selectedYear,
        formatWeekLabel(selectedWeek, t),
        formatDayLabel(selectedDeliveryDay, t),
      ]),
    [selectedYear, selectedWeek, selectedDeliveryDay, t],
  );

  // ----- Columns ---------------------------------------------------------
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "harvest",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { disabled: (record: TableRecord) => record.key != -1 },
      size: { disabled: (record: TableRecord) => record.key != -1 },
    },
    showAmount: false,
  });

  const widthNote = useMemo(() => {
    const shareArticleWidth = parseFloat(widthShareArticle.replace("%", ""));
    const unitSizeWidth = parseFloat(widthAmountUnitSize.replace("%", ""));
    const totalAmountWidth = parseFloat(widthTotalAmount.replace("%", ""));
    const usedWidth = shareArticleWidth + unitSizeWidth * 2 + totalAmountWidth;
    return `${Math.max(100 - usedWidth, 5)}%`;
  }, []);

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const baseColumns: EditableColumnConfig<TableRecord>[] = [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
        pdf: {
          include: true,
          width: widthShareArticle,
          dataKey: "share_article_name",
          align: "left",
          title: t("commissioning.vegetables_and_fruits"),
        },
      },
      ...amountUnitSizeColumns.map(
        (col): EditableColumnConfig<TableRecord> => ({
          ...col,
          pdf: {
            include: true,
            width: widthAmountUnitSize,
            align: "center",
            dataKey:
              col.dataIndex === "unit"
                ? "unit_label"
                : col.dataIndex === "size"
                  ? "size_label"
                  : col.dataIndex,
            title: col.title,
          },
        }),
      ),
    ];

    const totalAmountColumn: EditableColumnConfig<TableRecord> = {
      title: t("commissioning.total_amount"),
      dataIndex: "total_amount",
      key: "total_amount",
      inputType: "positive_decimal2",
      align: "center",
      width: "10em",
      disabled: true,
      render: (value: unknown) => {
        if (value === null || value === undefined || value === "") return "";
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return String(value);
        return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2);
      },
    };

    const endColumns: EditableColumnConfig<TableRecord>[] = [
      {
        ...noteColumn,
        inputType: "optional",
        disabled: true,
        pdf: {
          include: true,
          width: widthNote,
          dataKey: "note",
          align: "left",
          title: t("commissioning.note"),
        },
      },
    ];

    return [...baseColumns, totalAmountColumn, ...endColumns];
  }, [t, widthNote, shareArticleColumn, amountUnitSizeColumns, noteColumn]);

  const apiFunctions = useMemo<ApiFunctions>(() => wrapApiFunctions({}), []);

  // ----- Data ------------------------------------------------------------
  const listParams: BulkParams = useMemo(
    () =>
      ({
        year: selectedYear,
        delivery_week: selectedWeek ?? undefined,
        day_number: selectedDeliveryDay ?? undefined,
        is_past: isPast,
        delivery_station: selectedDeliveryStation ?? undefined,
        // In MIXED mode only sum variations actually packed in bulk; BULK mode
        // already implies every variation is bulk, so the filter is a no-op.
        ...(packing_mode === "MIXED" ? { is_packed_bulk: true } : {}),
      }) as BulkParams,
    [
      selectedYear,
      selectedWeek,
      selectedDeliveryDay,
      isPast,
      selectedDeliveryStation,
      packing_mode,
    ],
  );

  const queryEnabled =
    selectedDeliveryDay !== null && selectedDeliveryStation !== null;

  const { data: rawData, isFetching } = useCommissioningPackingListBulkList(
    listParams as unknown as CommissioningPackingListBulkListParams,
    { query: { enabled: queryEnabled } },
  );

  const data = useMemo(
    () => (rawData as unknown as (PackingListBulkRow & TableRecord)[]) ?? [],
    [rawData],
  );

  const processedData = useMemo(
    () =>
      data.map((item) => ({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      })),
    [data, getUnitLabel, getSizeLabel],
  );

  const stationName = useMemo(
    () => (data[0]?.delivery_station_name as string | undefined) ?? undefined,
    [data],
  );

  const filename = useMemo(
    () => generateFilename(t("commissioning.packing_list_bulk")),
    [generateFilename, t],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningPackingListBulkListQueryKey(
        listParams as unknown as CommissioningPackingListBulkListParams,
      ),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  return (
    <div>
      <h1>{t("commissioning.packing_list_bulk")}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />

        <DaySelector
          selectedDay={selectedDeliveryDay}
          setSelectedDay={setSelectedDeliveryDay}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedYear={selectedYear}
          days={deliveryDayOptions}
          suffix={t("commissioning.delivery_day")}
          customDateCalculator={calculateDeliveryDate}
        />
      </MobileStack>

      {!isMobile && (
        <div>
          <RelatedDayInfo
            label={t("commissioning.packing_day")}
            relatedDayNumbers={packingDaysForDelivery}
            selectedWeek={selectedWeek ?? currentWeek}
            selectedYear={selectedYear}
            formatDate={calculatePackingDate}
          />
        </div>
      )}

      <div
        style={{ marginTop: "1em", marginLeft: "-2em", marginBottom: "1em" }}
      >
        <DeliveryStationSelector
          selectedDeliveryStation={selectedDeliveryStation}
          setSelectedDeliveryStation={setSelectedDeliveryStation}
          delivery_day={getDeliveryDayId}
        />
      </div>

      {!isMobile && (
        <div
          className="section-divider"
          style={{ display: "flex", gap: "1em" }}
        >
          <PackingListBulkPDFGenerator
            data={processedData}
            year={selectedYear}
            week={selectedWeek}
            dayName={
              selectedDeliveryDay !== null
                ? getDayName(selectedDeliveryDay, t)
                : ""
            }
            deliveryStationName={stationName}
            showSize={showSize}
            filename={filename}
            buttonText={t("download.packing_list_bulk")}
            t={t}
          />
        </div>
      )}

      {queryEnabled ? (
        <EditableTable
          key={`${selectedYear}-${selectedWeek}-${selectedDeliveryDay}-${selectedDeliveryStation}`}
          columns={columns as EditableColumnConfig[]}
          apiFunctions={apiFunctions}
          initialData={data}
          loading={isFetching}
          onSaveSuccess={onSaveSuccess}
          onDeleteSuccess={onDeleteSuccess}
          permissions={READ_ONLY_PERMISSION}
          className={"w-max custom-jasmin-table"}
          renderMobileCard={(record: TableRecord) => (
            <PackingListBulkMobileCard
              key={String(record.key)}
              record={record}
            />
          )}
        />
      ) : (
        <PastWarningMessage>
          {selectedDeliveryDay === null
            ? t("commissioning.please_select_delivery_day")
            : t("commissioning.please_select_delivery_station")}
        </PastWarningMessage>
      )}

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.packing_list_bulk")}
        </ExplainerText>
      )}
    </div>
  );
}
