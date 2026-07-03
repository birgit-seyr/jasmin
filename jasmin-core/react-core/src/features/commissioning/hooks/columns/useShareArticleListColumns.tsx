/**
 * Column factory for the ListShareArticles (share-article data list) page.
 * The page supplies the prebuilt is-active / price-modal column refs, the
 * unit/crate/share-option options, the active-filter + tenant flags, and the
 * harvest/purchase number renderers; every column shape lives here.
 */

import type { ReactNode } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
import { organicStatusOptions } from "@hooks/index";
import { useNumberFormat } from "@hooks/useNumberFormat";
import type { CrateOption } from "../useCrates";
import { isFieldDisabled } from "@shared/utils";

// Pure row predicates — a row is harvest-only or purchase-only based on
// ``is_purchased``. Module-level so they're stable references.
const isHarvestDisabled = (record: TableRecord) =>
  record.is_purchased === true;
const isPurchaseDisabled = (record: TableRecord) =>
  record.is_purchased === false;

interface ShareOptionLite {
  value: string;
  label: string;
}

interface UnitOptionLite {
  value: string;
  label: string;
}

interface UseShareArticleListColumnsArgs {
  isActiveColumn: Record<string, unknown>;
  priceModalColumn: Record<string, unknown>;
  unitOptions: UnitOptionLite[];
  crates: CrateOption[];
  organicGateEnabled: boolean;
  visibleShareOptions: ShareOptionLite[];
  activeFilter: string;
  sells_to_resellers: boolean;
  has_markets: boolean;
  number_packing_stations: number;
  packingBulk: boolean;
  renderHarvestNumber: (
    decimals: number,
  ) => (value: number, record: TableRecord) => ReactNode;
  renderPurchaseNumber: (
    decimals: number,
  ) => (value: number, record: TableRecord) => ReactNode;
}

