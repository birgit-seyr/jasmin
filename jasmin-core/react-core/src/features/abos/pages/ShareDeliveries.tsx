import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningShareDeliveryOverviewCreate,
  commissioningShareDeliveryOverviewDestroy,
  commissioningShareDeliveryOverviewPartialUpdate,
  getCommissioningShareDeliveryOverviewListQueryKey,
  useCommissioningShareDeliveryOverviewList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareDeliveryOverviewListParams,
  ShareDeliveryOverview,
} from "@shared/api/generated/models";
import { MemberSelector, WeekSelector } from "@shared/selectors";
import { DeliveryStationSelector } from "@features/commissioning/selectors";
import {
  EditableTable,
  gatedByPermissionOnlyEdit,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, ToolTipIcon } from "@shared/ui";
import { useRoles } from "@shared/auth";
import {
  useDateFormat,
  useDeliveryStationDays,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useTableRowSelection,
  useTenant,
} from "@hooks/index";
import type { ShareDeliveryRecord } from "./types";

export default function ShareDeliveries() {
  const [selectedMember, setSelectedMember] = useState<string | null>(null);
  // ``null`` / ``"none"`` = "all stations" (the selector's null option).
  const [selectedDeliveryStation, setSelectedDeliveryStation] = useState<
    string | null
  >(null);
  const [selectedYear, setSelectedYear] = useState(dayjs().year());
  // ``null`` = "all weeks" (the WeekSelector null option). When set, rows are
  // filtered client-side — the overview list endpoint only filters by
  // year + member, not week.
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermissionOnlyEdit(isOffice),
      canEditRecord: (record: ShareDeliveryRecord) =>
        !!record.delivery_date &&
        dayjs(record.delivery_date).isAfter(dayjs(), "day"),
    }),
    [isOffice],
  );
  const queryClient = useQueryClient();
  const { getSetting } = useTenant();

  const uses_jokers = getSetting("uses_jokers", true);

  const { formatDate } = useDateFormat();
  const { noteColumn } = useNoteColumn({ disabled: true });

  // row selection state and handler:
  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection(
    (record: ShareDeliveryRecord) =>
      Boolean(
        record.key === -1 ||
          (record.delivery_date &&
            dayjs(record.delivery_date).isSameOrBefore(dayjs(), "day")),
      ),
  );

  // Capacity is shown per row as ``(occupied/capacity)`` for the row's week,
  // keyed ``${selectedYear}-${week}``. Fetch the capacity window for the whole
  // selected year (week 1 + 52 weeks) so every row's key resolves — otherwise
  // the default current-week window misses past/other weeks and shows nothing.
  const deliveryStationDayParams = useMemo(
    () => ({ year: selectedYear, delivery_week: 1, num_weeks: 52 }),
    [selectedYear],
  );
  const { deliveryStationDays } = useDeliveryStationDays(
    deliveryStationDayParams,
  );

  const customEdit = useCallback(
    (
      record: ShareDeliveryRecord,
      form: { setFieldsValue: (v: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = {
          is_trial: false,
          quantity: 1,
        };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    return transformedData;
  }, []);

  const listParams = useMemo<CommissioningShareDeliveryOverviewListParams>(
    () => ({
      year: selectedYear,
      ...(selectedMember ? { member: selectedMember } : {}),
      // The selector's "all stations" option yields ``"none"``/null — only send
      // the (backend-filtered) param for a real station.
      ...(selectedDeliveryStation && selectedDeliveryStation !== "none"
        ? { delivery_station: selectedDeliveryStation }
        : {}),
    }),
    [selectedYear, selectedMember, selectedDeliveryStation],
  );

  // Enabled on year alone — no member required. With no member selected the
  // backend returns every member's deliveries for the year; the week selector
  // (incl. "all weeks") then narrows client-side.
  // ``isFetching`` (not ``isLoading``): year/member changes the query key, and
  // with the global ``staleTime: 0`` a revisited (cached) year would have
  // ``isLoading === false`` → no spinner. ``isFetching`` shows the overlay on
  // every filter change so the office sees the table refresh.
  const { data: rawData, isFetching } =
    useCommissioningShareDeliveryOverviewList(listParams, {
      query: { enabled: !!selectedYear },
    });

  const data = useMemo(() => {
    // Single directional cast at the generated-client boundary: the overview
    // rows flow into the table as ``ShareDeliveryRecord`` (the ``key`` field
    // is injected by EditableTable itself).
    const all = (rawData ?? []) as unknown as ShareDeliveryRecord[];
    if (selectedWeek == null) return all;
    return all.filter((row) => row.delivery_week === selectedWeek);
  }, [rawData, selectedWeek]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareDeliveryOverviewListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  // No ``list`` here on purpose: this page owns the data via the
  // ``useCommissioningShareDeliveryOverviewList`` query above and passes it as
  // ``initialData``. Supplying ``list`` would make EditableTable ALSO fetch
  // (it auto-fetches when ``showSearchBar`` + ``apiFunctions.list`` are both
  // set), double-fetching and racing two loading states. Search still works
  // (it filters the loaded rows client-side); create/update/delete below
  // drive mutations, and ``onSaveSuccess``/``onDeleteSuccess`` invalidate the
  // query to refresh.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ShareDeliveryOverview & TableRecord>({
        create: (data) => commissioningShareDeliveryOverviewCreate(data),
        update: (id, data) =>
          commissioningShareDeliveryOverviewPartialUpdate(id, data),
        delete: (id) => commissioningShareDeliveryOverviewDestroy(id),
      }),
    [],
  );

  const columns: EditableColumnConfig<ShareDeliveryRecord>[] = useMemo(
    () => [
      {
        title: t("commissioning.KW"),
        dataIndex: "delivery_week",
        key: "delivery_week",
        inputType: "kw",
        width: "5em",
        disabled: true,
        align: "center",
        sortable: true,
        render: (value: unknown) => <strong>{value as number}</strong>,
      },
      {
        title: (
          <>
            {t("members.delivery_station")}{" "}
            <ToolTipIcon title={t("tooltip.delivery_station_day")} />
          </>
        ),
        dataIndex: "delivery_station_day_string",
        key: "delivery_station_day_string",
        inputType: "select",
        required: true,
        align: "left",
        width: "16em",
        options: (record: ShareDeliveryRecord) => {
          const week = record.delivery_week;
          const year = selectedYear;
          if (!week) return deliveryStationDays;
          const weekStart = dayjs().year(year).isoWeek(week).startOf("isoWeek");
          const weekEnd = weekStart.endOf("isoWeek");
          const weekKey = `${year}-${week}`;
          return deliveryStationDays
            .filter((dsd) => {
              const from = dayjs(dsd.valid_from);
              const until = dsd.valid_until ? dayjs(dsd.valid_until) : null;
              return (
                from.isSameOrBefore(weekEnd, "day") &&
                (!until || until.isSameOrAfter(weekStart, "day"))
              );
            })
            .map((dsd) => {
              const cap = dsd.capacity_by_week?.[weekKey];
              const capacityLabel =
                cap && dsd.capacity != null
                  ? ` (${cap.occupied}/${dsd.capacity})`
                  : "";
              // Grey out (disable) a full station-day for this week, but keep
              // the row's currently-assigned one selectable so an edit isn't
              // blocked. ``free === null`` = no capacity limit → always free.
              const isFull = cap != null && cap.free !== null && cap.free <= 0;
              const isCurrent = dsd.value === record.delivery_station_day;
              return {
                ...dsd,
                label: `${dsd.label}${capacityLabel}`,
                disabled: isFull && !isCurrent,
              };
            });
        },
        foreignKey: {
          valueField: "delivery_station_day",
          displayField: "delivery_station_day_string",
        },
      },
      {
        title: t("members.delivery_date"),
        dataIndex: "delivery_date",
        key: "delivery_date",
        disabled: true,
        readOnly: true,
        align: "center",
        width: "10em",
        sortable: true,
        render: (value: unknown) => formatDate(value as string),
      },
      ...(uses_jokers
        ? ([
            {
              title: t("abos.joker_taken"),
              dataIndex: "joker_taken",
              key: "joker_taken",
              inputType: "checkbox",
              align: "center",
              required: false,
              disabled: !uses_jokers,
              sortable: true,
            },
          ] as EditableColumnConfig<ShareDeliveryRecord>[])
        : []),
      {
        title: <>{t("members.share_type_variation")}</>,
        dataIndex: "share_type_variation_string",
        key: "share_type_variation_string",
        inputType: "select",
        disabled: true,
        readOnly: true,
        fixed: true,
        align: "left",
        width: "16em",
        sortable: true,
      },
      {
        title: <>{t("members.quantity")}</>,
        dataIndex: "quantity",
        key: "quantity",
        inputType: "positive_integer",
        required: false,
        disabled: true,
        readOnly: true,
        align: "center",
        width: "5em",
      },
      {
        title: "",
        dataIndex: "delivery_station_day_id",
        key: "delivery_station_day_id",
        disabled: true,
        readOnly: true,
        align: "center",
        width: "10em",
        render: (_value: unknown, record: ShareDeliveryRecord) => (
          <span className="text-xs">{record.delivery_station_day}</span>
        ),
      },
      noteColumn,
    ],
    [t, deliveryStationDays, uses_jokers, formatDate, selectedYear, noteColumn],
  );

  const rowClassName = useCallback((record: ShareDeliveryRecord) => {
    return record.joker_taken ? "joker-taken-row" : "";
  }, []);

  return (
    <div>
      <h1>{t("abos.share_deliveries")}</h1>
      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
        include_null_option
      />
      <MemberSelector
        selectedMember={selectedMember}
        setSelectedMember={setSelectedMember}
      />
      <DeliveryStationSelector
        selectedDeliveryStation={selectedDeliveryStation}
        setSelectedDeliveryStation={setSelectedDeliveryStation}
        include_null_option
        allStations
      />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="delivery_week"
        initialData={data}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        rowClassName={rowClassName}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.share_deliveries_overview")}
      </ExplainerText>
    </div>
  );
}
