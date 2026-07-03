import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  getCommissioningPackingListListQueryKey,
  useCommissioningPackingListList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListListParams,
  PackingListRow,
} from "@shared/api/generated/models";
import { PackingListBoxesMobileCard } from "@features/commissioning/components/mobileCards";
import {
  PackingListAllStationsPDFGenerator,
  PackingListPDFGenerator,
} from "@features/commissioning/pdfs";
import type { PackingStationPage } from "@features/commissioning/pdfs/exports/PackingListPDF";
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
import { ExplainerText } from "@shared/ui";
import { useInvalidateAfterTableMutation, useIsMobile, useNoteColumn, useNumberFormat, useSizeOptions, useTenant, useUnitOptions } from '@hooks/index';
import { useAmountUnitSizeColumns, useShareArticleColumn } from '@features/commissioning/hooks';
import type { ShareTypeOption } from "@hooks/useShareTypes";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import dayjs from "dayjs";

import { generatePdfFilename, getDayName } from "@shared/utils";

const fallbackWeek = dayjs().isoWeek();

import PackingListShell, {
  type PackingListShellState,
} from "./PackingListShell";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
};

const widthShareArticle = "30%";
const widthAmountUnitSize = "10%";
const widthVariation = "10%";

// The boxes endpoint accepts ``is_packed_bulk`` for the MIXED packing-mode
// split. Generated params type lags until ``npm run generate-api`` is rerun.
type BoxesParams = CommissioningPackingListListParams & {
  is_packed_bulk?: boolean;
};

export default function PackingListBoxes() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { noteColumn } = useNoteColumn();
  const { format } = useNumberFormat();
  const { getSetting } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  // Mirror the on-screen size column: hidden unless ``show_size_column`` is on.
  const showSize = Boolean(getSetting("show_size_column"));

  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { disabled: (record: TableRecord) => record.key != -1 },
      size: { disabled: (record: TableRecord) => record.key != -1 },
    },
    showAmount: false,
  });

  const renderBody = useCallback(
    (shell: PackingListShellState) => (
      <BoxesBody
        shell={shell}
        shareArticleColumn={shareArticleColumn}
        amountUnitSizeColumns={amountUnitSizeColumns}
        noteColumn={noteColumn}
        getUnitLabel={getUnitLabel}
        getSizeLabel={getSizeLabel}
        format={format}
        queryClient={queryClient}
        isMobile={isMobile}
        packing_mode={packing_mode}
        showSize={showSize}
        t={t}
      />
    ),
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      noteColumn,
      getUnitLabel,
      getSizeLabel,
      format,
      queryClient,
      isMobile,
      packing_mode,
      showSize,
      t,
    ],
  );

  return (
    <PackingListShell
      titleKey="commissioning.packing_list_boxes"
      mode="boxes"
      variationsTotalsTooltipKey="tooltip.variations_totals_packing_list_boxes"
    >
      {renderBody}
    </PackingListShell>
  );
}

