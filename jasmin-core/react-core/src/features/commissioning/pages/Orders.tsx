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
  SUMMARY_ROW_STYLE,
} from "@shared/tables";
import type {
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, LabeledSwitch, ToolTipIcon } from "@shared/ui";
import { useTenant } from "@hooks/index";
import { useOrderColumns } from "@features/commissioning/hooks";
// Imported directly from the source module (not the ``hooks`` barrel) to
// avoid a Rollup chunk cycle: the barrel re-exports ``useOrdersData`` while
// ``useOrdersData`` transitively depends back on the barrel.
import {
  useOrdersData,
  type OrderDays,
} from "@features/commissioning/hooks/useOrdersData";
import { refuseRepeatedCrateType } from "@features/commissioning/hooks/useDocumentCrateTable";
import { OrderDaySelectors } from "@features/commissioning/selectors/OrderDaySelectors";
import {
  missingOrderDays,
  orderDayConfigs,
} from "@features/commissioning/utils/orderDays";
import { OrderInfoPanel } from "@features/commissioning/components/OrderInfoPanel";
import "./Orders.css";

export default function Orders() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  // The setting gates crate CREATION (backend). The crates tab shows when the
  // tenant puts crates on documents OR crates already exist this week (see the
  // tab filter below) — an off-tenant simply has none, so the tab stays hidden.
  const showCratesOnDocuments = Boolean(
    getSetting("crates_should_be_on_documents", true),
  );

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
    handleFinalizeDeliveryNotesSuccess,
    handleCreateInvoiceSuccess,
    calculatePricePerUnit,
    data,
    loading,
    cratesLoading,
    summaryColumns,
    summaryDataOffers,
    summaryDataArticles,
    summaryDataCrates,
    defaultTaxRateArticles,
  } = useOrdersData();

  const {
    columnsOffers,
    columnsArticles,
    filteredColumnsCrates,
    createCustomSave,
    createCustomSaveOffers,
  } = useOrderColumns({
    params: listParams,
    dataCrates,
  });

  // Modal state
  const [deliveryNoteModalVisible, setDeliveryNoteModalVisible] =
    useState(false);
  const [invoiceModalVisible, setInvoiceModalVisible] = useState(false);

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
        // ``OrderContentRow`` builds on a generated interface, which has no
        // index signature to make it a ``Record``.
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

  // An order bills a crate type at each price, discount and VAT rate, one line
  // each, so the crate table holds no crate-type uniqueness; only a new line
  // must take a crate type the order doesn't list yet. ``listParams`` is the
  // selected slot (year, delivery week, day, reseller), which names the order.
  const customSaveCrates = useCallback(
    (transformedData: Record<string, unknown>, record: TableRecord) => {
      if (!transformedData.crate_type) return null;
      const message = t("validation.unique.crate_type");
      refuseRepeatedCrateType(dataCrates, transformedData, record, message);
      return { ...transformedData, ...listParams };
    },
    [listParams, dataCrates, t],
  );

  const customEdit = useCallback(
    <TRow extends TableRecord>(
      record: TRow,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ): TRow => {
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

  const handleDayChange = useCallback(
    (field: keyof OrderDays, val: number | null) => {
      setOrderDays((prev) => ({ ...prev, [field]: val }));
    },
    [setOrderDays],
  );

  const dayConfigs = useMemo(() => orderDayConfigs(t), [t]);

  // Editing must follow the ORDER's finalized flag (what the backend actually
  // gates on — see FinalizedProtectedMixin), NOT the presence of a delivery
  // note / invoice number. Keying off the DN number let deleting a not-yet-
  // finalized delivery note re-enable cells whose saves then fail server-side,
  // and also (mis)treated a directly-finalized order with no DN as editable.
  // Any save of a new order starts it, which needs every one of its days.
  const orderDaysMissing =
    selectedReseller != null &&
    missingOrderDays(dayConfigs, orderDays, orderState.orderId).length > 0;
  const canModify =
    isOffice && !orderState.isOrderFinalized && !orderDaysMissing;
  const canModifyPermissions = useMemo(
    () => gatedByPermission(canModify),
    [canModify],
  );
  const canModifyOnlyEditPermissions = useMemo(
    () => gatedByPermissionOnlyEdit(canModify),
    [canModify],
  );

  const tabItems = useMemo(
    () => [
      {
        key: "offers",
        label: (
          <span>
            <h3>
              {t("commissioning.orders_from_offers")} ({filteredDataOffersCount}
              )
            </h3>
          </span>
        ),
        children:
          !loading &&
          !showOnlyOrderedOffers &&
          filteredDataOffers.length === 0 ? (
            <Alert
              type="info"
              showIcon
              className="mt-1em"
              message={t("commissioning.no_offers_for_week")}
            />
          ) : (
            <div>
              <div className="mt-1em mb-1em">
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
                    style: SUMMARY_ROW_STYLE,
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
            <h3>
              {t("commissioning.orders_from_articles")} (
              {filteredDataArticlesCount})
            </h3>
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
                  style: SUMMARY_ROW_STYLE,
                },
              ]}
            />
          </div>
        ),
      },
      {
        key: "crates",
        label: (
          <span className="orders__tab-label">
            <h3>
              {t("commissioning.crates_in_orders")} ({dataCratesCount})
              <ToolTipIcon title={t("tooltip.crates_in_orders")} />
            </h3>
          </span>
        ),
        children: (
          <div className="orders__crates">
            <EditableTable
              key={`${selectedYear}-${selectedWeek}-${selectedDay}-${selectedReseller}-crates`}
              columns={filteredColumnsCrates}
              apiFunctions={apiFunctionsCrates}
              focusIndex="crate_type_name"
              initialData={dataCrates}
              loading={cratesLoading}
              onDataChange={handleCratesDataChange}
              onSaveSuccess={handleSaveSuccess}
              customSave={customSaveCrates}
              customEdit={customEdit}
              customDelete={customDeleteCrates}
              permissions={canModifyPermissions}
              summaryRows={[
                {
                  columns: summaryColumns,
                  label: t("commissioning.sum"),
                  data: summaryDataCrates,
                  suffix: "",
                  style: SUMMARY_ROW_STYLE,
                },
              ]}
            />
          </div>
        ),
      },
    ]
      // Presence-based: keep the crates tab when the tenant puts crates on
      // documents OR crates already exist this week (so the tab stays in sync
      // with ``totalSum``, which counts any existing crates).
      .filter(
        (item) =>
          showCratesOnDocuments || dataCratesCount > 0 || item.key !== "crates",
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- canModify stands for the permission memos built from it
    [
      showCratesOnDocuments,
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
      loading,
      cratesLoading,
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
      <div className="mt-1em">
        <ResellerSelector
          selectedReseller={selectedReseller}
          setSelectedReseller={setSelectedReseller}
          year={selectedYear}
          delivery_week={selectedWeek}
          day_number={selectedDay}
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
          loading={loading}
        />
      )}

      <OrderInfoPanel
        orderState={orderState}
        formattedOrderNumber={formattedOrderNumber}
        totalSum={totalSum}
        fetchData={fetchData}
        handleFinalizeDeliveryNotesSuccess={handleFinalizeDeliveryNotesSuccess}
        handleFinalizeInvoicesSuccess={handleFinalizeInvoicesSuccess}
        handleCreateInvoiceSuccess={handleCreateInvoiceSuccess}
        onOpenDeliveryNoteModal={() => setDeliveryNoteModalVisible(true)}
        onOpenInvoiceModal={() => setInvoiceModalVisible(true)}
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
        visible={deliveryNoteModalVisible}
        onClose={() => {
          setDeliveryNoteModalVisible(false);
          fetchData();
        }}
        deliveryNoteId={orderState.deliveryNoteId}
      />
      <InvoiceModal
        visible={invoiceModalVisible}
        onClose={() => {
          setInvoiceModalVisible(false);
          fetchData();
        }}
        invoiceId={orderState.invoiceId}
      />
    </div>
  );
}
