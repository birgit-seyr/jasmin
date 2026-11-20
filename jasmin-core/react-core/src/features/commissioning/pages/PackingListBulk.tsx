import { RelatedDayInfo } from "@features/commissioning/components";
import { PackingListBulkMobileCard } from "@features/commissioning/components/mobileCards";
import {
  useAmountUnitSizeColumns,
  useCurrentDays,
  useDeliveryStationOfDay,
  useShareArticleColumn,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import type { ShareDeliveryDayOption } from "@features/commissioning/hooks/useShareDeliveryDays";
import { PackingListBulkPDFGenerator } from "@features/commissioning/pdfs";
import type { PackingListBulkPage } from "@features/commissioning/pdfs/exports/PackingListBulkPDF";
import { DeliveryStationSelector } from "@features/commissioning/selectors";
import {
  useDateFormat,
  useDeliveryDayLabel,
  useInvalidateAfterTableMutation,
  useIsMobile,
  useNoteColumn,
  useNumberFormat,
  useVegetableSizeOptions,
  useTenant,
  useUnitOptions,
  useYearWeekState,
} from "@hooks/index";
import {
  getCommissioningPackingListBulkListQueryKey,
  useCommissioningPackingListBulkList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListBulkListParams,
  CommissioningSharesDeliveryDaysListParams,
  PackingListBulkRow,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
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
import {
  ExplainerText,
  MobileStack,
  PastWarningMessage,
  ToolTipIcon,
} from "@shared/ui";
import {
  activeAtDateForWeek,
  dateForWeekDayNumber,
  formatAmountForUnit,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  isWeekInPast,
} from "@shared/utils";
import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
};

const widthShareArticle = "30%";
const widthAmountUnitSize = "10%";
const widthTotalAmount = "10%";

/** A row's total in the tenant's number format, at its unit's precision —
 *  the text the table, the phone card and the printed list all show. */
const totalAmountText = (
  amount: unknown,
  unit: unknown,
  format: (value: number, decimals: number) => string,
): string =>
  amount == null || amount === "" || !Number.isFinite(Number(amount))
    ? ""
    : formatAmountForUnit(Number(amount), unit as string | null, format);

// Bulk endpoint accepts ``delivery_station`` and ``is_packed_bulk`` (only the
// sizes packed loose); ``share_type`` is optional — omitting it sums every
// share_type.
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
  const { format } = useNumberFormat();
  const { dateFormat, mobileDateFormat } = useDateFormat();
  const deliveryDayLabel = useDeliveryDayLabel();
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { noteColumn } = useNoteColumn();
  const { getSetting } = useTenant();
  const showSize = Boolean(getSetting("show_size_column"));

  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
  } = useYearWeekState();
  // Backend day numbers run 0 = Monday … 6 = Sunday.
  const [selectedDeliveryDay, setSelectedDeliveryDay] = useState<number | null>(
    () => dayjs().isoWeekday() - 1,
  );
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );

  // ----- Delivery-day resolution -----------------------------------------
  const shareDeliveryDaysParams =
    useMemo<CommissioningSharesDeliveryDaysListParams>(
      () => ({
        active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
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
    if (!isLoaded || selectedDeliveryDay === null) {
      return [];
    }
    return getRelatedDays.getPackingDaysForDelivery(selectedDeliveryDay);
  }, [isLoaded, getRelatedDays, selectedDeliveryDay]);

  // A packing weekday later than the selected delivery's weekday packs for it
  // in the week before. One packing day can serve several delivery days, so
  // the comparison is with the selected one.
  const calculatePackingDate = useCallback(
    (packingDayNum: number | null) => {
      if (packingDayNum === null) return "";
      let date = dateForWeekDayNumber(
        selectedYear,
        selectedWeek,
        packingDayNum,
      );
      if (selectedDeliveryDay !== null && packingDayNum > selectedDeliveryDay) {
        date = date.subtract(1, "week");
      }
      return isMobile
        ? date.format(`dd, ${mobileDateFormat}`)
        : date.format(`dddd, ${dateFormat}`);
    },
    [
      selectedYear,
      selectedWeek,
      selectedDeliveryDay,
      isMobile,
      dateFormat,
      mobileDateFormat,
    ],
  );

  const calculateDeliveryDate = useCallback(
    (deliveryDayNum: number | null) =>
      deliveryDayLabel(selectedYear, selectedWeek, deliveryDayNum),
    [deliveryDayLabel, selectedYear, selectedWeek],
  );

  // The stations the day served in the selected week.
  const weekDate = activeAtDateForWeek(selectedYear, selectedWeek);
  const [selectedDeliveryStation, setSelectedDeliveryStation] =
    useDeliveryStationOfDay(getDeliveryDayId, { activeAtDate: weekDate });

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
  const dayName =
    selectedDeliveryDay !== null ? getDayName(selectedDeliveryDay, t) : "";

  // ----- Columns ---------------------------------------------------------
  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    autofillContext: "harvest",
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
      render: (value: unknown, record: TableRecord) =>
        totalAmountText(value, record.unit, format),
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
  }, [t, widthNote, shareArticleColumn, amountUnitSizeColumns, noteColumn, format]);

  const apiFunctions = useMemo<ApiFunctions>(() => wrapApiFunctions({}), []);

  // ----- Data ------------------------------------------------------------
  // Without a station the endpoint answers every station's rows at once,
  // grouped by station name — the day's lists, one PDF page each.
  const dayParams: BulkParams = useMemo(
    () =>
      ({
        year: selectedYear,
        delivery_week: selectedWeek ?? undefined,
        day_number: selectedDeliveryDay ?? undefined,
        is_past: isPast,
        // Only the sizes packed loose, a past week's as they were.
        is_packed_bulk: true,
      }) as BulkParams,
    [selectedYear, selectedWeek, selectedDeliveryDay, isPast],
  );
  const listParams: BulkParams = useMemo(
    () => ({
      ...dayParams,
      delivery_station: selectedDeliveryStation ?? undefined,
    }),
    [dayParams, selectedDeliveryStation],
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

  const toPrintRows = useCallback(
    (rows: PackingListBulkRow[]) =>
      rows.map((item) => ({
        ...item,
        total_amount_text: totalAmountText(item.total_amount, item.unit, format),
        unit_label: item.unit ? getUnitLabel(item.unit) : "",
        size_label: item.size ? getVegetableSizeLabel(item.size) : "",
      })),
    [format, getUnitLabel, getVegetableSizeLabel],
  );

  const stationPages = useMemo<PackingListBulkPage[] | null>(
    () =>
      data.length > 0
        ? [
            {
              deliveryStationName: data[0].delivery_station_name,
              data: toPrintRows(data),
            },
          ]
        : null,
    [data, toPrintRows],
  );

  // Asked once the day's stations are known, like the station's own list,
  // and only where its download is offered: a phone shows no downloads.
  const { data: dayRows } = useCommissioningPackingListBulkList(
    dayParams as unknown as CommissioningPackingListBulkListParams,
    { query: { enabled: queryEnabled && !isMobile } },
  );
  // A station without loose amounts has no rows, so no page.
  const dayPages = useMemo<PackingListBulkPage[] | null>(() => {
    const pagesByStation = new Map<string, PackingListBulkPage>();
    for (const row of toPrintRows(dayRows ?? [])) {
      const page = pagesByStation.get(row.delivery_station) ?? {
        deliveryStationName: row.delivery_station_name,
        data: [],
      };
      page.data.push(row);
      pagesByStation.set(row.delivery_station, page);
    }
    return pagesByStation.size > 0 ? [...pagesByStation.values()] : null;
  }, [dayRows, toPrintRows]);

  const filename = useMemo(
    () => generateFilename(t("commissioning.packing_list_bulk")),
    [generateFilename, t],
  );
  const dayFilename = useMemo(
    () =>
      generatePdfFilename([
        t("commissioning.packing_list_bulk"),
        selectedYear,
        formatWeekLabel(selectedWeek, t),
        formatDayLabel(selectedDeliveryDay, t),
        t("commissioning.all_day"),
      ]),
    [selectedYear, selectedWeek, selectedDeliveryDay, t],
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
          selectedWeek={selectedWeek}
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
            selectedWeek={selectedWeek}
            selectedYear={selectedYear}
            formatDate={calculatePackingDate}
          />
        </div>
      )}

      <div className="packing-list-bulk__station-selector">
        <DeliveryStationSelector
          selectedDeliveryStation={selectedDeliveryStation}
          setSelectedDeliveryStation={setSelectedDeliveryStation}
          delivery_day={getDeliveryDayId}
          active_at_date={weekDate}
        />
      </div>

      {!isMobile && (
        <div className="section-divider flex-row gap-1em">
          <PackingListBulkPDFGenerator
            pages={stationPages}
            year={selectedYear}
            week={selectedWeek}
            dayName={dayName}
            showSize={showSize}
            filename={filename}
            buttonText={t("download.packing_list_bulk")}
            t={t}
          />
          <span>
            <PackingListBulkPDFGenerator
              pages={dayPages}
              year={selectedYear}
              week={selectedWeek}
              dayName={dayName}
              showSize={showSize}
              filename={dayFilename}
              buttonText={t("download.packing_lists_bulk_day")}
              t={t}
            />
            <ToolTipIcon
              title={t("tooltip.packing_lists_bulk_day")}
              className="tooltip-icon-beside-button"
            />
          </span>
        </div>
      )}

      {queryEnabled ? (
        <EditableTable
          key={`${selectedYear}-${selectedWeek}-${selectedDeliveryDay}-${selectedDeliveryStation}`}
          columns={columns}
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
