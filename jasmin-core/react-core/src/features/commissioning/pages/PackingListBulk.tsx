import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  getCommissioningPackingListBulkListQueryKey,
  useCommissioningPackingListBulkList,
  useCommissioningPackingListList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningPackingListBulkListParams,
  CommissioningPackingListListParams,
  PackingListBulkRow,
  PackingListRow,
} from "@shared/api/generated/models";
import { PackingListBulkMobileCard } from "@features/commissioning/components/mobileCards";
import {
  PackingListBulkPDFGenerator,
  PackingListPDFGenerator,
} from "@features/commissioning/pdfs";
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
import {
  useInvalidateAfterTableMutation,
  useIsMobile,
  useNoteColumn,
  useSizeOptions,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import type { ShareTypeOption } from "@hooks/useShareTypes";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import { getDayName } from "@shared/utils";

import PackingListShell, {
  type PackingListShellState,
} from "./PackingListShell";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
};

const widthShareArticle = "30%";
const widthAmountUnitSize = "10%";
const widthTotalAmount = "10%";

// Bulk endpoint accepts ``delivery_station`` as of the per-station rewrite,
// and ``is_packed_bulk`` for the MIXED packing-mode split. Generated params
// type lags until ``npm run generate-api`` is rerun.
type BulkParams = CommissioningPackingListBulkListParams & {
  delivery_station?: string;
  is_packed_bulk?: boolean;
};

export default function PackingListBulk() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const isMobile = useIsMobile();
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { noteColumn } = useNoteColumn();
  const { getSetting } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";

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

  const renderBody = useCallback(
    (shell: PackingListShellState) => {
      const listParams: BulkParams = {
        year: shell.selectedYear,
        delivery_week: shell.selectedWeek ?? undefined,
        day_number: shell.selectedDeliveryDay ?? undefined,
        share_type: shell.effectiveShareType || undefined,
        is_past: shell.isPast,
        delivery_station: shell.selectedDeliveryStation ?? undefined,
        // In MIXED mode the bulk list must only sum variations actually
        // packed in bulk (is_packed_bulk=True); BULK mode already implies
        // all variations are bulk, so the filter would be a no-op.
        ...(packing_mode === "MIXED" ? { is_packed_bulk: true } : {}),
      } as BulkParams;

      return (
        <BulkBody
          shell={shell}
          listParams={listParams}
          columns={columns}
          apiFunctions={apiFunctions}
          getUnitLabel={getUnitLabel}
          getSizeLabel={getSizeLabel}
          queryClient={queryClient}
          isMobile={isMobile}
          packing_mode={packing_mode}
          t={t}
        />
      );
    },
    [
      apiFunctions,
      columns,
      getSizeLabel,
      getUnitLabel,
      isMobile,
      packing_mode,
      queryClient,
      t,
    ],
  );

  return (
    <PackingListShell titleKey="commissioning.packing_list_bulk" mode="bulk">
      {renderBody}
    </PackingListShell>
  );
}

