import {
  useBoxCombinationColumns,
  usePlanningAxes,
} from "@features/commissioning/hooks";
import { currentWeek, useTenant, useYearWeekState } from "@hooks/index";
import { useCommissioningShareDeliveryBoxCombinationMatrixRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
  PackingBoxesMatrixColumn,
  WeeklyComboMatrixRow,
} from "@shared/api/generated/models";
import { WeekSelector } from "@shared/selectors";
import { EmptyHint, ExplainerText, LabeledSwitch } from "@shared/ui";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

// Box-matrix rows carry dynamic ``combo_<key>`` counts on top of the declared
// fields; the combination columns read those by dataIndex.
type BoxMatrixRow = WeeklyComboMatrixRow & Record<string, unknown>;

// The left "which delivery" label for a box-matrix row: the weekday, plus the
// tour or the delivery station when the row is split that way.
function boxRowLabel(row: WeeklyComboMatrixRow, t: TFunction): string {
  const day = t(`commissioning.weekdays.${row.day_number}`);
  if (row.tour != null) return `${day} · T${row.tour}`;
  if (row.delivery_station_name) return `${day} · ${row.delivery_station_name}`;
  return day;
}

// The full box-matrix column set: a fixed weekday/label column plus the dynamic
// box-combination columns. Shared by the joker and donation-joker tables so both
// render identically.
function makeBoxColumns(
  comboColumns: ReturnType<typeof useBoxCombinationColumns>,
  t: TFunction,
): ColumnsType<BoxMatrixRow> {
  return [
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
  ];
}

/**
 * Jokers overview: two whole-week box matrices for the selected week — the
 * boxes SKIPPED via a taken joker, and the boxes DONATED via a donation joker.
 * Both are ALWAYS shown (an empty week just renders its "no data" state); they
 * reuse the SAME ``box_combination_matrix`` endpoint (``joker`` /
 * ``donation_joker`` flag), the box-combination columns, week selector and
 * tour/station switches — so one week selector drives both tables.
 */
export default function Jokers() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const usesJokers = getSetting("uses_jokers", true);

  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();

  const [showTours, setShowTours] = useState(false);
  const [showDeliveryStations, setShowDeliveryStations] = useState(false);

  // Only needed to decide whether the "show tours" switch is meaningful.
  const { toursExist } = usePlanningAxes({
    year: selectedYear,
    week: selectedWeek ?? currentWeek,
    requireStations: true,
    needTours: true,
  });

  const buildParams = useMemo(
    () =>
      (
        donationJoker: boolean,
      ): CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams | undefined => {
        if (selectedWeek == null || !usesJokers) return undefined;
        const params: CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams =
          {
            year: selectedYear,
            delivery_week: selectedWeek,
          };
        if (donationJoker) {
          params.donation_joker = true;
        } else {
          params.joker = true;
        }
        if (showDeliveryStations) {
          params.for_stations = true;
        } else if (showTours) {
          params.for_tours = true;
        }
        // Shows EVERYTHING, including bulk-packed variations (no is_packed_bulk
        // filter) — it's the full weekly overview.
        return params;
      },
    [usesJokers, selectedYear, selectedWeek, showTours, showDeliveryStations],
  );

  const jokerParams = useMemo(() => buildParams(false), [buildParams]);
  const donationParams = useMemo(() => buildParams(true), [buildParams]);

  const { data: jokerMatrix, isFetching: jokerFetching } =
    useCommissioningShareDeliveryBoxCombinationMatrixRetrieve(
      jokerParams as CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
      { query: { enabled: !!jokerParams } },
    );
  const { data: donationMatrix, isFetching: donationFetching } =
    useCommissioningShareDeliveryBoxCombinationMatrixRetrieve(
      donationParams as CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
      { query: { enabled: !!donationParams } },
    );

  const jokerMatrixColumns = useMemo<PackingBoxesMatrixColumn[]>(
    () => jokerMatrix?.columns ?? [],
    [jokerMatrix],
  );
  const jokerRows = useMemo<BoxMatrixRow[]>(
    () => (jokerMatrix?.rows ?? []) as BoxMatrixRow[],
    [jokerMatrix],
  );
  const jokerComboColumns = useBoxCombinationColumns(jokerMatrixColumns);
  const jokerColumns = useMemo(
    () => makeBoxColumns(jokerComboColumns, t),
    [jokerComboColumns, t],
  );

  const donationMatrixColumns = useMemo<PackingBoxesMatrixColumn[]>(
    () => donationMatrix?.columns ?? [],
    [donationMatrix],
  );
  const donationRows = useMemo<BoxMatrixRow[]>(
    () => (donationMatrix?.rows ?? []) as BoxMatrixRow[],
    [donationMatrix],
  );
  const donationComboColumns = useBoxCombinationColumns(donationMatrixColumns);
  const donationColumns = useMemo(
    () => makeBoxColumns(donationComboColumns, t),
    [donationComboColumns, t],
  );

  const boxTable = (
    columns: ColumnsType<BoxMatrixRow>,
    rows: BoxMatrixRow[],
    loading: boolean,
  ) => (
    <Table
      columns={columns}
      dataSource={rows}
      pagination={false}
      size="small"
      loading={loading}
      className="custom-jasmin-table w-max"
      rowKey="id"
      bordered
      locale={{ emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint> }}
    />
  );

  // Direct URL or stale bookmark — bounce off the page when the tenant has
  // disabled jokers. Sidebar entry is hidden in the same condition by
  // ``AboSidebar``. All hooks above run first (rules of hooks); the joker
  // queries are additionally gated off via ``enabled`` when jokers are off.
  if (!usesJokers) {
    return <Navigate to="/abos/dashboard" replace />;
  }

  return (
    <div>
      <h1>{t("abos.overview_jokers")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />

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
      {/* Both tables are always shown; an empty one renders "no data". */}
      <h2>{t("abos.jokers")}</h2>
      {boxTable(jokerColumns, jokerRows, jokerFetching)}

      <h2 style={{ marginTop: "2em" }}>{t("abos.donation_jokers")}</h2>
      {boxTable(donationColumns, donationRows, donationFetching)}

      <ExplainerText title={t("common.info")}>
        {t("explainers.amount_jokers")}
      </ExplainerText>
    </div>
  );
}
