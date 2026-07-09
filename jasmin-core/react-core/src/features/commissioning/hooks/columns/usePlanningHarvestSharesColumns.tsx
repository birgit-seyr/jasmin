import { EditOutlined } from "@ant-design/icons";
import { Button } from "antd";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { editableOnlyOnCreate } from "@shared/utils";
import {
  planningColors,
  planningRowEmphasis,
} from "@shared/styles/planningColors";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useSellerColumn } from "./useSellerColumn";

interface DataHasNotes {
  hasForecastNote: boolean;
  hasStockNote: boolean;
}

interface UsePlanningHarvestSharesColumnsArgs {
  finalColumn: EditableColumnConfig<TableRecord>;
  shareArticleColumn: EditableColumnConfig<TableRecord>;
  amountUnitSizeColumns: EditableColumnConfig<TableRecord>[];
  washingCleaningColumns: EditableColumnConfig<TableRecord>[];
  noteColumn: EditableColumnConfig<TableRecord>;
  deliveryDayColumns: EditableColumnConfig<TableRecord>[];
  showDetailedColumns: boolean;
  dataHasNotes: DataHasNotes;
  calculateStillFree: (record: TableRecord) => number;
  number_packing_stations: number;
  formatCurrency: (amount: number | null | undefined) => string;
  getUnitLabel: (unit: string) => string;
  setIsBackupModalOpen: Dispatch<SetStateAction<boolean>>;
  setSelectedBackupData: Dispatch<SetStateAction<TableRecord | null>>;
}

