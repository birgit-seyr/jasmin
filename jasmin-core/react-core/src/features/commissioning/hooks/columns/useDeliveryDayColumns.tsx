import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import {
  amountCellText,
  decimalsForUnit,
  formatAmountForUnit,
} from "@shared/utils";
import { getShareTypeVariationSizeLabelPure } from "@hooks/index";
import { useNumberFormat } from "@hooks/useNumberFormat";
import type { ShareDeliveryDayOption } from "../useShareDeliveryDays";
import type { ShareTypeVariationOption } from "../useShareTypeVariations";
import { computePlannedAmountForDay } from "../usePlanningSummaryData";
import { planningRowUnit } from "../../utils/planningRow";
import {
  dayAvailableStockKey,
  dayCellTier,
  dayPlannedAmountKey,
  dayVariationKey,
  variationColumnKey,
} from "./columnKeys";

export type DeliveryDay = ShareDeliveryDayOption;

const AMOUNT_COLUMN_WIDTH = "5.5em";

interface UseDeliveryDayColumnsParams {
  shareDeliveryDays: DeliveryDay[];
  shareTypeVariations: ShareTypeVariationOption[];
  showDaysTogether: boolean;
  showDetailedColumns: boolean;
  planningMode: string;
  showForecastClassification: boolean;
  /** Counts of subscribers per variation-day key, used to derive the
   *  per-day "planned amount" live as the user types into variation cells.
   *  Optional so existing callers that don't display planned_amount aren't
   *  forced to pass it. */
  shareTypeVariationAmountsSummary?: Record<string, string>;
}

