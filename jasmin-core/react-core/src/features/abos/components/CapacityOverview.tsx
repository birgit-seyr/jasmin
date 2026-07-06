/**
 * Office capacity control panel — "what does the program think is full right
 * now, for this period?".
 *
 * Pick a date range; for every share-type variation (farm-wide production cap)
 * and every delivery-station-day (weekly logistics cap) it shows the busiest
 * ("peak") ISO week's occupancy across that range, the capacity, the free
 * slots and which week is tightest. It reads the EXACT same per-week
 * ``capacity_by_week`` + ``termCapacity`` evaluator the new-subscription modal
 * and the Abos select use, so this panel is the visual single-source-of-truth:
 * if it says "full", a save for an overlapping term waiting_lists — and vice versa.
 *
 * The capacity window is fetched wide + fixed by the parent (this year + next);
 * the range picker only chooses WHICH weeks to evaluate, so changing it never
 * refetches.
 */

import { Collapse, DatePicker, Tag } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DeliveryStationDayOption } from "@hooks/useDeliveryStationDays";
import type { ShareTypeVariationOption } from "@hooks/useAllShareTypeVariations";
import { useDateFormat, useDateRangePresets } from "@hooks/index";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  formatWeekKey,
  termCapacity,
  termWeekKeys,
} from "@features/abos/utils/stationCapacity";

interface CapacityOverviewProps {
  variations: ShareTypeVariationOption[];
  stationDays: DeliveryStationDayOption[];
}

interface CapacityRow extends TableRecord {
  key: string;
  id: string;
  name: string;
  capacity: number | null;
  peak_occupied: number;
  free: number | null;
  peak_week: string | null;
  status: "full" | "tight" | "ok" | "unknown";
}