export function usePlanningHarvestSharesColumns(
  args: UsePlanningHarvestSharesColumnsArgs,
): EditableColumnConfig<TableRecord>[] {
  const {
    finalColumn,
    shareArticleColumn,
    amountUnitSizeColumns,
    washingCleaningColumns,
    noteColumn,
    deliveryDayColumns,
    showDetailedColumns,
    dataHasNotes,
    calculateStillFree,
    number_packing_stations,
    formatCurrency,
    getUnitLabel,
    setIsBackupModalOpen,
    setSelectedBackupData,
  } = args;
  const { t } = useTranslation();
  const { format } = useNumberFormat();
  const sellerColumn = useSellerColumn({
    titleKey: "commissioning.seller_for_purchase",
  });

  return useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const baseColumns: EditableColumnConfig<TableRecord>[] = [
      finalColumn,
      {
        ...shareArticleColumn,
        disabled: editableOnlyOnCreate,
        // Forecast rows pop in green + bold so they read as "system
        // told us to plant this". Stock-only rows pick up the colour
        // but stay at normal weight — they're a hint, not a directive.
        render: (value: unknown, record: TableRecord) => (
          <span style={planningRowEmphasis(record)}>{value as string}</span>
        ),
      },
      // Wrap the shared unit/size/amount columns so they pick up the
      // same forecast/stock highlight that the share-article-name cell
      // uses (green when the row was scaffolded from a forecast, blue
      // when there's leftover stock to work with). Done here rather
      // than inside ``useColumnsAmountSizeUnit`` so that other consumers
      // (orders, etc.) of the shared hook stay neutral — the colour
      // ladder is planning-specific.
      ...amountUnitSizeColumns.map((col) => ({
        ...col,
        render: (value: unknown, record: TableRecord, index: number) => {
          const inner = col.render
            ? col.render(value, record, index)
            : (value as ReactNode);
          return <span style={planningRowEmphasis(record)}>{inner}</span>;
        },
      })),
      {
        title: (
          <div className="small-title">
            {t("commissioning.kg_per_piece")}{" "}
            <ToolTipIcon title={t("tooltip.kg_per_piece_share_content")} />
          </div>
        ),
        dataIndex: "kg_per_piece",
        key: "kg_per_piece",
        width: "6em",
        inputType: "positive_decimal3",
        required: false,
        hidden: !showDetailedColumns,

        render: (value: unknown) =>
          value !== null && value !== undefined ? (
            <div className="small-title">{format(value as number, 2)}</div>
          ) : (
            ""
          ),
      },
      {
        title: (
          <div className="small-title">
            {t("commissioning.price_per_unit_share_content")}{" "}
            <ToolTipIcon title={t("tooltip.price_per_unit_share_content")} />
          </div>
        ),
        dataIndex: "price_per_unit",
        key: "price_per_unit",
        inputType: "positive_decimal2",
        width: "8em",
        required: false,
        hidden: !showDetailedColumns,

        render: (value: unknown, record: TableRecord) =>
          value !== null && value !== undefined ? (
            <div className="small-title">
              {formatCurrency(Number(value))}/{getUnitLabel(record.unit as string)}
            </div>
          ) : (
            ""
          ),
      },
      {
        title: (
          <div className="tiny-title">
            {t("commissioning.forecast_available_amount")}
          </div>
        ),
        dataIndex: "forecast_available_amount",
        key: "forecast_available_amount",
        width: "8em",
        required: false,
        align: "center",
        disabled: true,
        readOnly: true,
        hidden: !showDetailedColumns,
        render: (_: unknown, record: TableRecord) => (
          <div className="read-only-amounts-planning">
            {record.forecast_available_amount
              ? format(record.forecast_available_amount as number, 0)
              : record.forecast_unit
                ? t("commissioning.forecast_enough_available")
                : ""}
          </div>
        ),
      },
      ...(dataHasNotes.hasForecastNote
        ? ([
            {
              title: (
                <div className="tiny-title">
                  {t("commissioning.forecast_note")}
                </div>
              ),
              dataIndex: "forecast_note",
              key: "forecast_note",
              width: "10em",
              required: false,
              align: "left",
              disabled: true,
              readOnly: true,
              hidden: !showDetailedColumns,
              render: (value: unknown) => (
                <div className="read-only-amounts-planning">
                  {value as string}
                </div>
              ),
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      {
        title: (
          <div className="tiny-title">
            {t(
              "commissioning.available_amount_current_stock_at_time_of_planning",
            )}
          </div>
        ),
        dataIndex: "current_stock_begin_of_week",
        key: "current_stock_begin_of_week",
        width: "5em",
        required: false,
        align: "center",
        disabled: true,
        readOnly: true,
        hidden: !showDetailedColumns,
        render: (value: unknown) => (
          <div className="read-only-amounts-planning">{value as string}</div>
        ),
      },
      ...(dataHasNotes.hasStockNote
        ? ([
            {
              title: (
                <div className="tiny-title">
                  {t("commissioning.current_stock_note")}
                </div>
              ),
              dataIndex: "current_stock_note",
              key: "current_stock_note",
              width: "10em",
              required: false,
              align: "left",
              disabled: true,
              readOnly: true,
              hidden: !showDetailedColumns,
              render: (value: unknown) => (
                <div className="read-only-amounts-planning">
                  {value as string}
                </div>
              ),
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      {
        title: (
          <div className="tiny-title">{t("commissioning.still_free")}</div>
        ),
        dataIndex: "still_free",
        key: "still_free",
        width: "5em",
        required: false,
        align: "center",
        disabled: true,
        readOnly: true,
        hidden: !showDetailedColumns,
        render: (_: unknown, record: TableRecord) => {
          const stillFree = calculateStillFree(record);
          return (
            <div
              className="read-only-amounts-planning"
              style={{
                color:
                  stillFree < 0
                    ? planningColors.overPlanned
                    : planningColors.ok,
                fontWeight: stillFree < 0 ? "bold" : "normal",
              }}
            >
              {format(stillFree, 0)}
            </div>
          );
        },
      },
    ];

    const endColumns: EditableColumnConfig<TableRecord>[] = [
      { ...washingCleaningColumns[0], className: "column-group-start" },
      ...washingCleaningColumns.slice(1),
      ...(number_packing_stations > 1
        ? ([
            {
              title: (
                <div className="checkbox-column-title">
                  {t("commissioning.packing_station")}
                </div>
              ),
              dataIndex: "packing_station",
              key: "packing_station",
              inputType: "select",
              width: "4.5em",
              required: false,
              align: "center",
              options: Array.from(
                { length: number_packing_stations },
                (_, i) => ({
                  label: String(i + 1),
                  value: i + 1,
                }),
              ),
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      sellerColumn,
      {
        title: <div className="backup-title">{t("commissioning.backup")}</div>,
        key: "backup",
        dataIndex: "backup",
        align: "center",
        width: "8em",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: TableRecord) => {
          if (record.key === "summary-row") {
            return "";
          }

          const hasBackup = Boolean(record.backup_share_article);

          return (
            <>
              <Button
                size="small"
                type="text"
                icon={<EditOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  setIsBackupModalOpen(true);
                  setSelectedBackupData(record);
                }}
                style={{
                  minWidth: "auto",
                  padding: "0 4px",
                  backgroundColor: hasBackup
                    ? "var(--color-success-bg)"
                    : undefined,
                  color: hasBackup ? "var(--color-success-text)" : undefined,
                }}
              >
                <strong>B</strong>
              </Button>
              <ToolTipIcon
                title={t("tooltip.backup_for_share_content")}
                style={{ marginLeft: 4 }}
              />
            </>
          );
        },
      },
      {
        ...noteColumn,
        title: (
          <>
            {t("commissioning.note")}{" "}
            <ToolTipIcon
              title={t("commissioning.harvest_share_planning_note")}
            />
          </>
        ),
      },
    ];

    return [...baseColumns, ...deliveryDayColumns, ...endColumns];
  }, [
    t,
    finalColumn,
    shareArticleColumn,
    amountUnitSizeColumns,
    washingCleaningColumns,
    noteColumn,
    deliveryDayColumns,
    showDetailedColumns,
    dataHasNotes,
    calculateStillFree,
    number_packing_stations,
    sellerColumn,
    formatCurrency,
    getUnitLabel,
    setIsBackupModalOpen,
    setSelectedBackupData,
    format,
  ]);
}
