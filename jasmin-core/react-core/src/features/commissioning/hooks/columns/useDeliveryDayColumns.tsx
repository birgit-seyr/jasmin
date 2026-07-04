import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { useNumberFormat } from "@hooks/useNumberFormat";
import type { ShareDeliveryDayOption } from "../useShareDeliveryDays";
import type { ShareTypeVariationOption } from "../useShareTypeVariations";
import { computePlannedAmountForDay } from "../usePlanningSummaryData";
import {
  dayHarvestedKey,
  dayPlannedAmountKey,
  dayVariationKey,
  variationColumnKey,
} from "./columnKeys";

// Orval types delivery_stations as string, but runtime data is an array of objects
interface DeliveryStation {
  id: string;
  short_name: string;
}

export type DeliveryDay = Omit<ShareDeliveryDayOption, "delivery_stations"> & {
  delivery_stations?: DeliveryStation[];
};

const AMOUNT_COLUMN_WIDTH = "5.5em";
const STATIONS_COLUMN_WIDTH = "8em";

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
      const isEmpty =
        !value || value === 0 || isNaN(numValue) || numValue === 0;
      const shouldHighlight =
        shouldHighlightEmpty(record, variationId) && isEmpty;

      if (isEmpty && !shouldHighlight) return "";

      const displayValue = !record.unit
        ? format(numValue, 2)
        : record.unit === "KG"
          ? format(numValue, 2)
          : format(numValue, 1);

      return (
        <div
          style={{
            backgroundColor: shouldHighlight ? "#fff3cd" : "transparent",
            padding: "4px",
            borderRadius: "2px",
            minHeight: "20px",
          }}
        >
          {!isEmpty && displayValue}
        </div>
      );
    };

    const createBasicVariationColumn = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord> => ({
      title: deliveryDay.label,
      dataIndex: dayVariationKey({
        dayId: deliveryDay.id!,
        variationId: variation.id!,
      }),
      key: dayVariationKey({ dayId: deliveryDay.id!, variationId: variation.id! }),
      // Same (day, variation) cell as the day-major layout and the tour/station
      // leaves — all `positive_decimal2`. This is the "days together" (variation-
      // major) rendering of it, so it must accept the same precision; it used to
      // be `positive_integer`, silently forbidding decimals only in this toggle
      // state (see docs/day-variation-columns-audit.md, Phase 4).
      inputType: "positive_decimal2",
      align: "center",
      width: AMOUNT_COLUMN_WIDTH,
      render: (value: unknown, record: TableRecord) =>
        renderVariationCell(value, record, variation.id as string),
    });

    const createTourVariationColumn = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord> => ({
      title: deliveryDay.label,
      dataIndex: dayVariationKey({
        dayId: deliveryDay.id!,
        variationId: variation.id!,
      }),
      key: dayVariationKey({ dayId: deliveryDay.id!, variationId: variation.id! }),
      align: "center",
      children: Array.from(
        { length: deliveryDay.used_tours?.length || 0 },
        (_, tourIndex) => {
          const tourNumber =
            deliveryDay.used_tours?.[tourIndex] || tourIndex + 1;

          return {
            title: `T${tourNumber}`,
            dataIndex: dayVariationKey({
              dayId: deliveryDay.id!,
              variationId: variation.id!,
              tour: tourNumber,
            }),
            key: dayVariationKey({
              dayId: deliveryDay.id!,
              variationId: variation.id!,
              tour: tourNumber,
            }),
            inputType: "positive_decimal2",
            align: "center",
            width: AMOUNT_COLUMN_WIDTH,
            render: (value: unknown, record: TableRecord) =>
              renderVariationCell(value, record, variation.id as string),
          };
        },
      ),
    });

    const createStationsVariationColumn = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord> => ({
      title: deliveryDay.label,
      dataIndex: dayVariationKey({
        dayId: deliveryDay.id!,
        variationId: variation.id!,
      }),
      key: dayVariationKey({ dayId: deliveryDay.id!, variationId: variation.id! }),
      align: "center",
      children:
        deliveryDay.delivery_stations?.map((station) => ({
          title: `${station.short_name}`,
          dataIndex: dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
            station: station.id,
          }),
          key: dayVariationKey({
            dayId: deliveryDay.id!,
            variationId: variation.id!,
            station: station.id,
          }),
          inputType: "positive_decimal2",
          align: "center",
          width: STATIONS_COLUMN_WIDTH,
          render: (value: unknown, record: TableRecord) =>
            renderVariationCell(value, record, variation.id as string),
        })) || [],
    });

    const createVariationColumnForDay = (
      deliveryDay: DeliveryDay,
      variation: ShareTypeVariationOption,
    ): EditableColumnConfig<TableRecord> => {
      const dayId = deliveryDay.id!;
      const variationId = variation.id!;
      const bareKey = dayVariationKey({ dayId, variationId });
      const baseColumn = {
        title: t(`commissioning.${variation.size}`),
        dataIndex: bareKey,
        key: bareKey,
        align: "center" as const,
      };

      if (planningMode === "tours") {
        return {
          ...baseColumn,
          children: Array.from(
            { length: deliveryDay.used_tours?.length || 0 },
            (_, tourIndex) => {
              const tourNumber =
                deliveryDay.used_tours?.[tourIndex] || tourIndex + 1;
              const tourKey = dayVariationKey({
                dayId,
                variationId,
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
            },
          ),
        };
      } else if (planningMode === "stations") {
        return {
          ...baseColumn,
          children:
            deliveryDay.delivery_stations?.map((station) => {
              const stationKey = dayVariationKey({
                dayId,
                variationId,
                station: station.id,
              });
              return {
                title: `${station.short_name}`,
                dataIndex: stationKey,
                key: stationKey,
                inputType: "positive_decimal2",
                align: "center",
                width: STATIONS_COLUMN_WIDTH,
                render: (value: unknown, record: TableRecord) =>
                  renderVariationCell(value, record, variation.id as string),
              };
            }) || [],
        };
      } else {
        return {
          ...baseColumn,
          dataIndex: bareKey,
          inputType: "positive_decimal2",
          width: AMOUNT_COLUMN_WIDTH,
          render: (value: unknown, record: TableRecord) =>
            renderVariationCell(value, record, variation.id as string),
        };
      }
    };

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
      // Computed live from variation cells × subscriber counts. The
      // `record` argument is the saved record on idle rows and the
      // form's live record on the row currently being edited (see
      // EditableCell's disabled-cell re-render). When no counts summary
      // is provided we fall back to the saved value to stay
      // backwards-compatible.
      render: (value: unknown, record: TableRecord) => {
        const planned = shareTypeVariationAmountsSummary
          ? computePlannedAmountForDay(
              record as Record<string, unknown>,
              deliveryDay,
              shareTypeVariations,
              shareTypeVariationAmountsSummary,
              planningMode,
            )
          : Number(value) || 0;
        return (
          <div className="read-only-amounts-planning">
            {planned ? format(planned, 0) : ""}
          </div>
        );
      },
    });

    const createHarvestedAmountColumn = (
      deliveryDay: DeliveryDay,
    ): EditableColumnConfig<TableRecord> => ({
      title: (
        <div className="tiny-title">
          {t("commissioning.available_amount_harvest")}
          <ToolTipIcon title={t("tooltip.available_amount_harvest")} />
        </div>
      ),
      dataIndex: dayHarvestedKey(deliveryDay.id!),
      key: dayHarvestedKey(deliveryDay.id!),
      inputType: "text",
      align: "center",
      width: "5em",
      hidden: !showDetailedColumns,
      disabled: true,
      render: (value: unknown) => (
        <div className="read-only-amounts-harvest">{value as string}</div>
      ),
    });

    const withGroupStart = (
      columns: EditableColumnConfig<TableRecord>[],
    ): EditableColumnConfig<TableRecord>[] => {
      if (!columns || columns.length === 0) return columns;
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
      if (col.children) {
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
          title: t(`commissioning.${variation.size}`),
          dataIndex: variationColumnKey(variation.id!),
          key: variationColumnKey(variation.id!),
          className: varIndex === 0 ? "column-group-start" : "column-group-start column-variation-start",
          align: "center",
          children: withGroupStart(
            shareDeliveryDays.map((deliveryDay) =>
              planningMode === "tours"
                ? createTourVariationColumn(deliveryDay, variation)
                : planningMode === "stations"
                  ? createStationsVariationColumn(deliveryDay, variation)
                  : createBasicVariationColumn(deliveryDay, variation),
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
              const col = createVariationColumnForDay(deliveryDay, variation);
              return varIndex === 0 ? col : withVariationStart(col);
            }),
            createPlannedAmountColumn(deliveryDay),
            createHarvestedAmountColumn(deliveryDay),
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
