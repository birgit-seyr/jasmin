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
import {
  PackingBoxesMatrixPDFGenerator,
  PackingListBulkPDFGenerator,
} from "@features/commissioning/pdfs";
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
  useCommissioningPackingListMemberAmountsRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListBulkListParams,
  CommissioningPackingListMemberAmountsRetrieveParams,
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
import { ExplainerText, MobileStack, PastWarningMessage } from "@shared/ui";
import {
  activeAtDateForWeek,
  dateForWeekDayNumber,
  amountCellText,
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

// Bulk endpoint accepts ``delivery_station`` and ``is_packed_bulk`` (MIXED-mode
// split); ``share_type`` is optional — omitting it sums every share_type.
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
  const { getSetting, tenantName, logoUrl, tenant } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  const showSize = Boolean(getSetting("show_size_column"));

  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    currentWeek,
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
        selectedWeek ?? currentWeek,
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
      currentWeek,
      selectedDeliveryDay,
      isMobile,
      dateFormat,
      mobileDateFormat,
    ],
  );

  const calculateDeliveryDate = useCallback(
    (deliveryDayNum: number | null) =>
      deliveryDayLabel(selectedYear, selectedWeek ?? currentWeek, deliveryDayNum),
    [deliveryDayLabel, selectedYear, selectedWeek, currentWeek],
  );

  const [selectedDeliveryStation, setSelectedDeliveryStation] =
    useDeliveryStationOfDay(getDeliveryDayId);

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
        total_amount_text: totalAmountText(item.total_amount, item.unit, format),
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getVegetableSizeLabel(item.size as string) : "",
      })),
    [data, format, getUnitLabel, getVegetableSizeLabel],
  );

  const stationName = useMemo(
    () => (data[0]?.delivery_station_name as string | undefined) ?? undefined,
    [data],
  );

  const filename = useMemo(
    () => generateFilename(t("commissioning.packing_list_bulk")),
    [generateFilename, t],
  );

  // ----- "Was ihr nehmen könnt" (member per-share amounts) ---------------
  // Same scope as the bulk list, but the matrix keeps amounts PER share size
  // (share_type_variation) instead of summing them — the sheet a member reads
  // at the distribution. ShareContent-based, so it works for import tenants too.
  const { data: memberMatrix } = useCommissioningPackingListMemberAmountsRetrieve(
    listParams as unknown as CommissioningPackingListMemberAmountsRetrieveParams,
    { query: { enabled: queryEnabled } },
  );

  const memberColumns = useMemo(
    () => memberMatrix?.columns ?? [],
    [memberMatrix],
  );

  const memberRows = useMemo(
    () =>
      (memberMatrix?.rows ?? []).map((row) => ({
        ...row,
        unit_label: row.unit ? getUnitLabel(row.unit) : "",
        size_label: row.size ? getVegetableSizeLabel(row.size) : "",
      })),
    [memberMatrix, getUnitLabel, getVegetableSizeLabel],
  );

  // A member's amount per share size, often a fraction: at its unit's
  // precision in the tenant's number format, as the box list prints it.
  const memberAmountText = useCallback(
    (value: unknown, item: Record<string, unknown>) =>
      amountCellText(value, item.unit as string | undefined, format),
    [format],
  );

  // Branded strip for the member-facing PDF (logo + tenant name).
  const tenantInfo = useMemo(
    () => ({
      name: tenantName,
      logoUrl,
      email: (tenant?.email as string) || "",
      phone: (tenant?.phone_number as string) || "",
    }),
    [tenantName, logoUrl, tenant],
  );

  const memberFilename = useMemo(
    () => generateFilename(t("commissioning.packing_list_bulk_member")),
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

          {/* "Was ihr nehmen könnt" — the member per-share sheet. Reuses the
              packing-boxes matrix PDF (grouped columns + green group lines),
              with the box-count row off and a member-facing branded header. */}
          <PackingBoxesMatrixPDFGenerator
            columns={memberColumns.length ? memberColumns : null}
            data={memberRows.length ? memberRows : null}
            week={selectedWeek}
            dayName={
              selectedDeliveryDay !== null
                ? getDayName(selectedDeliveryDay, t)
                : ""
            }
            showSize={showSize}
            tenant={tenantInfo}
            pillKey="commissioning.packing_list_bulk_member"
            showCountRow={false}
            cellText={memberAmountText}
            filename={memberFilename}
            buttonText={t("download.packing_list_bulk_member")}
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