export function CapacityOverview({
  variations,
  stationDays,
}: CapacityOverviewProps) {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const presets = useDateRangePresets();

  // Default: today through one year ahead — the typical subscription horizon.
  const [range, setRange] = useState<[Dayjs, Dayjs]>(() => [
    dayjs(),
    dayjs().add(1, "year"),
  ]);

  const weekKeys = useMemo(() => termWeekKeys(range[0], range[1]), [range]);

  // The fetched capacity window (the union of week keys every entity carries).
  // A range with NO week in this set was never fetched — showing it as "free"
  // would be a confident lie, so those rows render as "unknown" instead.
  const windowKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const v of variations) {
      for (const k in v.capacity_by_week ?? {}) keys.add(k);
    }
    for (const d of stationDays) {
      for (const k in d.capacity_by_week ?? {}) keys.add(k);
    }
    return keys;
  }, [variations, stationDays]);

  const rangeInWindow = useMemo(
    () => weekKeys.some((k) => windowKeys.has(k)),
    [weekKeys, windowKeys],
  );

  const buildRows = (
    keyPrefix: string,
    entities: {
      value: string | number;
      label: string;
      capacity?: number | null;
      capacity_by_week?: Parameters<typeof termCapacity>[1];
    }[],
  ): CapacityRow[] =>
    entities.map((e) => {
      const base = {
        key: `${keyPrefix}-${e.value}`,
        id: `${keyPrefix}-${e.value}`,
        name: e.label,
        capacity: e.capacity ?? null,
      };
      if (!rangeInWindow) {
        return {
          ...base,
          peak_occupied: 0,
          free: null,
          peak_week: null,
          status: "unknown" as const,
        };
      }
      const cap = termCapacity(e.capacity, e.capacity_by_week, weekKeys);
      const free =
        cap.total == null ? null : Math.max(0, cap.total - cap.peakOccupied);
      // "tight" = ≤10% (min 1 slot) of the cap left but not yet full — an early
      // warning so the office can raise capacity before the waiting_list kicks in.
      const tight =
        cap.total != null &&
        free != null &&
        free > 0 &&
        free <= Math.max(1, cap.total * 0.1);
      return {
        key: `${keyPrefix}-${e.value}`,
        id: `${keyPrefix}-${e.value}`,
        name: e.label,
        capacity: cap.total,
        peak_occupied: cap.peakOccupied,
        free,
        peak_week: cap.peakWeekKey,
        status: cap.isFull ? "full" : tight ? "tight" : "ok",
      };
    });

  const variationRows = useMemo(
    () => buildRows("var", variations),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [variations, weekKeys],
  );

  const stationRows = useMemo(
    () => buildRows("dsd", stationDays),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stationDays, weekKeys],
  );

  const columns = useMemo<EditableColumnConfig<CapacityRow>[]>(
    () => [
      {
        title: <>{t("abos.capacity_col_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "left",
        sortable: true,
      },
      {
        title: <>{t("abos.capacity_col_capacity")}</>,
        dataIndex: "capacity",
        key: "capacity",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "center",
        width: "8em",
        render: (value: unknown) =>
          value == null ? t("abos.capacity_unlimited") : (value as number),
      },
      {
        title: <>{t("abos.capacity_col_peak_occupied")}</>,
        dataIndex: "peak_occupied",
        key: "peak_occupied",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "center",
        width: "9em",
        sortable: true,
        render: (value: unknown, record: CapacityRow) =>
          record.status === "unknown" ? "—" : (value as number),
      },
      {
        title: <>{t("abos.capacity_col_free")}</>,
        dataIndex: "free",
        key: "free",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "center",
        width: "8em",
        sortable: true,
        render: (value: unknown, record: CapacityRow) =>
          record.status === "unknown"
            ? "—"
            : value == null
              ? t("abos.capacity_unlimited")
              : (value as number),
      },
      {
        title: <>{t("abos.capacity_col_peak_week")}</>,
        dataIndex: "peak_week",
        key: "peak_week",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "center",
        width: "9em",
        render: (value: unknown) =>
          value ? formatWeekKey(value as string) : "—",
      },
      {
        title: <>{t("abos.capacity_col_status")}</>,
        dataIndex: "status",
        key: "status",
        inputType: "text",
        readOnly: true,
        disabled: true,
        align: "center",
        width: "9em",
        sortable: true,
        render: (value: unknown) => {
          const status = value as CapacityRow["status"];
          const color =
            status === "full"
              ? "red"
              : status === "tight"
                ? "orange"
                : status === "unknown"
                  ? "default"
                  : "green";
          return <Tag color={color}>{t(`abos.capacity_status_${status}`)}</Tag>;
        },
      },
    ],
    [t],
  );

  // Drop quick-range presets that fall entirely outside the fetched window
  // (e.g. "last year") — picking one would just paint every row "unknown".
  const inWindowPresets = useMemo(
    () =>
      presets.filter((p) =>
        termWeekKeys(p.value[0], p.value[1]).some((k) => windowKeys.has(k)),
      ),
    [presets, windowKeys],
  );

  const rangeLabel = `${range[0].format(dateFormat)} – ${range[1].format(dateFormat)}`;

  return (
    <Collapse
      style={{ borderColor: "var(--color-primary)" }}
      items={[
        {
          key: "capacities",
          label: `${t("abos.capacities_overview")} (${rangeLabel})`,
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <DatePicker.RangePicker
                // Size to content instead of stretching to the full panel
                // width in the flex column.
                style={{ alignSelf: "flex-start" }}
                value={range}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setRange([dates[0], dates[1]]);
                  }
                }}
                format={dateFormat}
                allowClear={false}
                presets={inWindowPresets}
              />

              {!rangeInWindow ? (
                <div style={{ color: "var(--color-text-tertiary)" }}>
                  {t("abos.capacity_out_of_window")}
                </div>
              ) : null}

              <div>
                <h3>{t("abos.capacities_variations")}</h3>
                <EditableTable
                  columns={columns}
                  initialData={variationRows}
                  permissions={READ_ONLY_PERMISSION}
                  pagination={false}
                  showSearchBar={false}
                />
              </div>

              <div>
                <h3>{t("abos.capacities_station_days")}</h3>
                <EditableTable
                  columns={columns}
                  initialData={stationRows}
                  permissions={READ_ONLY_PERMISSION}
                  pagination={true}
                  showSearchBar={true}
                />
              </div>
            </div>
          ),
        },
      ]}
    />
  );
}
