import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import type { MarketPriceListGroup } from "@features/commissioning/pdfs/exports/MarketPriceListPDF";

/** How many active prices each product group has this week. */
export default function MarketPriceGroupCounts({
  groups,
}: {
  groups: MarketPriceListGroup[] | null;
}) {
  const { t } = useTranslation();
  if (!groups || groups.length === 0) return null;

  return (
    <div className="button-row-spaced flex-center-y">
      <strong>{t("commissioning.market_prices_per_group")}</strong>
      {groups.map((group) => (
        <Tag key={group.label}>
          {group.label}: {group.rows.length}
        </Tag>
      ))}
    </div>
  );
}
