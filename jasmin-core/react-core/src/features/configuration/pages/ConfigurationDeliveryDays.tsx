import { CheckOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getWeekdayChoices,
  type WeekdayChoice,
} from "@shared/utils/weekdayChoices";
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
  gatedByPermissionOnlyEdit,
  permissionsWithDeletable,
  withNewRowDefaults,
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
  ToolTipIcon,
} from "@shared/ui";
import {
  useActiveStatusColumn,
  useCapability,
  useEarlierStartWindow,
  useWashingCleaningVisibility,
  useInvalidateAfterTableMutation,
  useTenant,
  useTimeBoundColumns,
} from "@hooks/index";
import { getDateRangeStatus, isFieldDisabled, toApiDate } from "@shared/utils";
import {
  missingWorkDays,
  shownWorkDayFields,
} from "@features/commissioning/utils/workDays";

type SharesDeliveryDayRecord = SharesDeliveryDay & TableRecord;
type OrdersDeliveryDayRecord = OrdersDeliveryDay & TableRecord;

// A delivery day's earlier versions are the closed rows of its weekday.
const sameWeekday = (a: SharesDeliveryDayRecord, b: SharesDeliveryDayRecord) =>
  a.day_number === b.day_number;
// A later start would strand what is already on a delivery day in use.
const notInUse = (row: SharesDeliveryDayRecord) => row.can_be_deleted !== false;
// A new delivery day starts with one tour.
const startWithOneTour = withNewRowDefaults({ number_of_tours: 1 });

/** The order delivery days' columns: the weekday, its work days and the
 * ordering deadline. */
function useOrderDayColumns(
  weekdayChoices: WeekdayChoice[],
  renderWeekday: (value: unknown) => string | number,
  isShownColumn: (column: EditableColumnConfig<TableRecord>) => boolean,
): EditableColumnConfig<TableRecord>[] {
  const { t } = useTranslation();
  return useMemo<EditableColumnConfig<TableRecord>[]>(
    () =>
      (
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
                inputType: "time",
                required: false,
                align: "center",
                width: "8em",
                disabled: isFieldDisabled,
              },
            ],
          },
        ] satisfies EditableColumnConfig<TableRecord>[]
      ).filter(isShownColumn),
    [t, weekdayChoices, renderWeekday, isShownColumn],
  );
}