// Split out so the hooks below (useQuery, useMemo on per-shell-state values)
// re-evaluate when the shell hands new state to the render-prop.
function BulkBody({
  shell,
  listParams,
  columns,
  apiFunctions,
  getUnitLabel,
  getSizeLabel,
  queryClient,
  isMobile,
  packing_mode,
  t,
}: {
  shell: PackingListShellState;
  listParams: BulkParams;
  columns: EditableColumnConfig<TableRecord>[];
  apiFunctions: ApiFunctions;
  getUnitLabel: (unit: string) => string;
  getSizeLabel: (size: string) => string;
  queryClient: ReturnType<typeof useQueryClient>;
  isMobile: boolean;
  packing_mode: "BOXES" | "BULK" | "MIXED";
  t: ReturnType<typeof useTranslation>["t"];
}) {
  const { data: rawData, isFetching } = useCommissioningPackingListBulkList(
    listParams as unknown as CommissioningPackingListBulkListParams,
    { query: { enabled: shell.queryEnabled } },
  );

  // Brand strip data for the member-facing PDF — see ``ListPDFHeader``.
  // Wrapped in ``useMemo`` so the props identity is stable and the PDF
  // generator doesn't see a fresh ``tenant`` object on every render.
  const { tenantName, logoUrl, tenant, getSetting } = useTenant();
  // Mirror the on-screen size column: hidden unless ``show_size_column`` is on.
  const showSize = Boolean(getSetting("show_size_column"));
  const memberPdfTenant = useMemo(
    () => ({
      name: tenantName,
      logoUrl,
      email: (tenant?.email as string) || "",
      phone: (tenant?.phone_number as string) || "",
    }),
    [tenantName, logoUrl, tenant],
  );

  // Member-facing per-variation PDF needs the boxes-shape data
  // (rows keyed by (article × variation)) — the bulk endpoint only
  // returns per-station sums. In MIXED mode we also restrict to bulk
  // variations so the PDF columns line up with what members pack.
  // ``is_packed_bulk`` is sent until the generated params type catches up.
  const perVariationParams = useMemo(
    () =>
      ({
        year: shell.selectedYear,
        delivery_week: shell.selectedWeek ?? undefined,
        day_number: shell.selectedDeliveryDay ?? undefined,
        share_type: shell.effectiveShareType || undefined,
        is_past: shell.isPast,
        delivery_station: shell.selectedDeliveryStation ?? undefined,
        ...(packing_mode === "MIXED" ? { is_packed_bulk: true } : {}),
      }) as unknown as CommissioningPackingListListParams,
    [
      shell.selectedYear,
      shell.selectedWeek,
      shell.selectedDeliveryDay,
      shell.effectiveShareType,
      shell.isPast,
      shell.selectedDeliveryStation,
      packing_mode,
    ],
  );

  const { data: rawPerVariationData } = useCommissioningPackingListList(
    perVariationParams,
    {
      query: {
        enabled: shell.queryEnabled && !!shell.selectedDeliveryStation,
      },
    },
  );

  const data = useMemo(
    () => (rawData as unknown as (PackingListBulkRow & TableRecord)[]) ?? [],
    [rawData],
  );

  // PDF needs ``unit_label`` / ``size_label`` for the centred cells —
  // raw rows only carry the raw enum codes.
  const perVariationProcessed = useMemo(
    () =>
      (
        (rawPerVariationData as unknown as (PackingListRow & TableRecord)[]) ??
        []
      ).map((item) => ({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      })),
    [rawPerVariationData, getUnitLabel, getSizeLabel],
  );

  // In MIXED mode the member-facing PDF must only show bulk-packed
  // variation columns (matches the restricted per-variation rows).
  const memberFacingVariations = useMemo(
    () =>
      packing_mode === "MIXED"
        ? shell.shareTypeVariations.filter(
            (v: ShareTypeVariationOption) =>
              (v as ShareTypeVariationOption & { is_packed_bulk?: boolean })
                .is_packed_bulk === true,
          )
        : shell.shareTypeVariations,
    [shell.shareTypeVariations, packing_mode],
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

  const processedData = useMemo(
    () =>
      data.map((item) => ({
        ...item,
        unit_label: item.unit ? getUnitLabel(item.unit as string) : "",
        size_label: item.size ? getSizeLabel(item.size as string) : "",
      })),
    [data, getUnitLabel, getSizeLabel],
  );

  const stationName = useMemo(() => {
    const firstRow = data[0];
    return (firstRow?.delivery_station_name as string | undefined) ?? undefined;
  }, [data]);

  const filename = useMemo(
    () => shell.generateFilename(t("commissioning.packing_list_bulk")),
    [shell, t],
  );

  const memberFilename = useMemo(
    () => shell.generateFilename(t("commissioning.packing_list_bulk_member")),
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
          <PackingListBulkPDFGenerator
            data={processedData}
            year={shell.selectedYear}
            week={shell.selectedWeek}
            dayName={
              shell.selectedDeliveryDay !== null
                ? getDayName(shell.selectedDeliveryDay, t)
                : ""
            }
            shareType={shareTypeName}
            deliveryStationName={stationName}
            showSize={showSize}
            filename={filename}
            buttonText={t("download.packing_list_bulk")}
            t={t}
          />

          <PackingListPDFGenerator
            data={perVariationProcessed}
            year={shell.selectedYear}
            week={shell.selectedWeek}
            dayName={
              shell.selectedDeliveryDay !== null
                ? getDayName(shell.selectedDeliveryDay, t)
                : ""
            }
            shareType={shareTypeName}
            variations={memberFacingVariations}
            titleKey="commissioning.packing_list_bulk_member"
            tenant={memberPdfTenant}
            showSize={showSize}
            filename={memberFilename}
            buttonText={t("download.packing_list_bulk_member")}
            t={t}
          />
        </div>
      )}

      {shell.queryEnabled ? (
        <EditableTable
          key={`${shell.selectedYear}-${shell.selectedWeek}-${shell.selectedDeliveryDay}-${shell.selectedDeliveryStation}`}
          columns={columns as EditableColumnConfig[]}
          apiFunctions={apiFunctions}
          initialData={data}
          loading={isFetching}
          onSaveSuccess={onSaveSuccess}
          onDeleteSuccess={onDeleteSuccess}
          permissions={READ_ONLY_PERMISSION}
          renderMobileCard={(record: TableRecord) => (
            <PackingListBulkMobileCard
              key={String(record.key)}
              record={record}
            />
          )}
        />
      ) : (
        <div className="empty-state-block">
          {!shell.selectedDeliveryDay && !shell.selectedShareType
            ? t("commissioning.please_select_delivery_day_and_share_type")
            : !shell.selectedDeliveryDay
              ? t("commissioning.please_select_delivery_day")
              : !shell.selectedShareType
                ? t("commissioning.please_select_share_type")
                : t("commissioning.please_select_delivery_station")}
        </div>
      )}

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.packing_list_bulk")}
        </ExplainerText>
      )}
    </>
  );
}
