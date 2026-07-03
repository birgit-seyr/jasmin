import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningShareDeliveryVariationDeliveryCountsList } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningShareDeliveryVariationDeliveryCountsListParams } from "@shared/api/generated/models";
import { ShareTypeSelector, WeekSelector } from "@shared/selectors";
import { ExplainerText, LabeledSwitch } from "@shared/ui";
import { useShareDeliveryDays } from '@features/commissioning/hooks';

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

type VariationRow = Record<string, unknown> & {
  id?: string;
  share_type_variation_size?: string;
};

interface DeliveryStation {
  id: string;
  short_name?: string;
  number?: string;
}

interface AmountSharesProps {
  jokerMode?: boolean;
}

export default function AmountShares({ jokerMode = false }: AmountSharesProps) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);

  const [selectedShareType, setSelectedShareType] = useState<string | null>(
    null,
  );
  const [showTours, setShowTours] = useState(false);
  const [showDeliveryStations, setShowDeliveryStations] = useState(false);

  const { t } = useTranslation();

  // delivery days — derived purely from the selected year/week (no effect).
  const shareDeliveryDaysFilters = useMemo(
    () => ({
      active_at_date: dayjs()
        .year(selectedYear)
        .isoWeek(selectedWeek ?? currentWeek)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
      get_delivery_stations: true,
      need_info_on_tours: true,
    }),
    [selectedYear, selectedWeek],
  );
  const { shareDeliveryDays, toursExist } = useShareDeliveryDays(
    shareDeliveryDaysFilters,
  );

  const queryParams = useMemo<
    CommissioningShareDeliveryVariationDeliveryCountsListParams | undefined
  >(() => {
    if (!selectedShareType || selectedWeek == null) return undefined;

    const params: CommissioningShareDeliveryVariationDeliveryCountsListParams =
      {
        year: selectedYear,
        delivery_week: selectedWeek,
        share_type: selectedShareType,
        ...(jokerMode && { joker: true }),
      };

    if (showDeliveryStations) {
      params.for_stations = true;
    } else if (showTours) {
      params.for_tours = true;
    }

    return params;
  }, [
    selectedYear,
    selectedWeek,
    selectedShareType,
    showTours,
    showDeliveryStations,
    jokerMode,
  ]);

  const { data } = useCommissioningShareDeliveryVariationDeliveryCountsList(
    queryParams as CommissioningShareDeliveryVariationDeliveryCountsListParams,
    {
      query: {
        enabled: !!queryParams,
      },
    },
  );

  const tableData = useMemo(
    () => (data ? [data as unknown as VariationRow].flat() : []),
    [data],
  );

  const columns = useMemo(() => {
    const baseColumns: ColumnsType<VariationRow> = [
      {
        title: "",
        dataIndex: "share_type_variation_size",
        key: "share_type_variation_size",
        align: "center",
        width: "5em",
        fixed: "left",
      },
    ];

    // Create dynamic columns for each active delivery day
    const deliveryDayColumns: ColumnsType<VariationRow> = shareDeliveryDays.map(
      (deliveryDay) => ({
        title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
        dataIndex: `amount_day_${deliveryDay.id}`,
        key: `amount_day_${deliveryDay.id}`,
        align: "center" as const,
        width: "6em",
        render: (value: number | null) => value || 0,
      }),
    );

    const deliveryDayTourColumns: ColumnsType<VariationRow> =
      shareDeliveryDays.map((deliveryDay) => ({
        title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
        key: `amount_day_${deliveryDay.id}`,
        align: "center" as const,
        children: Array.from(
          // only include the tours that have delivery_stations assigned to them
          { length: deliveryDay.used_tours?.length || 0 },
          (_, tourIndex) => {
            const tourNumber =
              deliveryDay.used_tours?.[tourIndex] || tourIndex + 1;

            return {
              title: `T${tourNumber}`,
              dataIndex: `amount_day_${deliveryDay.id}_tour_${tourNumber}`,
              key: `amount_day_${deliveryDay.id}_tour_${tourNumber}`,
              align: "center" as const,
              width: "6em",
              render: (value: number | null) => value || 0,
            };
          },
        ),
      }));

    const deliveryDayDeliveryStationColumns: ColumnsType<VariationRow> =
      shareDeliveryDays.map((deliveryDay) => ({
        title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
        key: `amount_day_${deliveryDay.id}`,
        align: "center" as const,
        children: Array.from(
          // Use delivery_stations array length, or fallback to 0
          {
            length:
              (
                deliveryDay.delivery_stations as unknown as
                  | DeliveryStation[]
                  | undefined
              )?.length || 0,
          },
          (_, index) => {
            // Get the actual delivery station from the array
            const deliveryStation = (
              deliveryDay.delivery_stations as unknown as DeliveryStation[]
            )?.[index];

            // Use the station's short_name or number for the title
            const stationTitle =
              deliveryStation?.short_name ||
              deliveryStation?.number ||
              `S${index + 1}`;

            return {
              title: stationTitle,
              dataIndex: `amount_day_${deliveryDay.id}_station_${
                deliveryStation?.id || index + 1
              }`,
              key: `amount_day_${deliveryDay.id}_station_${
                deliveryStation?.id || index + 1
              }`,
              align: "center" as const,
              width: "8em",
              render: (value: number | null) => value || 0,
            };
          },
        ),
      }));
    if (showTours) {
      return [...baseColumns, ...deliveryDayTourColumns];
    } else if (showDeliveryStations) {
      return [...baseColumns, ...deliveryDayDeliveryStationColumns];
    } else {
      return [...baseColumns, ...deliveryDayColumns];
    }
  }, [shareDeliveryDays, t, showTours, showDeliveryStations]);

  return (
    <div>
      <h1>
        {jokerMode
          ? t("abos.overview_jokers")
          : t("commissioning.amount_shares")}
      </h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      <ShareTypeSelector
        selectedShareType={selectedShareType}
        setSelectedShareType={setSelectedShareType}
        year={selectedYear}
        delivery_week={selectedWeek}
      />

      {/* Check if there are no active delivery days */}
      {shareDeliveryDays.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "2em",
            backgroundColor: "var(--color-bg-subtle)",
            borderRadius: "8px",
            margin: "2em 0",
          }}
        >
          <h3>{t("commissioning.no_active_delivery_days")}</h3>
          <p>{t("commissioning.no_active_delivery_days_message")}</p>
        </div>
      ) : (
        <>
          {toursExist && (
            <div className="section-divider">
              <LabeledSwitch
                value={showTours}
                onChange={(checked: boolean) => {
                  setShowTours(checked);
                  if (checked) {
                    setShowDeliveryStations(false);
                  }
                }}
                label={t("commissioning.show_tours")}
                withEyeIcons
              />
            </div>
          )}
          <div
            style={{
              marginTop: toursExist ? "0.5em" : "2em",
              marginBottom: "1em",
            }}
          >
            <LabeledSwitch
              value={showDeliveryStations}
              onChange={(checked: boolean) => {
                setShowDeliveryStations(checked);
                if (checked) {
                  setShowTours(false);
                }
              }}
              label={t("commissioning.show_delivery_stations")}
              withEyeIcons
            />
          </div>

          <div style={{ height: "2em" }}></div>
          <Table
            columns={columns}
            dataSource={tableData}
            pagination={false}
            size="small"
            className="custom-forecast-table w-max"
            rowKey="id"
            locale={{
              emptyText: (
                <div style={{ height: "4em" }}>{t("table.no_data")}</div>
              ),
            }}
          />
        </>
      )}
      <ExplainerText title={t("common.info")}>
        {jokerMode
          ? t("explainers.amount_jokers")
          : t("explainers.amount_shares")}
      </ExplainerText>
    </div>
  );
}
