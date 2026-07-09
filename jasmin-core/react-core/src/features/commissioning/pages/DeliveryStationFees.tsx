import { DownloadOutlined } from "@ant-design/icons";
import { Button } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  commissioningDeliveryStationFeesList,
  useCommissioningDeliveryStationFeesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStationFees } from "@shared/api/generated/models";
import ExportCsvDateRangeModal from "@features/commissioning/modals/csv/ExportCsvDateRangeModal";
import { WeekSelector } from "@shared/selectors";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText } from "@shared/ui";
import { buildCsvString, toApiDate } from "@shared/utils";
import { useCurrency } from "@hooks/index";

type FeeRow = DeliveryStationFees & TableRecord;

/** What the solawi owes each fee-carrying delivery station over a period. The
 * on-screen table is driven by a year + week selector ("all weeks" = the whole
 * year); the CSV button still exports an office-chosen date range. */
export default function DeliveryStationFees() {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const [csvModalOpen, setCsvModalOpen] = useState(false);
  const [selectedYear, setSelectedYear] = useState(() => dayjs().year());
  // null week = "all delivery weeks" → the whole year (so the table isn't empty
  // on first load).
  const [selectedWeek, setSelectedWeek] = useState<number | null>(null);

  const feeTypeLabel = useCallback(
    (feeType: string) =>
      t(
        {
          per_box: "commissioning.fee_type_per_box",
          per_month: "commissioning.fee_type_per_month",
          per_year: "commissioning.fee_type_per_year",
          none: "commissioning.fee_type_none",
        }[feeType] ?? "commissioning.fee_type_none",
      ),
    [t],
  );

  // (year, week|null) → the inclusive [start_date, end_date] the fees endpoint
  // wants. A specific week is its Mon–Sun ISO span; "all weeks" is the year.
  const { start_date, end_date } = useMemo(() => {
    if (selectedWeek === null) {
      const base = dayjs().year(selectedYear);
      return {
        start_date: toApiDate(base.startOf("year"))!,
        end_date: toApiDate(base.endOf("year"))!,
      };
    }
    const monday = dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek)
      .startOf("isoWeek");
    return {
      start_date: toApiDate(monday)!,
      end_date: toApiDate(monday.endOf("isoWeek"))!,
    };
  }, [selectedYear, selectedWeek]);

  // This page OWNS the data (passed to the table as ``initialData``), so no
  // ``apiFunctions.list`` — that would double-fetch. ``isFetching`` drives the
  // spinner (staleTime=0 means a revisited key still refetches).
  const { data: rawFees, isFetching } = useCommissioningDeliveryStationFeesList(
    {
      start_date,
      end_date,
    },
  );

  const data = useMemo<FeeRow[]>(
    () =>
      (rawFees ?? []).map((row, index) => {
        // Report rows have no server ``id``; EditableTable overwrites each row's
        // ``key`` with ``item.id`` on sync, so give every row a stable unique
        // ``id`` (station + fee type + index) or all keys collapse to undefined.
        const id = `${row.delivery_station}-${row.fee_type}-${index}`;
        return { ...row, id, key: id };
      }),
    [rawFees],
  );

  const columns = useMemo<EditableColumnConfig<FeeRow>[]>(
    () => [
      {
        title: t("commissioning.delivery_station"),
        dataIndex: "delivery_station_name",
        key: "delivery_station_name",
        render: (value, record) =>
          (value as string | null) ?? record.delivery_station,
      },

      {
        title: t("commissioning.quantity"),
        dataIndex: "quantity",
        key: "quantity",
        align: "right",
        render: (value) => `${value} x`,
      },
      {
        title: t("commissioning.rate_net"),
        dataIndex: "rate_net",
        key: "rate_net",
        align: "right",
        render: (value, record) =>
          `${value} ${currencySymbol} / ${feeTypeLabel(record.fee_type as string)}`,
      },
      {
        title: t("commissioning.total_net"),
        dataIndex: "total_net",
        key: "total_net",
        align: "right",
        render: (value) => `${value} ${currencySymbol}`,
      },
    ],
    [t, feeTypeLabel, currencySymbol],
  );

  const fetchFeesCsv = useCallback(
    async (params: { date_from: string; date_to: string }) => {
      const feeRows = await commissioningDeliveryStationFeesList({
        start_date: params.date_from,
        end_date: params.date_to,
      });
      const headers = [
        t("commissioning.delivery_station"),
        t("commissioning.fee_type"),
        t("commissioning.quantity"),
        t("commissioning.rate_net"),
        t("commissioning.total_net"),
      ];
      const csvRows = (feeRows ?? []).map((row: DeliveryStationFees) => [
        row.delivery_station_name ?? row.delivery_station,
        feeTypeLabel(row.fee_type),
        `${row.quantity} ${row.quantity_unit}`,
        row.rate_net,
        row.total_net,
      ]);
      return buildCsvString(headers, csvRows);
    },
    [feeTypeLabel, t],
  );

  return (
    <div>
      <h1>{t("commissioning.station_fees")}</h1>

      <div style={{ marginBottom: "1em" }}>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
          include_null_option
        />
      </div>

      <EditableTable
        columns={columns}
        initialData={data}
        loading={isFetching}
        permissions={READ_ONLY_PERMISSION}
        pagination={true}
        showSearchBar={true}
        style={{ width: "50%" }}
      />

      <Button
        className="download-button"
        icon={<DownloadOutlined />}
        onClick={() => setCsvModalOpen(true)}
        style={{ marginTop: "1em" }}
      >
        {t("commissioning.download_csv")}
      </Button>

      <ExportCsvDateRangeModal
        open={csvModalOpen}
        onClose={() => setCsvModalOpen(false)}
        title={t("commissioning.station_fees")}
        filenamePrefix="station_fees"
        fetchCsv={fetchFeesCsv}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.station_fees")}
      </ExplainerText>
    </div>
  );
}
