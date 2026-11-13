/**
 * The market prices of one ISO week: each PLU's gross price and origin. The
 * office copies selected prices into the next week, puts them on sale or takes
 * them off it, exports the week for the scales and prints the price list and
 * the order list by product group, and the member list for the market stand.
 */

import { useQueryClient } from "@tanstack/react-query";
import { Button } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningMarketPricesCreate,
  commissioningMarketPricesDestroy,
  commissioningMarketPricesPartialUpdate,
  commissioningMarketPricesScaleExportRetrieve,
  getCommissioningMarketPricesListQueryKey,
  useCommissioningMarketPricesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningMarketPricesListParams,
  MarketPrice,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { WeekSelector } from "@shared/selectors";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, PastWarningMessage } from "@shared/ui";
import {
  downloadBlob,
  generatePdfFilename,
  isWeekInPast,
  notify,
} from "@shared/utils";
import { getErrorMessage, readBlobErrorBody } from "@shared/utils/apiError";
import { formatWeekLabel } from "@shared/utils/weekLabels";
import {
  useCurrency,
  useInvalidateAfterTableMutation,
  useTableRowSelection,
  useYearWeekState,
} from "@hooks/index";
import { useUnitOptions } from "@hooks/useUnitOptions";
import {
  isPickedGroup,
  marketProductGroupLabel,
  useMarketArticles,
  useMarketOrderListGroups,
  useMarketPricesColumns,
} from "@features/commissioning/hooks";
import MarketMemberListPrint from "@features/commissioning/components/MarketMemberListPrint";
import MarketPriceGroupCounts from "@features/commissioning/components/MarketPriceGroupCounts";
import MarketPricesBulkActions from "@features/commissioning/components/MarketPricesBulkActions";
import MarketWeekListsPrint from "@features/commissioning/components/MarketWeekListsPrint";
import type { MarketPriceListGroup } from "@features/commissioning/pdfs/exports/MarketPriceListPDF";

type MarketPriceRow = MarketPrice & TableRecord;

