import { Alert, Tabs } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRoles } from "@shared/auth";
import {
  DeliveryNoteModal,
  InvoiceModal,
} from "@features/commissioning/modals";
import { DaySelector, ResellerSelector, WeekSelector } from "@shared/selectors";
import {
  EditableTable,
  gatedByPermission,
  gatedByPermissionOnlyEdit,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, LabeledSwitch, ToolTipIcon } from "@shared/ui";
import { useOrderColumns } from "@features/commissioning/hooks";
// Imported directly from the source module (not the ``hooks`` barrel) to
// avoid a Rollup chunk cycle: the barrel re-exports ``useOrdersData`` while
// ``useOrdersData`` transitively depends back on the barrel.
import {
  useOrdersData,
  type OrderDays,
} from "@features/commissioning/hooks/useOrdersData";
import { OrderDaySelectors } from "@features/commissioning/selectors/OrderDaySelectors";
import { OrderInfoPanel } from "@features/commissioning/components/OrderInfoPanel";

export default function Orders() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();

  const orderData = useOrdersData();
  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    selectedDay,
    setSelectedDay,
    selectedReseller,
    setSelectedReseller,
    activeTab,
    setActiveTab,
    showOnlyOrderedOffers,
    setShowOnlyOrderedOffers,
    filteredDataOffers,
    filteredDataArticles,
    filteredDataArticlesCount,
    filteredDataOffersCount,
    dataCrates,
    dataCratesCount,
    daysWithOrders,
    orderState,
    orderDays,
    setOrderDays,
    oddDefaults,
    orderNote,
    setOrderNote,
    totalSum,
    apiFunctions,
    apiFunctionsCrates,
    listParams,
    fetchData,
    handleDataChange,
    handleCratesDataChange,
    handleSaveSuccess,
    handleFinalizeInvoicesSuccess,
    handleFinalizeDNSuccess,
    handleCreateInvoiceSuccess,
    calculatePricePerUnit,
    data,
    loading,
    summaryColumns,
    summaryDataOffers,
    summaryDataArticles,
    summaryDataCrates,
    defaultTaxRateArticles,
  } = orderData;

  const {
    columnsOffers,
    columnsArticles,
    filteredColumnsCrates,
    createCustomSave,
    createCustomSaveOffers,
  } = useOrderColumns({
    params: listParams,
    // useOrderColumns is internally typed against Record<string, unknown>[]
    // (pre-dating the CrateOrderContentRow tightening in useOrdersData).
    // Cast bridges the row-shape gap without forcing the hook to update.
    dataCrates: dataCrates as unknown as Record<string, unknown>[],
  });

  // Modal state
  const [modalVisibleDeliveryNote, setModalVisibleDeliveryNote] =
    useState(false);
  const [modalVisibleInvoice, setModalVisibleInvoice] = useState(false);

  const formattedOrderNumber = useMemo(() => {
    if (!orderState.orderNumber) return "---";
    return `${orderState.usedOrderNumberPrefix}-${orderState.orderNumber}`;
  }, [orderState.orderNumber, orderState.usedOrderNumberPrefix]);

  const customSave = useMemo(
    () =>
      createCustomSave(
        selectedYear,
        selectedWeek,
        selectedDay,
        selectedReseller,
        orderDays,
        // See note on `dataCrates` above re: hook row-shape gap.
        data as unknown as Record<string, unknown>[],
        calculatePricePerUnit,
      ),
    [
      createCustomSave,
      selectedYear,
      selectedWeek,
      selectedDay,
      selectedReseller,
      orderDays,
      data,
      calculatePricePerUnit,
    ],
  );

  const customSaveOffers = useMemo(
    () =>
      createCustomSaveOffers(
        selectedYear,
        selectedWeek,
        selectedDay,
        selectedReseller,
        orderDays,
      ),
    [
      createCustomSaveOffers,
      selectedYear,
      selectedWeek,
      selectedDay,
      selectedReseller,
      orderDays,
    ],
  );

  const customSaveCrates = useCallback(
    (transformedData: Record<string, unknown>) => {
      if (!transformedData.crate_type) return null;
      return {
        ...transformedData,
        year: selectedYear,
        delivery_week: selectedWeek,
        day_number: selectedDay,
        reseller: selectedReseller,
      };
    },
    [selectedYear, selectedWeek, selectedDay, selectedReseller],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { size: "M", tax_rate: defaultTaxRateArticles };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      // Order rows derived from offers don't carry a ``tax_rate`` (offers
      // store price tiers, not VAT), so editing one with an empty
      // ``tax_rate`` would send ``null`` to the backend and the
      // OrderContent serializer would reject the save. Default to the
      // tenant's ``default_tax_rate_articles`` and show it in the form
      // so the user can override before save if needed.
      if (record.tax_rate == null || record.tax_rate === "") {
        const filled = { ...record, tax_rate: defaultTaxRateArticles };
        form.setFieldsValue({ tax_rate: defaultTaxRateArticles });
        return filled;
      }
      return record;
    },
    [defaultTaxRateArticles],
  );

  const customDeleteCrates = useCallback(
    (record: TableRecord) => ({
      crate_type: record.crate_type,
      order_id: orderState.orderId,
      year: selectedYear,
      delivery_week: selectedWeek,
      day_number: selectedDay,
      reseller: selectedReseller,
    }),
    [
      orderState.orderId,
      selectedYear,
      selectedWeek,
      selectedDay,
      selectedReseller,
    ],
  );

  const canModify =
    isOffice && !orderState.deliveryNoteNumber && !orderState.invoiceNumber;
  const canModifyPermissions = useMemo(
    () => gatedByPermission(canModify),
    [canModify],
  );
  const canModifyOnlyEditPermissions = useMemo(
    () => gatedByPermissionOnlyEdit(canModify),
    [canModify],
  );

  const handleDayChange = useCallback(
    (field: keyof OrderDays, val: number | null) => {
      setOrderDays((prev) => ({ ...prev, [field]: val }));
    },
    [setOrderDays],
  );

  const dayConfigs = useMemo(
    () => [
      {
        label: t("commissioning.harvest"),
        field: "harvesting_day" as const,
        defaultField: "default_harvesting_day" as const,
      },
      {
        label: t("commissioning.washing"),
        field: "washing_day" as const,
        defaultField: "default_washing_day" as const,
      },
      {
        label: t("commissioning.commissioning"),
        field: "packing_day" as const,
        defaultField: "default_packing_day" as const,
      },
    ],
    [t],
  );

  const tabItems = useMemo(
    () => [
      {
        key: "offers",
        label: (
          <span>
            {t("commissioning.orders_from_offers")} ({filteredDataOffersCount})
          </span>
        ),
        children:
          !loading &&
          !showOnlyOrderedOffers &&
          filteredDataOffers.length === 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: "1em" }}
              message={t("commissioning.no_offers_for_week")}
            />
          ) : (
            <div>
              <div style={{ marginTop: "1em", marginBottom: "1em" }}>
                <LabeledSwitch
                  value={showOnlyOrderedOffers}
                  onChange={setShowOnlyOrderedOffers}
                  label={t("commissioning.show_only_ordered_offers")}
                  withEyeIcons
                />
              </div>
              <h6>{t("commissioning.setting_crates_from_ordered_offers")}</h6>
              <EditableTable
                key={`${selectedYear}-${selectedWeek}-${selectedDay}-${selectedReseller}-offers`}
                columns={columnsOffers}
                apiFunctions={apiFunctions}
                focusIndex="share_article_name"
                initialData={filteredDataOffers as unknown as TableRecord[]}
                loading={loading}
                onDataChange={handleDataChange as (data: TableRecord[]) => void}
                onSaveSuccess={handleSaveSuccess}
                customSave={customSaveOffers}
                customEdit={customEdit}
                permissions={canModifyOnlyEditPermissions}
                summaryRows={[
                  {
                    columns: summaryColumns,
                    label: t("commissioning.sum"),
                    data: summaryDataOffers,
                    suffix: "",
                    summaryLabelColSpan: 3,
                  },
                ]}
              />
            </div>
          ),
      },
      {
        key: "articles",
        label: (
          <span>
            {t("commissioning.orders_from_articles")} (
            {filteredDataArticlesCount})
          </span>
        ),
        children: (
          <div>
            <h6>{t("commissioning.setting_crates_from_ordered_articles")}</h6>
            <EditableTable
              key={`${selectedYear}-${selectedWeek}-${selectedDay}-${selectedReseller}-articles`}
              columns={columnsArticles}
              apiFunctions={apiFunctions}
              focusIndex="share_article_name"
              initialData={filteredDataArticles as unknown as TableRecord[]}
              loading={loading}
              onDataChange={handleDataChange as (data: TableRecord[]) => void}
              onSaveSuccess={handleSaveSuccess}
              customSave={customSave}
              customEdit={customEdit}
              uniqueCheck={["share_article", "unit", "size"]}
              uniqueCheckMessage={t(
                "validation.unique.share_article_unit_size_must_be_unique",
              )}
              permissions={canModifyPermissions}
              summaryRows={[
                {
                  columns: summaryColumns,
                  label: t("commissioning.sum"),
                  data: summaryDataArticles,
                  suffix: "",
                  summaryLabelColSpan: 3,
                },
              ]}
            />
          </div>
        ),
      },
      {
        key: "crates",
        label: (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5em",
            }}
          >
            {t("commissioning.crates_in_orders")} ({dataCratesCount})
            <ToolTipIcon title={t("tooltip.crates_in_orders")} />
          </span>
        ),
        children: (
          <div style={{ width: "70%" }}>
            <EditableTable
              key={`${selectedYear}-${selectedWeek}-${selectedDay}-${selectedReseller}-crates`}
              columns={filteredColumnsCrates as EditableColumnConfig[]}
              apiFunctions={apiFunctionsCrates}
              focusIndex="crate_type_name"
              initialData={dataCrates as unknown as TableRecord[]}
              loading={loading}
              onDataChange={
                handleCratesDataChange as (data: TableRecord[]) => void
              }
              onSaveSuccess={handleSaveSuccess}
              customSave={customSaveCrates}
              customEdit={customEdit}
              customDelete={customDeleteCrates}
              uniqueCheck={["crate_type"]}
              uniqueCheckMessage={t("validation.unique.crate_type")}
              permissions={canModifyPermissions}
              summaryRows={[
                {
                  columns: summaryColumns,
                  label: t("commissioning.sum"),
                  data: summaryDataCrates,
                  suffix: "",
                },
              ]}
            />
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      t,
      selectedYear,
      selectedWeek,
      selectedDay,
      selectedReseller,
      showOnlyOrderedOffers,
      setShowOnlyOrderedOffers,
      canModify,
      columnsOffers,
      columnsArticles,
      filteredColumnsCrates,
      apiFunctions,
      apiFunctionsCrates,
      listParams,
      filteredDataOffers,
      filteredDataArticles,
      dataCrates,
      filteredDataOffersCount,
      filteredDataArticlesCount,
      dataCratesCount,
      handleDataChange,
      handleCratesDataChange,
      handleSaveSuccess,
      customSave,
      customSaveOffers,
      customSaveCrates,
      customEdit,
      customDeleteCrates,
      summaryColumns,
      summaryDataOffers,
      summaryDataArticles,
      summaryDataCrates,
      orderState.deliveryNoteNumber,
      orderState.invoiceNumber,
    ],
  );

  return (
    <div>
      <h1>{t("commissioning.orders")}</h1>
      <div>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={(v) => v !== null && setSelectedWeek(v)}
        />
        <DaySelector
          selectedYear={selectedYear}
          selectedWeek={selectedWeek}
          selectedDay={selectedDay}
          setSelectedDay={(v) => v !== null && setSelectedDay(v)}
          days={[0, 1, 2, 3, 4, 5]}
          suffix={t("commissioning.delivery_day")}
          usesDaysWithOrders={true}
          daysWithOrders={daysWithOrders}
        />
      </div>
      <div style={{ marginTop: "1em" }}>
        <ResellerSelector
          selectedReseller={selectedReseller}
          setSelectedReseller={setSelectedReseller}
          year={selectedYear}
          delivery_week={selectedWeek}
          delivery_day={String(selectedDay)}
          preserveSelection={true}
        />
      </div>

      {selectedReseller && (
        <OrderDaySelectors
          days={dayConfigs}
          orderDays={orderDays}
          oddDefaults={oddDefaults}
          orderId={orderState.orderId}
          onDayChange={handleDayChange}
        />
      )}

      <OrderInfoPanel
        orderState={orderState}
        formattedOrderNumber={formattedOrderNumber}
        totalSum={totalSum}
        fetchData={fetchData}
        handleFinalizeDNSuccess={handleFinalizeDNSuccess}
        handleFinalizeInvoicesSuccess={handleFinalizeInvoicesSuccess}
        handleCreateInvoiceSuccess={handleCreateInvoiceSuccess}
        onOpenDeliveryNoteModal={() => setModalVisibleDeliveryNote(true)}
        onOpenInvoiceModal={() => setModalVisibleInvoice(true)}
        orderNote={orderNote}
        onOrderNoteChange={setOrderNote}
      />

      <div className="section-divider--lg">
        <Tabs
          type="card"
          size="large"
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          className="orders-view-switcher"
        />
      </div>

      <ExplainerText title={t("common.info")}>
        {t("explainers.orders")}
      </ExplainerText>

      <DeliveryNoteModal
        visible={modalVisibleDeliveryNote}
        onClose={() => {
          setModalVisibleDeliveryNote(false);
          fetchData();
        }}
        deliveryNoteId={orderState.deliveryNoteId}
      />
      <InvoiceModal
        visible={modalVisibleInvoice}
        onClose={() => {
          setModalVisibleInvoice(false);
          fetchData();
        }}
        invoiceId={orderState.invoiceId}
      />
    </div>
  );
}
