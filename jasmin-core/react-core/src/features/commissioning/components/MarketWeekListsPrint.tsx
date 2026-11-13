/**
 * The print controls of the week's market lists: the price list and the order
 * list. Both can be narrowed to some product groups (the fruit list, say, or
 * an order list without the bread and honey), and the price list to the prices
 * that changed since last week; each says so under its title. The page keeps
 * the choice of groups, as it narrows the page's table too, and keeps it from
 * one week to the next.
 */

import { Checkbox, Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { generatePdfFilename } from "@shared/utils";
import { formatWeekLabel } from "@shared/utils/weekLabels";
import { isPickedGroup } from "@features/commissioning/hooks";
import {
  MarketOrderListPDFGenerator,
  MarketPriceListPDFGenerator,
} from "@features/commissioning/pdfs";
import type { MarketOrderListGroup } from "@features/commissioning/pdfs/exports/MarketOrderListPDF";
import type { MarketPriceListGroup } from "@features/commissioning/pdfs/exports/MarketPriceListPDF";

export default function MarketWeekListsPrint({
  priceGroups,
  orderGroups,
  pickedGroups,
  onPickedGroupsChange,
  isReady,
  year,
  week,
}: {
  /** The week's active prices by product group; null while loading. */
  priceGroups: MarketPriceListGroup[] | null;
  /** Every active PLU by product group; null while loading. */
  orderGroups: MarketOrderListGroup[] | null;
  /** The labels of the picked product groups; none picked means all. */
  pickedGroups: string[];
  onPickedGroupsChange: (groups: string[]) => void;
  isReady: boolean;
  year: number;
  week: number;
}) {
  const { t } = useTranslation();
  const [changedOnly, setChangedOnly] = useState(false);

  // Every group of either list, counted by its active prices this week.
  const groupOptions = useMemo(() => {
    const priceCounts = new Map(
      (priceGroups ?? []).map((group) => [group.label, group.rows.length]),
    );
    const labels = [
      ...(orderGroups ?? []).map((group) => group.label),
      ...priceCounts.keys(),
    ];
    return [...new Set(labels)].map((label) => ({
      value: label,
      label: `${label} (${priceCounts.get(label) ?? 0})`,
    }));
  }, [priceGroups, orderGroups]);

  const printedPriceGroups = useMemo<MarketPriceListGroup[] | null>(() => {
    if (!priceGroups) return null;
    return priceGroups
      .filter((group) => isPickedGroup(pickedGroups, group.label))
      .map((group) => ({
        ...group,
        rows: changedOnly ? group.rows.filter((row) => row.is_changed) : group.rows,
      }))
      .filter((group) => group.rows.length > 0);
  }, [priceGroups, pickedGroups, changedOnly]);

  const printedOrderGroups = useMemo(
    () =>
      orderGroups?.filter((group) => isPickedGroup(pickedGroups, group.label)) ??
      null,
    [orderGroups, pickedGroups],
  );

  const priceSubtitle = [
    changedOnly && t("commissioning.market_price_list_changed_only"),
    pickedGroups.join(", "),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <Select
        mode="multiple"
        allowClear
        className="market-prices__group-select"
        aria-label={t("commissioning.market_price_list_groups")}
        placeholder={t("commissioning.market_price_list_all_groups")}
        options={groupOptions}
        value={pickedGroups}
        onChange={onPickedGroupsChange}
      />
      <Checkbox
        checked={changedOnly}
        onChange={(event) => setChangedOnly(event.target.checked)}
      >
        {t("commissioning.market_price_list_changed_only")}
      </Checkbox>
      <MarketPriceListPDFGenerator
        groups={printedPriceGroups}
        isReady={isReady}
        year={year}
        week={week}
        subtitle={priceSubtitle || undefined}
        filename={generatePdfFilename([
          t("commissioning.market_price_list"),
          year,
          formatWeekLabel(week, t),
          changedOnly && t("commissioning.market_price_list_changed_only"),
        ])}
        buttonText={t("commissioning.market_price_list_pdf")}
        t={t}
      />
      <MarketOrderListPDFGenerator
        groups={printedOrderGroups}
        isReady={isReady}
        year={year}
        week={week}
        subtitle={pickedGroups.join(", ") || undefined}
        filename={generatePdfFilename([
          t("commissioning.market_order_list"),
          year,
          formatWeekLabel(week, t),
        ])}
        buttonText={t("commissioning.market_order_list_pdf")}
        t={t}
      />
    </>
  );
}