export default function MarketPrices() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isOffice } = useRoles();
  const { formatCurrency } = useCurrency();
  const { getUnitLabel } = useUnitOptions();
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const permissions = useMemo(
    () => gatedByPermission(isOffice && !isPast),
    [isOffice, isPast],
  );
  const [exporting, setExporting] = useState(false);
  // The labels of the product groups picked for the lists; none picked is all.
  const [pickedGroups, setPickedGroups] = useState<string[]>([]);

  const listParams = useMemo<CommissioningMarketPricesListParams>(
    () => ({ year: selectedYear, delivery_week: selectedWeek }),
    [selectedYear, selectedWeek],
  );
  // ``isFetching``, not ``isLoading``: with the global ``staleTime: 0`` a
  // revisited week has ``isLoading === false`` while it refetches.
  const { data: prices, isFetching } =
    useCommissioningMarketPricesList(listParams);
  // The cached rows themselves, not copies: the table keeps a row it saved
  // only while the list hands back the same object for it.
  const allPrices = useMemo<TableRecord[]>(
    () => (prices ?? []) as unknown as TableRecord[],
    [prices],
  );
  // The product groups picked for the lists narrow the table too.
  const shownPrices = useMemo<TableRecord[]>(() => {
    const rows = (prices ?? []).filter((price) =>
      isPickedGroup(
        pickedGroups,
        marketProductGroupLabel(
          price.product_group_number,
          price.product_group_name,
          t,
        ),
      ),
    );
    return rows as unknown as TableRecord[];
  }, [prices, pickedGroups, t]);
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningMarketPricesListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);
  // A new price is fetched into the week's list, so it shows under its own
  // product groups only and "select all pages" reaches it.
  const handleSaveSuccess = useCallback(
    (saved: TableRecord, action: "create" | "update") => {
      if (action === "create") invalidateData();
      onSaveSuccess(saved, action);
    },
    [invalidateData, onSaveSuccess],
  );

  const { marketArticles } = useMarketArticles();
  const orderListGroups = useMarketOrderListGroups(prices);
  // A new price can only be for a PLU of the picked groups, so it stays in the
  // table once saved.
  const pickableArticles = useMemo(() => {
    if (pickedGroups.length === 0 || !orderListGroups) return marketArticles;
    const picked = new Set(
      orderListGroups
        .filter((group) => isPickedGroup(pickedGroups, group.label))
        .flatMap((group) => group.rows.map((row) => row.id)),
    );
    return marketArticles.filter((plu) => picked.has(plu.id));
  }, [marketArticles, orderListGroups, pickedGroups]);
  const columns = useMarketPricesColumns({ marketArticles: pickableArticles });

  const {
    selectedRowKeys,
    onSelectedRowsChange,
    rowSelection,
    clearSelection,
  } = useTableRowSelection(
    (record: TableRecord) => record.key === -1 || isPast,
    { allRows: shownPrices },
  );

  // No ``list`` here: the page owns the data, so the table never fetches it.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<MarketPriceRow>({
        create: (payload) => commissioningMarketPricesCreate(payload),
        update: (id, payload) =>
          commissioningMarketPricesPartialUpdate(id, payload),
        delete: (id) => commissioningMarketPricesDestroy(id),
      }),
    [],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      year: selectedYear,
      delivery_week: selectedWeek,
    }),
    [selectedYear, selectedWeek],
  );

  // A new price is on sale unless the office unticks it.
  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key !== -1) return record;
      form.setFieldsValue({ is_active: true });
      return { ...record, is_active: true };
    },
    [],
  );

  const handleScaleExport = async () => {
    setExporting(true);
    try {
      const file = await commissioningMarketPricesScaleExportRetrieve(listParams);
      downloadBlob(
        file,
        `${generatePdfFilename([t("commissioning.scale_export"), selectedYear, formatWeekLabel(selectedWeek, t)])}.xlsx`,
      );
    } catch (error) {
      notify.error(
        getErrorMessage(
          await readBlobErrorBody(error),
          t("common.error_exporting"),
        ),
      );
    } finally {
      setExporting(false);
    }
  };

  // The active prices by product group, in the list's order (group number,
  // then PLU), the PLUs without a group last.
  const priceListGroups = useMemo<MarketPriceListGroup[] | null>(() => {
    if (!prices) return null;
    const groups = new Map<string, MarketPriceListGroup>();
    for (const price of prices) {
      if (!price.is_active) continue;
      const label = marketProductGroupLabel(
        price.product_group_number,
        price.product_group_name,
        t,
      );
      const group = groups.get(label) ?? { label, rows: [] };
      group.rows.push({
        id: price.id,
        plu_number: price.plu_number,
        name: [price.name, price.origin].filter(Boolean).join(" "),
        price_text: `${formatCurrency(Number(price.gross_price))}/${getUnitLabel(price.unit)}`,
        is_changed: price.is_changed,
      });
      groups.set(label, group);
    }
    return [...groups.values()];
  }, [prices, t, formatCurrency, getUnitLabel]);

  return (
    <div>
      <h1>{t("commissioning.market_prices")}</h1>
      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      <div className="button-row-spaced flex-center-y section-divider">
        <MarketWeekListsPrint
          key={`${selectedYear}-${selectedWeek}`}
          priceGroups={priceListGroups}
          orderGroups={orderListGroups}
          pickedGroups={pickedGroups}
          onPickedGroupsChange={setPickedGroups}
          isReady={!isFetching}
          year={selectedYear}
          week={selectedWeek}
        />
        {isOffice && (
          <Button
            onClick={handleScaleExport}
            loading={exporting}
            disabled={allPrices.length === 0}
          >
            {t("commissioning.scale_export")}
          </Button>
        )}
      </div>
      {isOffice && (
        <div className="button-row-spaced flex-center-y section-divider">
          <MarketMemberListPrint />
        </div>
      )}
      <MarketPriceGroupCounts groups={priceListGroups} />
      {isOffice && !isPast && (
        <MarketPricesBulkActions
          selectedRowKeys={selectedRowKeys}
          onClearSelection={clearSelection}
          onInvalidate={invalidateData}
        />
      )}
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      <EditableTable
        // One table per week and choice of groups: the table keeps a row
        // saved on this mount pinned, whatever its rows become.
        key={`${selectedYear}-${selectedWeek}-${pickedGroups.join("|")}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="name"
        initialData={shownPrices}
        loading={isFetching}
        customSave={customSave}
        customEdit={customEdit}
        onSaveSuccess={handleSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
        rowSelection={rowSelection}
        onSelectedRowsChange={onSelectedRowsChange}
        selectedRowKeys={selectedRowKeys}
        pagination={true}
        uniqueCheck={["market_article"]}
        uniqueCheckRows={allPrices}
        uniqueCheckMessage={t("validation.unique.market_price")}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.market_prices")}
      </ExplainerText>
    </div>
  );
}
