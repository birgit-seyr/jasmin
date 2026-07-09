import { NoVariationColumnsBanner } from "@features/commissioning/components";
import {
  dayAmountKey,
  useBoxCombinationColumns,
  usePlanningAxes,
} from "@features/commissioning/hooks";
import { useShareTypes } from "@hooks/index";
import { useShareTypeVariationSizeOptions } from "@hooks/useShareTypeVariationSizeOptions";
import {
  useCommissioningShareDeliveryBoxCombinationMatrixRetrieve,
  useCommissioningShareDeliveryVariationDeliveryCountsList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
  CommissioningShareDeliveryVariationDeliveryCountsListParams,
  PackingBoxesMatrixColumn,
  WeeklyComboMatrixRow,
} from "@shared/api/generated/models";
import { ShareTypeSelector, WeekSelector } from "@shared/selectors";
import { ExplainerText, LabeledSwitch } from "@shared/ui";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { activeAtDateForWeek } from "@shared/utils";
import { EmptyHint } from "@shared/ui";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

type VariationRow = Record<string, unknown> & {
  id?: string;
  share_type_variation_size?: string;
};

// Box-matrix rows carry dynamic ``combo_<key>`` counts on top of the declared
// fields; the combination columns read those by dataIndex.
type BoxMatrixRow = WeeklyComboMatrixRow & Record<string, unknown>;

interface DeliveryStation {
  id: string;
  short_name?: string;
  number?: string;
}

interface AmountSharesProps {
  jokerMode?: boolean;
}

// The left "which delivery" label for a box-matrix row: the weekday, plus the
// tour or the delivery station when the row is split that way.
function boxRowLabel(row: WeeklyComboMatrixRow, t: TFunction): string {
  const day = t(`commissioning.weekdays.${row.day_number}`);
  if (row.tour != null) return `${day} · T${row.tour}`;
  if (row.delivery_station_name) return `${day} · ${row.delivery_station_name}`;
  return day;
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

  // The normal AmountShares view uses the days × columns box matrix (the
  // ``box_combination_matrix`` endpoint branches server-side: box combinations
  // for subscription tenants, flat per-variation columns for import tenants, so
  // one frontend path covers both). The JOKER view stays on the per-variation
  // size × day layout — jokers are per-variation extras, not box combinations.

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

  // ── Joker view: per-variation (size × day) counts ────────────────────────
  const queryParams = useMemo<
    CommissioningShareDeliveryVariationDeliveryCountsListParams | undefined
  >(() => {
    if (!jokerMode || !selectedShareType || selectedWeek == null) {
      return undefined;
    }

    const params: CommissioningShareDeliveryVariationDeliveryCountsListParams =
      {
        year: selectedYear,
        delivery_week: selectedWeek,
        share_type: selectedShareType,
        joker: true,
      };

    if (showDeliveryStations) {
      params.for_stations = true;
    } else if (showTours) {
      params.for_tours = true;
    }

    return params;
  }, [
    jokerMode,
    selectedYear,
    selectedWeek,
    selectedShareType,
    showTours,
    showDeliveryStations,
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

  // ── Normal view: whole-week matrix (days as rows). The endpoint returns box
  // combinations for subscription tenants and flat per-variation columns for
  // import tenants — both rendered by ``useBoxCombinationColumns``. ──────────
  const boxMatrixParams = useMemo<
    CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams | undefined
  >(() => {
    if (jokerMode || selectedWeek == null) return undefined;
    const params: CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams =
      {
        year: selectedYear,
        delivery_week: selectedWeek,
      };
    if (showDeliveryStations) {
      params.for_stations = true;
    } else if (showTours) {
      params.for_tours = true;
    }
    // Shows EVERYTHING, including bulk-packed variations (no is_packed_bulk
    // filter) — it's the full weekly overview.
    return params;
  }, [jokerMode, selectedYear, selectedWeek, showTours, showDeliveryStations]);

  const { data: boxMatrix, isFetching: boxFetching } =
    useCommissioningShareDeliveryBoxCombinationMatrixRetrieve(
      boxMatrixParams as CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
      { query: { enabled: !!boxMatrixParams } },
    );

  const matrixColumns = useMemo<PackingBoxesMatrixColumn[]>(
    () => boxMatrix?.columns ?? [],
    [boxMatrix],
  );
  const boxRows = useMemo<BoxMatrixRow[]>(
    () => (boxMatrix?.rows ?? []) as BoxMatrixRow[],
    [boxMatrix],
  );
  const comboColumns = useBoxCombinationColumns(matrixColumns);

  const boxColumns = useMemo<ColumnsType<BoxMatrixRow>>(
    () => [
      {
        title: t("commissioning.delivery_day"),
        key: "__day_label",
        align: "left" as const,
        width: "14em",
        fixed: "left" as const,
        render: (_: unknown, row: BoxMatrixRow) => (
          <strong>{boxRowLabel(row, t)}</strong>
        ),
      },
      ...(comboColumns as unknown as ColumnsType<BoxMatrixRow>),
    ],
    [comboColumns, t],
  );

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
      {jokerMode && (
        <ShareTypeSelector
          selectedShareType={selectedShareType}
          setSelectedShareType={setSelectedShareType}
          year={selectedYear}
          delivery_week={selectedWeek}
        />
      )}

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
        {jokerMode ? (
          hasShareTypes ? (
            <Table
              columns={columns}
              dataSource={tableData}
              pagination={false}
              size="small"
              className="custom-jasmin-table w-max"
              rowKey="id"
              locale={{
                emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint>,
              }}
            />
          ) : (
            <NoVariationColumnsBanner />
          )
        ) : (
          <Table
            columns={boxColumns}
            dataSource={boxRows}
            pagination={false}
            size="small"
            loading={boxFetching}
            className="custom-jasmin-table w-max"
            rowKey="id"
            bordered
            locale={{ emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint> }}
          />
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
