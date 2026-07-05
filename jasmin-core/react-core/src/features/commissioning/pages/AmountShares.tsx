import { NoVariationColumnsBanner } from "@features/commissioning/components";
import { dayAmountKey, usePlanningAxes } from "@features/commissioning/hooks";
import { useShareTypes } from "@hooks/index";
import { useShareTypeVariationSizeOptions } from "@hooks/useShareTypeVariationSizeOptions";
import { useCommissioningShareDeliveryVariationDeliveryCountsList } from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningShareDeliveryVariationDeliveryCountsListParams } from "@shared/api/generated/models";
import { ShareTypeSelector, WeekSelector } from "@shared/selectors";
import { ExplainerText, LabeledSwitch } from "@shared/ui";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { activeAtDateForWeek } from "@shared/utils";

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
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  // Day axis via the shared planning-axes hook (single source of truth — see
  // docs/day-variation-columns-audit.md). No shareOption is passed, so the
  // variation query stays gated off; this page derives its own variation rows
  // from the delivery-counts endpoint and only needs the day columns here.
  const { shareDeliveryDays, toursExist } = usePlanningAxes({
    year: selectedYear,
    week: selectedWeek ?? currentWeek,
    requireStations: true,
    needTours: true,
  });

  const shareTypeParams = useMemo(
    () => ({
      active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
    }),
    [selectedYear, selectedWeek],
  );
  const { shareTypes } = useShareTypes(shareTypeParams);
  const hasShareTypes = shareTypes.length > 0;

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
        render: (value) => getShareTypeVariationSizeLabel(value),
      },
    ];

    // Create dynamic columns for each active delivery day
    const deliveryDayColumns: ColumnsType<VariationRow> = shareDeliveryDays.map(
      (deliveryDay) => ({
        title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
        dataIndex: dayAmountKey({ dayId: deliveryDay.id! }),
        key: dayAmountKey({ dayId: deliveryDay.id! }),
        align: "center" as const,
        width: "6em",
        render: (value: number | null) => value || 0,
      }),
    );

    const deliveryDayTourColumns: ColumnsType<VariationRow> =
      shareDeliveryDays.map((deliveryDay) => ({
        title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
        key: dayAmountKey({ dayId: deliveryDay.id! }),
        align: "center" as const,
        children: Array.from(
          // only include the tours that have delivery_stations assigned to them
          { length: deliveryDay.used_tours?.length || 0 },
          (_, tourIndex) => {
            const tourNumber =
              deliveryDay.used_tours?.[tourIndex] || tourIndex + 1;
            const tourKey = dayAmountKey({
              dayId: deliveryDay.id!,
              tour: tourNumber,
            });

            return {
              title: `T${tourNumber}`,
              dataIndex: tourKey,
              key: tourKey,
              align: "center" as const,
              width: "6em",
              render: (value: number | null) => value || 0,
            };
          },
        ),
      }));

    const deliveryDayDeliveryStationColumns: ColumnsType<VariationRow> =
      shareDeliveryDays.map((deliveryDay) => {
        const stations =
          (deliveryDay.delivery_stations as unknown as
            | DeliveryStation[]
            | undefined) ?? [];
        return {
          title: t(`commissioning.weekdays.${deliveryDay.day_number}`),
          key: dayAmountKey({ dayId: deliveryDay.id! }),
          align: "center" as const,
          // Map the delivery_stations array DIRECTLY so each column keys off the
          // station's real id. The backend emits
          // `amount_day_<dayId>_station_<stationId>`; the old code built the key
          // from a positional `index + 1` when the id was missing, which can
          // never match that (a station id is a UUID) — see
          // docs/day-variation-columns-audit.md (Phase 4).
          children: stations.map((station, index) => {
            const stationKey = dayAmountKey({
              dayId: deliveryDay.id!,
              station: station.id,
            });
            return {
              title: station.short_name || station.number || `S${index + 1}`,
              dataIndex: stationKey,
              key: stationKey,
              align: "center" as const,
              width: "8em",
              render: (value: number | null) => value || 0,
            };
          }),
        };
      });
    if (showTours) {
      return [...baseColumns, ...deliveryDayTourColumns];
    } else if (showDeliveryStations) {
      return [...baseColumns, ...deliveryDayDeliveryStationColumns];
    } else {
      return [...baseColumns, ...deliveryDayColumns];
    }
  }, [
    shareDeliveryDays,
    t,
    showTours,
    showDeliveryStations,
    getShareTypeVariationSizeLabel,
  ]);

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
        {hasShareTypes && (
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
        )}

        <div style={{ height: "2em" }}></div>
        {hasShareTypes ? (
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
        ) : (
          <NoVariationColumnsBanner />
        )}
      </>

      <ExplainerText title={t("common.info")}>
        {jokerMode
          ? t("explainers.amount_jokers")
          : t("explainers.amount_shares")}
      </ExplainerText>
    </div>
  );
}