export function useDeliveryDayColumns({
  shareDeliveryDays,
  shareTypeVariations,
  showDaysTogether,
  showDetailedColumns,
  planningMode,
  showForecastClassification,
  shareTypeVariationAmountsSummary,
}: UseDeliveryDayColumnsParams) {
  const { t } = useTranslation();
  const { format } = useNumberFormat();

  const deliveryDayColumns = useMemo(() => {
    const shouldHighlightEmpty = (record: TableRecord, variationId: string) => {
      if (!record.forecast_share_type_variation_ids) return false;
      return (
        showForecastClassification &&
        (record.forecast_share_type_variation_ids as string[]).includes(variationId)
      );
    };

    const renderVariationCell = (
      value: unknown,
      record: TableRecord,
      variationId: string,
    ) => {
      const numValue = Number(value);
      const isEmpty = !value || isNaN(numValue) || numValue === 0;
      const shouldHighlight =
        shouldHighlightEmpty(record, variationId) && isEmpty;

      if (isEmpty && !shouldHighlight) return "";

      const displayValue = formatAmountForUnit(
        numValue,
        planningRowUnit(record),
        format,
      );

      return (
        <div
          className={
            shouldHighlight
              ? "planning-variation-cell planning-variation-cell-highlight"
              : "planning-variation-cell"
          }
        >
          {!isEmpty && displayValue}
        </div>
      );
    };

    /** The whole-day amount cell of a (day, variation) pair. */
    const createBasicVariationColumn = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
      title: ReactNode,
    ): EditableColumnConfig<TableRecord> => {
      const key = dayVariationKey({
        dayId: deliveryDay.id!,
        variationId: variation.id!,
      });
      return {
        title,
        dataIndex: key,
        key,
        inputType: "positive_decimal2",
        align: "center",
        width: AMOUNT_COLUMN_WIDTH,
        render: (value: unknown, record: TableRecord) =>
          renderVariationCell(value, record, variation.id as string),
      };
    };

    // Tour/station leaf columns — the per-tour and per-station amount cells
    // for a (day, variation) pair. Shared by BOTH layouts: the variation-major
    // ("days together") and the day-major columns build the identical leaves;
    // only the parent header (day label vs. size label) differs.
    const buildTourLeaves = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord>[] =>
      (deliveryDay.used_tours ?? []).map((tourNumber) => {
        const tourKey = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          tour: tourNumber,
        });
        return {
          title: `T${tourNumber}`,
          dataIndex: tourKey,
          key: tourKey,
          inputType: "positive_decimal2",
          align: "center",
          width: AMOUNT_COLUMN_WIDTH,
          render: (value: unknown, record: TableRecord) =>
            renderVariationCell(value, record, variation.id as string),
        };
      });

    const buildStationLeaves = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord>[] =>
      deliveryDay.delivery_stations?.map((station) => {
        const stationKey = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          station: station.id,
        });
        return {
          title: `${station.short_name}`,
          dataIndex: stationKey,
          key: stationKey,
          inputType: "positive_decimal2",
          align: "center",
          width: "8em",
          render: (value: unknown, record: TableRecord) =>
            renderVariationCell(value, record, variation.id as string),
        };
      }) || [];

    /** The (day, variation) cell split into the day's tours or stations, or
     *  the whole-day leaf when the day is planned as a whole (`dayCellTier`). */
    const createVariationColumn = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
      title: ReactNode,
    ): EditableColumnConfig<TableRecord> => {
      const bareColumn = createBasicVariationColumn(deliveryDay, variation, title);
      const tier = dayCellTier(deliveryDay, planningMode);
      if (tier === "bare") return bareColumn;
      return {
        title,
        dataIndex: bareColumn.dataIndex,
        key: bareColumn.key,
        align: "center",
        children:
          tier === "tour"
            ? buildTourLeaves(deliveryDay, variation)
            : buildStationLeaves(deliveryDay, variation),
      };
    };

    // The day's planned total, computed live from the variation cells ×
    // subscriber counts. The `record` is the saved record on idle rows and
    // the form's live record on the row being edited (see EditableCell's
    // disabled-cell re-render). Without a counts summary the saved total
    // stands in.
    const plannedAmountOf = (
      record: TableRecord,
      deliveryDay: DeliveryDay,
      savedTotal: unknown = record[dayPlannedAmountKey(deliveryDay.id!)],
    ) =>
      shareTypeVariationAmountsSummary
        ? computePlannedAmountForDay(
            record as Record<string, unknown>,
            deliveryDay,
            shareTypeVariations,
            shareTypeVariationAmountsSummary,
            planningMode,
          )
        : Number(savedTotal) || 0;

    const createPlannedAmountColumn = (
      deliveryDay: DeliveryDay,
    ): EditableColumnConfig<TableRecord> => ({
      title: (
        <div className="tiny-title">
          {t("commissioning.total_planned_amount")}
        </div>
      ),
      dataIndex: dayPlannedAmountKey(deliveryDay.id!),
      key: dayPlannedAmountKey(deliveryDay.id!),
      inputType: "positive_integer",
      align: "center",
      width: "4.5em",
      hidden: !showDetailedColumns,
      disabled: true,
      render: (value: unknown, record: TableRecord) => (
        <div className="read-only-amounts-planning">
          {amountCellText(
            plannedAmountOf(record, deliveryDay, value),
            planningRowUnit(record),
            format,
          )}
        </div>
      ),
    });

    // The article's stock before the day's shares are packed, against the
    // day's planned total: green while it covers it, red with the shortfall
    // where it doesn't, plain where nothing is planned.
    const createAvailableStockColumn = (
      deliveryDay: DeliveryDay,
    ): EditableColumnConfig<TableRecord> => ({
      title: (
        <div className="tiny-title">
          {t("commissioning.available_amount_harvest")}
          <ToolTipIcon title={t("tooltip.available_amount_harvest")} />
        </div>
      ),
      dataIndex: dayAvailableStockKey(deliveryDay.id!),
      key: dayAvailableStockKey(deliveryDay.id!),
      inputType: "text",
      align: "center",
      width: "6.5em",
      hidden: !showDetailedColumns,
      disabled: true,
      render: (value: unknown, record: TableRecord) => {
        if (value == null || value === "") return null;
        const available = Number(value);
        const unit = planningRowUnit(record);
        const planned = plannedAmountOf(record, deliveryDay);
        if (!(planned > 0)) {
          return (
            <div className="read-only-amounts-planning">
              {amountCellText(available, unit, format)}
            </div>
          );
        }
        // Short only by more than the unit's display precision can show.
        const shortfall = planned - available;
        const short = shortfall >= 0.5 * 10 ** -decimalsForUnit(unit);
        return (
          <div
            className={`read-only-amounts-planning ${
              short ? "available-stock-short" : "available-stock-enough"
            }`}
          >
            {formatAmountForUnit(available, unit, format)}
            {short &&
              ` ${t("commissioning.available_stock_shortfall", {
                diff: formatAmountForUnit(shortfall, unit, format),
              })}`}
          </div>
        );
      },
    });

    const withGroupStart = (
      columns: EditableColumnConfig<TableRecord>[],
    ): EditableColumnConfig<TableRecord>[] => {
      if (columns.length === 0) return columns;
      const first = columns[0];
      if (first.children) {
        return [
          {
            ...first,
            className: "column-group-start",
            children: withGroupStart(first.children),
          },
          ...columns.slice(1),
        ];
      }
      return [
        { ...first, className: "column-group-start" },
        ...columns.slice(1),
      ];
    };

    /** Mark the first leaf column of a group with column-variation-start. */
    const withVariationStart = (
      col: EditableColumnConfig<TableRecord>,
    ): EditableColumnConfig<TableRecord> => {
      if (col.children?.length) {
        const children = col.children;
        return {
          ...col,
          className: [col.className, "column-variation-start"].filter(Boolean).join(" "),
          children: [withVariationStart(children[0]), ...children.slice(1)],
        };
      }
      return {
        ...col,
        className: [col.className, "column-variation-start"].filter(Boolean).join(" "),
      };
    };

    if (showDaysTogether) {
      return shareTypeVariations.map(
        (variation: ShareTypeVariationOption, varIndex): EditableColumnConfig<TableRecord> => ({
          title: getShareTypeVariationSizeLabelPure(variation.size, t),
          dataIndex: variationColumnKey(variation.id!),
          key: variationColumnKey(variation.id!),
          className: varIndex === 0 ? "column-group-start" : "column-group-start column-variation-start",
          align: "center",
          children: withGroupStart(
            shareDeliveryDays.map((deliveryDay) =>
              createVariationColumn(deliveryDay, variation, deliveryDay.label),
            ),
          ),
        }),
      );
    } else {
      return shareDeliveryDays.map(
        (deliveryDay): EditableColumnConfig<TableRecord> => ({
          title: deliveryDay.label,
          dataIndex: `day_${deliveryDay.id}`,
          key: `day_${deliveryDay.id}`,
          className: "column-group-start",
          align: "center",
          children: withGroupStart([
            ...shareTypeVariations.map((variation: ShareTypeVariationOption, varIndex) => {
              const col = createVariationColumn(
                deliveryDay,
                variation,
                getShareTypeVariationSizeLabelPure(variation.size, t),
              );
              return varIndex === 0 ? col : withVariationStart(col);
            }),
            createPlannedAmountColumn(deliveryDay),
            createAvailableStockColumn(deliveryDay),
          ]),
        }),
      );
    }
  }, [
    shareDeliveryDays,
    shareTypeVariations,
    showDaysTogether,
    showDetailedColumns,
    planningMode,
    showForecastClassification,
    shareTypeVariationAmountsSummary,
    t,
    format,
  ]);

  return { deliveryDayColumns };
}