function BoxesBody({
  shell,
  shareArticleColumn,
  amountUnitSizeColumns,
  noteColumn,
  getUnitLabel,
  getSizeLabel,
  format,
  queryClient,
  isMobile,
  packing_mode,
  showSize,
  t,
}: {
  shell: PackingListShellState;
  shareArticleColumn: EditableColumnConfig<TableRecord>;
  amountUnitSizeColumns: EditableColumnConfig<TableRecord>[];
  noteColumn: EditableColumnConfig<TableRecord>;
  getUnitLabel: (unit: string) => string;
  getSizeLabel: (size: string) => string;
  format: (n: number, decimals: number) => string;
  queryClient: ReturnType<typeof useQueryClient>;
  isMobile: boolean;
  packing_mode: "BOXES" | "BULK" | "MIXED";
  showSize: boolean;
  t: ReturnType<typeof useTranslation>["t"];
}) {
  const widthNote = useMemo(() => {
    const shareArticleWidth = parseFloat(widthShareArticle.replace("%", ""));
    const unitSizeWidth = parseFloat(widthAmountUnitSize.replace("%", ""));
    const variationWidth = parseFloat(widthVariation.replace("%", ""));
    const usedWidth =
      shareArticleWidth +
      unitSizeWidth * 2 +
      shell.shareTypeVariations.length * variationWidth;
    return `${Math.max(100 - usedWidth, 5)}%`;
  }, [shell.shareTypeVariations.length]);

  const listParams = useMemo<BoxesParams>(
    () => ({
      year: shell.selectedYear,
      delivery_week: shell.selectedWeek ?? fallbackWeek,
      day_number: shell.selectedDeliveryDay!,
      share_type: shell.effectiveShareType,
      delivery_station: shell.selectedDeliveryStation ?? undefined,
      // Filter by tour only when tour is an active granularity (the
      // selector is live); otherwise show all tours so deliveries on a
      // non-default tour aren't silently hidden. Kept in lock-step with
      // the totals card via the shared shell.effectiveTour.
      tour: shell.effectiveTour,
      is_past: shell.isPast,
      packing_station:
        shell.numberPackingStations > 1
          ? shell.selectedPackingStation
          : undefined,
      // In MIXED mode the boxes list excludes variations that are packed
      // in bulk (is_packed_bulk=True); BOXES mode already implies all
      // variations are boxed, so the filter would be a no-op.
      ...(packing_mode === "MIXED" ? { is_packed_bulk: false } : {}),
    }),
    [
      shell.selectedYear,
      shell.selectedWeek,
      shell.selectedDeliveryDay,
      shell.effectiveShareType,
      shell.selectedDeliveryStation,
      shell.effectiveTour,
      shell.isPast,
      shell.numberPackingStations,
      shell.selectedPackingStation,
      packing_mode,
    ],
  );

  const { data: rawData, isFetching } = useCommissioningPackingListList(
    listParams,
    {
      query: { enabled: shell.queryEnabled },
    },
  );

  const data = useMemo(
    () => (rawData as unknown as (PackingListRow & TableRecord)[]) ?? [],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningPackingListListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const processedData = useMemo(
    () =>
      data.map((item) => ({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      })),
    [data, getUnitLabel, getSizeLabel],
  );

  // --- All-stations PDF data ---
  const allStationsParams = useMemo<CommissioningPackingListListParams>(
    () => ({ ...listParams, packing_station: undefined }),
    [listParams],
  );

  const { data: rawAllStationsData } = useCommissioningPackingListList(
    allStationsParams,
    {
      query: {
        enabled: shell.queryEnabled && shell.numberPackingStations > 1,
      },
    },
  );

  const allStationsData = useMemo(
    () =>
      shell.queryEnabled && shell.numberPackingStations > 1
        ? ((rawAllStationsData as unknown as (PackingListRow & TableRecord)[]) ??
          null)
        : null,
    [rawAllStationsData, shell.queryEnabled, shell.numberPackingStations],
  );

  const allStationsPages = useMemo<PackingStationPage[] | null>(() => {
    if (!allStationsData || !shell.shareTypeVariations.length) return null;

    const variationKeys = shell.shareTypeVariations.map(
      (v: ShareTypeVariationOption) => `variation_${v.id}`,
    );

    const grouped = new Map<number, TableRecord[]>();
    for (const item of allStationsData) {
      const station = (item.packing_station as number) ?? 1;
      if (!grouped.has(station)) grouped.set(station, []);
      grouped.get(station)!.push({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      });
    }

    const sortedStations = [...grouped.keys()].sort((a, b) => a - b);
    if (sortedStations.length === 0) return null;

    return sortedStations.map((station) => {
      const items = grouped.get(station)!;
      const totalsMap = new Map<string, number>();
      for (const vk of variationKeys) {
        let sum = 0;
        for (const item of items) sum += Number(item[vk] ?? 0);
        totalsMap.set(vk, sum);
      }

      const variationsTotals = shell.shareTypeVariations
        .map((v: ShareTypeVariationOption) => ({
          id: v.id,
          size: v.size,
          totalQuantity: totalsMap.get(`variation_${v.id}`) ?? 0,
        }))
        .filter((vt: { totalQuantity: number }) => vt.totalQuantity > 0);

      return {
        stationNumber: station,
        data: items,
        variationsTotals,
      };
    });
  }, [allStationsData, shell.shareTypeVariations, getUnitLabel, getSizeLabel]);

  const shareTypeVariationColumns = useMemo<
    EditableColumnConfig<TableRecord>[]
  >(
    () =>
      shell.shareTypeVariations.map(
        (
          variation: ShareTypeVariationOption,
        ): EditableColumnConfig<TableRecord> => ({
          title: t(`commissioning.${variation.size}`),
          dataIndex: `variation_${variation.id}`,
          key: `variation_${variation.id}`,
          inputType: "positive_integer",
          align: "center",
          width: "5em",
          render: (value: unknown) => {
            if (value === null || value === undefined || value === "") return "";
            const n = Number(value);
            // Hide zeros — matches the mobile card's filter
            // ``v.value !== 0`` so empty buckets look the same on
            // desktop and PDF.
            if (!Number.isFinite(n) || n === 0) return "";
            return format(n, 0);
          },
          pdf: {
            include: true,
            width: widthVariation,
            align: "center",
            dataKey: `variation_${variation.id}`,
            title: t(`commissioning.${variation.size}`),
          },
        }),
      ),
    [shell.shareTypeVariations, t, format],
  );

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

    return [...baseColumns, ...shareTypeVariationColumns, ...endColumns];
  }, [
    t,
    shareTypeVariationColumns,
    widthNote,
    shareArticleColumn,
    amountUnitSizeColumns,
    noteColumn,
  ]);

  const apiFunctions = useMemo<ApiFunctions>(
    () => wrapApiFunctions({}),
    [],
  );

  const generateFilename = useMemo(
    () => shell.generateFilename(t("commissioning.packing_list")),
    [shell, t],
  );

  const shareTypeName = useMemo(
    () =>
      shell.shareTypes.find(
        (st: ShareTypeOption) => st.id === shell.selectedShareType,
      )?.name ?? "",
    [shell.shareTypes, shell.selectedShareType],
  );

  return (
    <>
      {!isMobile && (
        <div
          className="section-divider"
          style={{ display: "flex", gap: "1em" }}
        >
          <PackingListPDFGenerator
            data={processedData.length > 0 ? processedData : null}
            year={shell.selectedYear}
            week={shell.selectedWeek}
            dayName={
              shell.selectedDeliveryDay !== null
                ? getDayName(shell.selectedDeliveryDay, t)
                : ""
            }
            shareType={shareTypeName}
            variations={shell.shareTypeVariations}
            variationsTotals={shell.variationsTotals}
            packingStation={
              shell.numberPackingStations > 1
                ? shell.selectedPackingStation
                : null
            }
            showSize={showSize}
            filename={generateFilename}
            buttonText={t("download.packing_list")}
            t={t}
          />
          {shell.numberPackingStations > 1 && (
            <PackingListAllStationsPDFGenerator
              pages={allStationsPages}
              year={shell.selectedYear}
              week={shell.selectedWeek}
              dayName={
                shell.selectedDeliveryDay !== null
                  ? getDayName(shell.selectedDeliveryDay, t)
                  : ""
              }
              shareType={shareTypeName}
              variations={shell.shareTypeVariations}
              showSize={showSize}
              filename={generatePdfFilename([
                generateFilename,
                t("commissioning.all_packing_stations"),
              ])}
              buttonText={t("download.packing_list_all_stations")}
              t={t}
            />
          )}
        </div>
      )}

      <EditableTable
        key={`${shell.selectedYear}-${shell.selectedWeek}-${shell.selectedDeliveryDay}`}
        columns={columns as EditableColumnConfig[]}
        apiFunctions={apiFunctions}
        initialData={data}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={READ_ONLY_PERMISSION}
        className="w-max custom-forecast-table"
        renderMobileCard={(record: TableRecord) => (
          <PackingListBoxesMobileCard
            key={String(record.key)}
            record={record}
            shareTypeVariations={
              shell.shareTypeVariations as ShareTypeVariationOption[]
            }
          />
        )}
      />

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.packing_list_boxes")}
        </ExplainerText>
      )}
    </>
  );
}