export function useShareArticleListColumns({
  isActiveColumn,
  priceModalColumn,
  unitOptions,
  crates,
  organicGateEnabled,
  visibleShareOptions,
  activeFilter,
  sells_to_resellers,
  has_markets,
  number_packing_stations,
  packingBulk,
  renderHarvestNumber,
  renderPurchaseNumber,
}: UseShareArticleListColumnsArgs): EditableColumnConfig<TableRecord>[] {
  const { t } = useTranslation();
  const { format } = useNumberFormat();

  return useMemo(
    () =>
      [
        isActiveColumn,
        {
          title: <>{t("commissioning.article_number")}</>,
          dataIndex: "article_number",
          key: "article_number",
          inputType: "text",
          required: false,
          width: "6em",
          align: "left",
          fixed: true,
          sortable: true,
        },
        {
          title: <>{t("commissioning.name")}</>,
          dataIndex: "name",
          key: "name",
          inputType: "text",
          required: true,
          width: "14em",
          align: "left",
          fixed: true,
          sortable: true,
          disabled: isFieldDisabled,
        },
        priceModalColumn,
        {
          title: (
            <>
              {t("commissioning.default_movement_unit")}
              <ToolTipIcon title={t("tooltip.default_movement_unit")} />
            </>
          ),
          dataIndex: "default_movement_unit",
          key: "default_movement_unit",
          inputType: "select",
          required: true,
          width: "8em",
          align: "center",
          fixed: true,
          options: unitOptions,
          disabled: isFieldDisabled,

          render: (value: string) => {
            const unitOption = unitOptions.find(
              (option: { value: string; label: string }) =>
                option.value === value,
            );
            return unitOption ? unitOption.label : value;
          },
        },
        {
          title: <>{t("commissioning.is_purchased")}</>,
          dataIndex: "is_purchased",
          key: "is_purchased",
          inputType: "checkbox",
          required: false,
          fixed: true,
          disabled: isFieldDisabled,
          sortable: true,
        },

        ...(organicGateEnabled
          ? (() => {
              const organicOptions = organicStatusOptions(t);
              return [
                {
                  title: <>{t("commissioning.organic_status")}</>,
                  dataIndex: "organic_status",
                  key: "organic_status",
                  inputType: "select",
                  required: false,
                  sortable: true,
                  options: organicOptions,
                  render: (value: string) => {
                    const match = organicOptions.find((o) => o.value === value);
                    return match ? match.label : value || "-";
                  },
                },
              ];
            })()
          : []),
        {
          title: <>{t("commissioning.description")}</>,
          dataIndex: "description",
          key: "description",
          inputType: "text",
          required: false,
          width: "24em",
        },
        ...(activeFilter === "all"
          ? visibleShareOptions
          : visibleShareOptions.filter(
              (opt: { value: string }) =>
                opt.value.toLowerCase() === activeFilter,
            )
        ).map((opt: { value: string; label: string }, idx: number) => ({
          title: (
            <span style={{ fontSize: "0.85em" }}>
              {t(`commissioning.share_option.${opt.value}`, opt.label)}
            </span>
          ),
          dataIndex: opt.value.toLowerCase(),
          key: opt.value.toLowerCase(),
          inputType: "checkbox",
          required: false,
          sortable: true,

          ...(idx === 0 ? { className: "column-group-start" } : {}),
        })),
        {
          title: <>{t("commissioning.for_resellers")}</>,
          dataIndex: "is_sold_to_resellers",
          key: "is_sold_to_resellers",
          inputType: "checkbox",
          required: false,
          hidden: !sells_to_resellers,
          className: "column-group-start",
          sortable: true,
        },
        {
          title: <>{t("commissioning.for_markets")}</>,
          dataIndex: "for_markets",
          key: "for_markets",
          inputType: "checkbox",
          required: false,
          hidden: !has_markets,
          sortable: true,
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.kg_per_piece_S")}</span>
          ),
          dataIndex: "kg_per_piece_S",
          key: "kg_per_piece_S",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",
          className: "column-group-start",

          render: (value: number) => (value ? format(Number(value), 3) : null),
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.kg_per_piece_M")}</span>
          ),
          dataIndex: "kg_per_piece_M",
          key: "kg_per_piece_M",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",

          render: (value: number) => (value ? format(Number(value), 3) : null),
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.kg_per_piece_L")}</span>
          ),
          dataIndex: "kg_per_piece_L",
          key: "kg_per_piece_L",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",

          render: (value: number) => (value ? format(Number(value), 3) : null),
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.pieces_per_kg_S")}</span>
          ),
          dataIndex: "pieces_per_kg_S",
          key: "pieces_per_kg_S",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6em",
          className: "column-group-start",

          render: (value: number) => (value ? format(Number(value), 0) : null),
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.pieces_per_kg_M")}</span>
          ),
          dataIndex: "pieces_per_kg_M",
          key: "pieces_per_kg_M",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6em",

          render: (value: number) => (value ? format(Number(value), 0) : null),
        },
        {
          title: (
            <span className="text-sm">{t("commissioning.pieces_per_kg_L")}</span>
          ),
          dataIndex: "pieces_per_kg_L",
          key: "pieces_per_kg_L",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6em",

          render: (value: number) => (value ? format(Number(value), 0) : null),
        },
        {
          title: (
            <div className="checkbox-column-title">
              {t("commissioning.packing_station")}
            </div>
          ),
          dataIndex: "default_packing_station",
          key: "default_packing_station",
          inputType: "select",
          width: "4.5em",
          required: false,
          className: "column-group-start",
          align: "center",
          sortable: true,
          options: Array.from({ length: number_packing_stations }, (_, i) => ({
            label: i + 1,
            value: i + 1,
          })),
        },
        ...(packingBulk
          ? [
              {
                title: (
                  <span className="text-sm">
                    {t("commissioning.percentage_added_to_bulk_packing_list")}
                  </span>
                ),
                dataIndex: "percentage_added_to_bulk_packing_list",
                key: "percentage_added_to_bulk_packing_list",
                inputType: "positive_integer",
                required: false,
                align: "center",
                width: "7em",
                className: "column-group-start",
                render: (value: number) =>
                  value ? `${format(Number(value), 0)} %` : null,
              },
            ]
          : []),
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_kg_per_pu_harvest")}
            </span>
          ),
          dataIndex: "default_kg_per_pu_harvest",
          key: "default_kg_per_pu_harvest",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",
          className: "column-group-start",
          disabled: isHarvestDisabled,
          render: renderHarvestNumber(3),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_pieces_per_pu_harvest")}
            </span>
          ),
          dataIndex: "default_pieces_per_pu_harvest",
          key: "default_pieces_per_pu_harvest",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6.5em",
          disabled: isHarvestDisabled,
          render: renderHarvestNumber(0),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_bunches_per_pu_harvest")}
            </span>
          ),
          dataIndex: "default_bunches_per_pu_harvest",
          key: "default_bunches_per_pu_harvest",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "7em",
          disabled: isHarvestDisabled,
          render: renderHarvestNumber(0),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_crate_harvest")}
            </span>
          ),
          dataIndex: "default_crate_harvest_name",
          key: "default_crate_harvest_name",
          inputType: "select",
          required: false,
          align: "center",
          width: "9em",
          options: crates,
          foreignKey: {
            valueField: "default_crate_harvest",
            displayField: "default_crate_harvest_name",
          },
          sortable: true,
          disabled: isHarvestDisabled,
          render: (value: string, record: TableRecord) =>
            isHarvestDisabled(record) ? null : (value ?? null),
        },
        {
          title: (
            <>
              {t("commissioning.default_commissioning_unit")}
              <ToolTipIcon title={t("tooltip.default_commissioning_unit")} />
            </>
          ),
          dataIndex: "default_commissioning_unit",
          key: "default_commissioning_unit",
          inputType: "select",
          required: false,
          width: "8em",
          align: "center",
          fixed: true,
          options: unitOptions,
          className: "column-group-start",
          render: (value: string) => {
            const unitOption = unitOptions.find(
              (option: { value: string; label: string }) =>
                option.value === value,
            );
            return unitOption ? unitOption.label : value;
          },
        },

        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_kg_per_pu_reseller")}
            </span>
          ),
          dataIndex: "default_kg_per_pu_reseller",
          key: "default_kg_per_pu_reseller",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",

          render: (value: number) => (value ? format(Number(value), 3) : null),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_pieces_per_pu_reseller")}
            </span>
          ),
          dataIndex: "default_pieces_per_pu_reseller",
          key: "default_pieces_per_pu_reseller",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6.5em",

          render: (value: number) => (value ? format(Number(value), 0) : null),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_bunches_per_pu_reseller")}
            </span>
          ),
          dataIndex: "default_bunches_per_pu_reseller",
          key: "default_bunches_per_pu_reseller",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "7em",

          render: (value: number) => (value ? format(Number(value), 0) : null),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_crate_reseller")}
            </span>
          ),
          dataIndex: "default_crate_reseller_name",
          key: "default_crate_reseller_name",
          inputType: "select",
          required: false,
          align: "center",
          width: "9em",
          options: crates,
          foreignKey: {
            valueField: "default_crate_reseller",
            displayField: "default_crate_reseller_name",
          },
          sortable: true,
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_kg_per_pu_purchase")}
            </span>
          ),
          dataIndex: "default_kg_per_pu_purchase",
          key: "default_kg_per_pu_purchase",
          inputType: "positive_decimal3",
          required: false,
          align: "center",
          width: "6em",
          className: "column-group-start",
          disabled: isPurchaseDisabled,
          render: renderPurchaseNumber(3),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_pieces_per_pu_purchase")}
            </span>
          ),
          dataIndex: "default_pieces_per_pu_purchase",
          key: "default_pieces_per_pu_purchase",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "6.5em",
          disabled: isPurchaseDisabled,
          render: renderPurchaseNumber(0),
        },
        {
          title: (
            <span className="text-sm">
              {t("commissioning.default_bunches_per_pu_purchase")}
            </span>
          ),
          dataIndex: "default_bunches_per_pu_purchase",
          key: "default_bunches_per_pu_purchase",
          inputType: "positive_integer",
          required: false,
          align: "center",
          width: "7em",
          disabled: isPurchaseDisabled,
          render: renderPurchaseNumber(0),
        },
      ] as EditableColumnConfig<TableRecord>[],
    [
      activeFilter,
      crates,
      format,
      has_markets,
      isActiveColumn,
      number_packing_stations,
      organicGateEnabled,
      packingBulk,
      priceModalColumn,
      renderHarvestNumber,
      renderPurchaseNumber,
      sells_to_resellers,
      t,
      unitOptions,
      visibleShareOptions,
    ],
  );
}