export default function ConfigurationDeliveryDays() {
  const [showAll, setShowAll] = useState(true);

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  // A host that keeps its pickup locations itself brings the share delivery
  // days with their weekday and validity, and puts the stations on its own
  // tours; only the days' work days are set here.
  const offersDeliveryStations = useCapability("delivery_stations");
  // Order days are the resellers' delivery days; a farm that doesn't sell to
  // resellers has none to set.
  const { getSetting } = useTenant();
  const sellsToResellers = Boolean(getSetting("sells_to_resellers", true));
  // A farm that hides washing or cleaning sets no days for them.
  const { showsWashing, showsCleaning } = useWashingCleaningVisibility();
  const isShownColumn = useCallback(
    (column: EditableColumnConfig<TableRecord>) =>
      (showsWashing || column.dataIndex !== "default_washing_day") &&
      (showsCleaning || column.dataIndex !== "default_cleaning_day") &&
      (offersDeliveryStations || column.dataIndex !== "number_of_tours"),
    [showsWashing, showsCleaning, offersDeliveryStations],
  );
  const sharesPermissions = useMemo(
    () =>
      offersDeliveryStations ? permissions : gatedByPermissionOnlyEdit(isOffice),
    [offersDeliveryStations, permissions, isOffice],
  );
  const queryClient = useQueryClient();

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const shareParams = useMemo<CommissioningSharesDeliveryDaysListParams>(
    () => (showAll ? {} : { active_at_date: toApiDate(dayjs())! }),
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

  // A delivery day in use keeps its work days, except while it lacks one and
  // the banner over the commissioning pages names it: a host's sync brings
  // days without them, and they could otherwise never be set. The stored row
  // decides, so the cells don't close while the last one is being picked.
  const incompleteDayIds = useMemo(() => {
    const fields = shownWorkDayFields(showsWashing, showsCleaning);
    return new Set(
      data
        .filter(
          (day) =>
            getDateRangeStatus(day.valid_from, day.valid_until) !== "inactive" &&
            missingWorkDays(day, fields).length > 0,
        )
        .map((day) => String(day.id)),
    );
  }, [data, showsWashing, showsCleaning]);
  const workDayDisabled = useCallback(
    (record: TableRecord) =>
      isFieldDisabled(record) && !incompleteDayIds.has(String(record.id)),
    [incompleteDayIds],
  );

  const validFromEarlierMove = useEarlierStartWindow({
    rows: data,
    sameLineage: sameWeekday,
    laterAllowed: notInUse,
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    overlapGroup: ["day_number"],
    // A new delivery day can only be scheduled going forward — the backend
    // rejects a past valid_from; this aligns the picker with that rule.
    validFromFutureOnly: true,
    // In onboarding mode a saved one may move back into past weeks.
    validFromEarlierMove,
  });

  const { data: rawOrderData, isLoading: ordersLoading } =
    useCommissioningOrdersDeliveryDaysList({
      query: { enabled: sellsToResellers },
    });
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
    onSaveSuccess: trackSharesSave,
    onDeleteSuccess: onSharesDeleteSuccess,
  } = useInvalidateAfterTableMutation(invalidateShares);
  // An update reloads nothing, but whether a day's work days are open goes by
  // its stored row, so the saved one takes its place in the cached list.
  const onSharesSaveSuccess = useCallback(
    (record: TableRecord, action: "create" | "update") => {
      trackSharesSave(record, action);
      if (action !== "update") return;
      const saved = record as unknown as SharesDeliveryDay;
      queryClient.setQueryData<SharesDeliveryDay[]>(
        getCommissioningSharesDeliveryDaysListQueryKey(shareParams),
        (rows) => rows?.map((row) => (row.id === saved.id ? { ...row, ...saved } : row)),
      );
    },
    [trackSharesSave, queryClient, shareParams],
  );
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

  const columnsSharesDeliveryDays = useMemo<
    EditableColumnConfig<TableRecord>[]
  >(
    () =>
      (
        [
          activeStatusColumn,
          {
            title: (
              <div className="checkbox-column-title">
                {t("configuration.in_use")}
              </div>
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
            disabled: offersDeliveryStations ? isFieldDisabled : true,
          },
          offersDeliveryStations
            ? validFromColumn
            : { ...validFromColumn, disabled: true },
          offersDeliveryStations
            ? validUntilColumn
            : { ...validUntilColumn, disabled: true },
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
            disabled: workDayDisabled,
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
            disabled: workDayDisabled,
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
            disabled: workDayDisabled,
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
            disabled: workDayDisabled,
          },
          {
            title: (
              <>
                {t("configuration.number_of_tours")}
                <ToolTipIcon title={t("tooltip.number_of_tours")} />
              </>
            ),
            dataIndex: "number_of_tours",
            key: "number_of_tours",
            inputType: "positive_integer",
            required: true,
            width: "10em",
            align: "center",
          },
        ] satisfies EditableColumnConfig<TableRecord>[]
      ).filter(isShownColumn),
    [
      activeStatusColumn,
      t,
      weekdayChoices,
      renderWeekday,
      validFromColumn,
      validUntilColumn,
      offersDeliveryStations,
      isShownColumn,
      workDayDisabled,
    ],
  );

  const columnsOrderDays = useOrderDayColumns(
    weekdayChoices,
    renderWeekday,
    isShownColumn,
  );

  return (
    <div>
      <h1>{t("configuration.time_management_title")}</h1>
      <h4>{t("configuration.time_management_for_shares")}</h4>
      <div className="mb-1em">
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
        onSaveSuccess={onSharesSaveSuccess}
        onDeleteSuccess={onSharesDeleteSuccess}
        customEdit={startWithOneTour}
        permissions={sharesPermissions}
        className="custom-jasmin-table mb-1em"
      />
      <DateRangeStatusLegend />
      {sellsToResellers && (
        <>
          <h4 className="order-days-heading">
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
            uniqueCheckMessage={t(
              "validation.unique.time_management_order_days",
            )}
            permissions={permissions}
            onSaveSuccess={onOrdersSaveSuccess}
            onDeleteSuccess={onOrdersDeleteSuccess}
          />
        </>
      )}
      <ExplainerText title={t("common.info")}>
        {t("explainers.configuration_time_management")}
      </ExplainerText>
    </div>
  );
}
