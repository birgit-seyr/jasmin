/**
 * The market prices of one ISO week: each PLU's gross price and origin. The
 * office copies selected prices into the next week, puts them on sale or takes
 * them off it, exports the week for the scales and prints the price list by
 * product group.
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
  useMarketArticles,
  useMarketPricesColumns,
} from "@features/commissioning/hooks";
import MarketPriceGroupCounts from "@features/commissioning/components/MarketPriceGroupCounts";
import MarketPriceListPrint from "@features/commissioning/components/MarketPriceListPrint";
import MarketPricesBulkActions from "@features/commissioning/components/MarketPricesBulkActions";
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
  const data = useMemo<TableRecord[]>(
    () => (prices ?? []) as unknown as TableRecord[],
    [prices],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningMarketPricesListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const { marketArticles } = useMarketArticles();
  const columns = useMarketPricesColumns({ marketArticles });

  const {
    selectedRowKeys,
    onSelectedRowsChange,
    rowSelection,
    clearSelection,
  } = useTableRowSelection((record: TableRecord) => record.key === -1 || isPast);

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
      const label =
        price.product_group_number == null
          ? t("commissioning.market_price_list_without_group")
          : `${price.product_group_number} ${price.product_group_name ?? ""}`;
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
        <MarketPriceListPrint
          key={`${selectedYear}-${selectedWeek}`}
          groups={priceListGroups}
          isReady={!isFetching}
          year={selectedYear}
          week={selectedWeek}
        />
        {isOffice && (
          <Button
            onClick={handleScaleExport}
            loading={exporting}
            disabled={data.length === 0}
          >
            {t("commissioning.scale_export")}
          </Button>
        )}
      </div>
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
        key={`${selectedYear}-${selectedWeek}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="name"
        initialData={data}
        loading={isFetching}
        customSave={customSave}
        customEdit={customEdit}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
        rowSelection={rowSelection}
        onSelectedRowsChange={onSelectedRowsChange}
        selectedRowKeys={selectedRowKeys}
        uniqueCheck={["market_article"]}
        uniqueCheckMessage={t("validation.unique.market_price")}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.market_prices")}
      </ExplainerText>
    </div>
  );
}
