/**
 * The market price list's print controls: the list can be narrowed to some
 * product groups (the fruit list, say) and to the prices that changed since
 * last week, and says so under its title.
 */

import { Checkbox, Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { generatePdfFilename } from "@shared/utils";
import { formatWeekLabel } from "@shared/utils/weekLabels";
import { MarketPriceListPDFGenerator } from "@features/commissioning/pdfs";
import type { MarketPriceListGroup } from "@features/commissioning/pdfs/exports/MarketPriceListPDF";

export default function MarketPriceListPrint({
  groups,
  isReady,
  year,
  week,
}: {
  /** The week's active prices by product group; null while loading. */
  groups: MarketPriceListGroup[] | null;
  isReady: boolean;
  year: number;
  week: number;
}) {
  const { t } = useTranslation();
  const [pickedGroups, setPickedGroups] = useState<string[]>([]);
  const [changedOnly, setChangedOnly] = useState(false);

  const groupOptions = useMemo(
    () =>
      (groups ?? []).map((group) => ({
        value: group.label,
        label: `${group.label} (${group.rows.length})`,
      })),
    [groups],
  );

  const printedGroups = useMemo<MarketPriceListGroup[] | null>(() => {
    if (!groups) return null;
    return groups
      .filter(
        (group) => pickedGroups.length === 0 || pickedGroups.includes(group.label),
      )
      .map((group) => ({
        ...group,
        rows: changedOnly ? group.rows.filter((row) => row.is_changed) : group.rows,
      }))
      .filter((group) => group.rows.length > 0);
  }, [groups, pickedGroups, changedOnly]);

  const subtitle = [
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
        onChange={setPickedGroups}
      />
      <Checkbox
        checked={changedOnly}
        onChange={(event) => setChangedOnly(event.target.checked)}
      >
        {t("commissioning.market_price_list_changed_only")}
      </Checkbox>
      <MarketPriceListPDFGenerator
        groups={printedGroups}
        isReady={isReady}
        year={year}
        week={week}
        subtitle={subtitle || undefined}
        filename={generatePdfFilename([
          t("commissioning.market_price_list"),
          year,
          formatWeekLabel(week, t),
          changedOnly && t("commissioning.market_price_list_changed_only"),
        ])}
        buttonText={t("commissioning.market_price_list_pdf")}
        t={t}
      />
    </>
  );
}
