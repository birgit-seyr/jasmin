import {
  useBoxCombinationColumns,
  usePlanningAxes,
} from "@features/commissioning/hooks";
import { currentWeek, useYearWeekState } from "@hooks/index";
import { useCommissioningShareDeliveryBoxCombinationMatrixRetrieve } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams,
  PackingBoxesMatrixColumn,
  WeeklyComboMatrixRow,
} from "@shared/api/generated/models";
import { WeekSelector } from "@shared/selectors";
import {
  EmptyHint,
  ExplainerText,
  LabeledSwitch,
  PastWarningMessage,
} from "@shared/ui";
import { Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

// Box-matrix rows carry dynamic ``combo_<key>`` counts on top of the declared
// fields; the combination columns read those by dataIndex.
type BoxMatrixRow = WeeklyComboMatrixRow & Record<string, unknown>;

interface AmountShareTypeVariationsProps {
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

export default function AmountShareTypeVariations({
  jokerMode = false,
}: AmountShareTypeVariationsProps) {
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();

  const [showTours, setShowTours] = useState(false);
  const [showDeliveryStations, setShowDeliveryStations] = useState(false);

  const { t } = useTranslation();

  // Both the shipping and the joker view render the SAME whole-week box matrix
  // (``box_combination_matrix`` branches server-side: box combinations for
  // subscription tenants, flat per-variation columns for import tenants). The
  // joker view just adds ``joker: true`` so the backend counts the boxes skipped
  // via a taken joker instead of the shipping ones — same columns, same layout.

  // Only needed to decide whether the "show tours" switch is meaningful.
  const { toursExist } = usePlanningAxes({
    year: selectedYear,
    week: selectedWeek ?? currentWeek,
    requireStations: true,
    needTours: true,
  });

  const boxMatrixParams = useMemo<
    CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams | undefined
  >(() => {
    if (selectedWeek == null) return undefined;
    const params: CommissioningShareDeliveryBoxCombinationMatrixRetrieveParams =
      {
        year: selectedYear,
        delivery_week: selectedWeek,
      };
    if (jokerMode) params.joker = true;
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

  // No box combinations this week (e.g. a past / empty week): surface the
  // read-only warning instead of an empty grid, and hide the grouping switches.
  const noColumns =
    selectedWeek != null && !boxFetching && matrixColumns.length === 0;

  return (
    <div>
      <h1>
        {jokerMode
          ? t("abos.overview_jokers")
          : t("commissioning.amount_share_type_variations")}
      </h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />

      {noColumns ? (
        <PastWarningMessage>
          {t("commissioning.packing_list_no_columns")}
        </PastWarningMessage>
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
        </>
      )}

      <ExplainerText title={t("common.info")}>
        {jokerMode
          ? t("explainers.amount_jokers")
          : t("explainers.amount_share_type_variations")}
      </ExplainerText>
    </div>
  );
}
