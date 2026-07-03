import { CheckOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { getWeekdayChoices } from "@shared/utils/weekdayChoices";
import {
  commissioningOrdersDeliveryDaysCreate,
  commissioningOrdersDeliveryDaysDestroy,
  commissioningOrdersDeliveryDaysPartialUpdate,
  commissioningSharesDeliveryDaysCreate,
  commissioningSharesDeliveryDaysDestroy,
  commissioningSharesDeliveryDaysPartialUpdate,
  getCommissioningOrdersDeliveryDaysListQueryKey,
  getCommissioningSharesDeliveryDaysListQueryKey,
  useCommissioningOrdersDeliveryDaysList,
  useCommissioningSharesDeliveryDaysList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningSharesDeliveryDaysListParams,
  OrdersDeliveryDay,
  SharesDeliveryDay,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
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
import {
  DateRangeStatusLegend,
  ExplainerText,
  LabeledSwitch,
} from "@shared/ui";
import {
  useActiveStatusColumn,
  useInvalidateAfterTableMutation,
  useTimeBoundColumns,
} from "@hooks/index";
import { isFieldDisabled } from "@shared/utils";

type SharesDeliveryDayRecord = SharesDeliveryDay & TableRecord;
type OrdersDeliveryDayRecord = OrdersDeliveryDay & TableRecord;

export default function TimeManagement() {
  const [showAll, setShowAll] = useState(true);

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const queryClient = useQueryClient();

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns();

  const shareParams = useMemo<CommissioningSharesDeliveryDaysListParams>(
    () => (showAll ? {} : { active_at_date: dayjs().format("YYYY-MM-DD") }),
    [showAll],
  );

  // ``isFetching`` (not ``isLoading``): the filter toggle changes the query
  // key, and with the global ``staleTime: 0`` a revisited key is cached
  // (``isLoading === false``) — so only ``isFetching`` shows the refresh
  // spinner while the background refetch runs.
  const { data: rawShareData, isFetching: sharesLoading } =
    useCommissioningSharesDeliveryDaysList(shareParams);
  // Directional cast at the orval boundary: rows gain the table-only
  // ``key`` field.
  const data = useMemo(
    () => (rawShareData ?? []) as SharesDeliveryDayRecord[],
    [rawShareData],
  );

  const { data: rawOrderData, isLoading: ordersLoading } =
    useCommissioningOrdersDeliveryDaysList();
  const dataOrders = useMemo(
    () => (rawOrderData ?? []) as OrdersDeliveryDayRecord[],
    [rawOrderData],
  );

  const sharesApiFunctions: ApiFunctions = useMemo(
    () =>
      wrapApiFunctions<SharesDeliveryDayRecord>({
        create: (data) => commissioningSharesDeliveryDaysCreate(data),
        update: (id, data) =>
          commissioningSharesDeliveryDaysPartialUpdate(id, data),
        delete: (id) => commissioningSharesDeliveryDaysDestroy(id),
      }),
    [],
  );

  const ordersApiFunctions: ApiFunctions = useMemo(
    () =>
      wrapApiFunctions<OrdersDeliveryDayRecord>({
        create: (data) => commissioningOrdersDeliveryDaysCreate(data),
        update: (id, data) =>
          commissioningOrdersDeliveryDaysPartialUpdate(id, data),
        delete: (id) => commissioningOrdersDeliveryDaysDestroy(id),
      }),
    [],
  );

  const invalidateShares = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningSharesDeliveryDaysListQueryKey(),
    });
  }, [queryClient]);
  const invalidateOrders = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOrdersDeliveryDaysListQueryKey(),
    });
  }, [queryClient]);
  const {
    onSaveSuccess: onSharesSaveSuccess,
    onDeleteSuccess: onSharesDeleteSuccess,
  } = useInvalidateAfterTableMutation(invalidateShares);
  const {
    onSaveSuccess: onOrdersSaveSuccess,
    onDeleteSuccess: onOrdersDeleteSuccess,
  } = useInvalidateAfterTableMutation(invalidateOrders);

  const weekdayChoices = useMemo(() => getWeekdayChoices(t), [t]);

  const renderWeekday = useCallback(
    (value: unknown) => {
      if (typeof value !== "number") return "-";
      const day = weekdayChoices.find((d) => d.value === value);
      return day ? day.label : value;
    },
    [weekdayChoices],
  );

  const columnsSharesDeliveryDays = useMemo<EditableColumnConfig<TableRecord>[]>(
    () =>
      [
        activeStatusColumn,
    {
      title: (
        <div className="checkbox-column-title">{t("configuration.in_use")}</div>
      ),
      dataIndex: "can_be_deleted",
      key: "can_be_deleted",
      required: false,
      align: "center",
      disabled: true,
      width: "4em",
      readOnly: true,
      render: (_: unknown, record: TableRecord) => {
        return record.can_be_deleted === false ? (
          <CheckOutlined className="icon-check-success" />
        ) : null;
      },
    },
    {
      title: t("configuration.delivery_day"),
      dataIndex: "day_number",
      key: "day_number",
      inputType: "select",
      required: true,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      sortable: true,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    validFromColumn,
    validUntilColumn,
    {
      title: t("configuration.default_get_current_stock_day"),
      dataIndex: "default_get_current_stock_day",
      key: "default_get_current_stock_day",
      inputType: "select",
      required: false,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      render: (value: unknown) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        return day ? day.label : value;
      },
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_washing_day"),
      dataIndex: "default_washing_day",
      key: "default_washing_day",
      inputType: "select",
      required: true,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_cleaning_day"),
      dataIndex: "default_cleaning_day",
      key: "default_cleaning_day",
      inputType: "select",
      required: true,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_harvesting_day"),
      dataIndex: "default_harvesting_day",
      key: "default_harvesting_day",
      inputType: "select",
      required: true,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_packing_day"),
      dataIndex: "default_packing_day",
      key: "default_packing_day",
      inputType: "select",
      required: true,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.number_of_tours"),
      dataIndex: "number_of_tours",
      key: "number_of_tours",
      inputType: "positive_integer",
      required: false,
      width: "10em",
      align: "center",
    },
      ] as EditableColumnConfig<TableRecord>[],
    [
      activeStatusColumn,
      t,
      weekdayChoices,
      renderWeekday,
      validFromColumn,
      validUntilColumn,
    ],
  );

  const columnsOrderDays = useMemo<EditableColumnConfig<TableRecord>[]>(
    () =>
      [
        {
          title: t("configuration.delivery_day"),
      dataIndex: "day_number",
      key: "day_number",
      inputType: "select",
      required: true,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },

    {
      title: t("configuration.default_get_current_stock_day"),
      dataIndex: "default_get_current_stock_day",
      key: "default_get_current_stock_day",
      inputType: "select",
      required: false,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      render: (value: unknown) => {
        if (typeof value !== "number") return "-";
        const day = weekdayChoices.find((d) => d.value === value);
        return day ? day.label : value;
      },
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_washing_day"),
      dataIndex: "default_washing_day",
      key: "default_washing_day",
      inputType: "select",
      required: false,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_cleaning_day"),
      dataIndex: "default_cleaning_day",
      key: "default_cleaning_day",
      inputType: "select",
      required: false,
      align: "center",
      width: "8em",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_harvesting_day"),
      dataIndex: "default_harvesting_day",
      key: "default_harvesting_day",
      inputType: "select",
      required: false,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_packing_day"),
      dataIndex: "default_packing_day",
      key: "default_packing_day",
      inputType: "select",
      required: false,
      width: "8em",
      align: "center",
      options: weekdayChoices,
      render: renderWeekday,
      disabled: isFieldDisabled,
    },
    {
      title: t("configuration.default_last_possible_ordering_day"),
      key: "ordering_day",
      dataIndex: "ordering_day",
      align: "center",
      width: "16em",
      children: [
        {
          title: t("configuration.day"),
          dataIndex: "default_last_possible_ordering_day",
          key: "default_last_possible_ordering_day",
          inputType: "select",
          required: false,
          align: "center",
          width: "8em",
          options: weekdayChoices,
          render: renderWeekday,
          disabled: isFieldDisabled,
        },
        {
          title: t("configuration.time"),
          dataIndex: "default_last_possible_ordering_time",
          key: "default_last_possible_ordering_time",
          inputType: "text",
          required: false,
          align: "center",
          width: "8em",
          disabled: isFieldDisabled,
        },
      ],
    },
      ] as EditableColumnConfig<TableRecord>[],
    [t, weekdayChoices, renderWeekday],
  );

  return (
    <div>
      <h1>{t("configuration.time_management_title")}</h1>
      <h4>{t("configuration.time_management_for_shares")}</h4>
      <div style={{ marginBottom: "1em" }}>
        <LabeledSwitch
          value={!showAll}
          onChange={(checked: boolean) => setShowAll(!checked)}
          label={t("configuration.show_only_active_days")}
          size="small"
        />
      </div>

      <EditableTable
        key={1}
        columns={columnsSharesDeliveryDays}
        apiFunctions={sharesApiFunctions}
        focusIndex="day_number"
        initialData={data}
        loading={sharesLoading}
        uniqueCheck={["day_number", "valid_from"]}
        uniqueCheckMessage={t("validation.unique.time_management")}
        onSaveSuccess={onSharesSaveSuccess}
        onDeleteSuccess={onSharesDeleteSuccess}
        permissions={permissions}
        className="custom-forecast-table mb-1em"
      />
      <DateRangeStatusLegend />
      <h4 style={{ marginTop: "3em" }}>
        {t("configuration.time_manamagent_for_orders")}
      </h4>

      <EditableTable
        key={2}
        columns={columnsOrderDays}
        apiFunctions={ordersApiFunctions}
        focusIndex="day_number"
        initialData={dataOrders}
        loading={ordersLoading}
        uniqueCheck={["day_number"]}
        uniqueCheckMessage={t("validation.unique.time_management_order_days")}
        permissions={permissions}
        onSaveSuccess={onOrdersSaveSuccess}
        onDeleteSuccess={onOrdersDeleteSuccess}
      />
      <DateRangeStatusLegend />
      <ExplainerText title={t("common.info")} style={{ marginTop: "2em" }}>
        {t("explainers.configuration_time_management")}
      </ExplainerText>
    </div>
  );
}
