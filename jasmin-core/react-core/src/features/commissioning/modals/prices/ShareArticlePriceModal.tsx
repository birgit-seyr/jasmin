import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningShareArticleNetPricesCreate,
  commissioningShareArticleNetPricesDestroy,
  commissioningShareArticleNetPricesPartialUpdate,
  getCommissioningShareArticleNetPricesListQueryKey,
  useCommissioningShareArticleNetPricesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ShareArticleNetPrice } from "@shared/api/generated/models/shareArticleNetPrice";
import {
  useActiveStatusColumn,
  useCurrency,
  useDefaultTaxRates,
  useNumberFormat,
  useTenant,
  useTimeBoundColumns,
} from "@hooks/index";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import PriceEditorModal from "./PriceEditorModal";
import { buildCurrencyPriceColumn, buildTaxRateColumn } from "./priceColumns";

interface ShareArticlePriceModalProps {
  visible: boolean;
  onClose: () => void;
  share_article: string | null;
  share_article_name: string;
  onSave?: () => void;
}

type Unit = "kg" | "pieces" | "bunch";
const UNITS: Unit[] = ["kg", "pieces", "bunch"];

export default function ShareArticlePriceModal({
  visible,
  onClose,
  share_article,
  share_article_name,
}: ShareArticlePriceModalProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { locale } = useNumberFormat();
  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    width: "9em",
  });

  const { getSetting } = useTenant();
  const { articles: defaultTaxRateArticles } = useDefaultTaxRates();

  const used_tiers_for_offers = getSetting("used_tiers_for_offers") as
    | number[]
    | undefined;
  // Single-tier mode when the tenant hasn't configured tier thresholds:
  // one column per unit using ``price_1`` only. No silent default to
  // [1, 3, 5] — that bumped non-tier tenants into multi-tier pricing.
  // ``useMemo`` so the fallback ``[1]`` has a stable identity across
  // renders — otherwise the columns ``useMemo`` below re-fires every render.
  const tiersList = useMemo<number[]>(
    () =>
      used_tiers_for_offers && used_tiers_for_offers.length > 0
        ? used_tiers_for_offers
        : [1],
    [used_tiers_for_offers],
  );

  const columns = useMemo<EditableColumnConfig[]>(() => {
    const tiers: Array<{ tier: number; idx: 1 | 2 | 3 }> = tiersList.map(
      (tier, i) => ({ tier, idx: (i + 1) as 1 | 2 | 3 }),
    );

    const boxChildren = UNITS.map((unit, i) =>
      buildCurrencyPriceColumn({
        title: <>{t(`commissioning.box_price_${unit}`, { currencySymbol })}</>,
        dataIndex: `net_price_for_boxes_${unit}`,
        currencySymbol,
        className: i === 0 ? "column-group-start" : undefined,
        locale,
      }),
    );

    const resellerChildren: EditableColumnConfig[] = [];
    for (const unit of UNITS) {
      tiers.forEach(({ tier, idx }, tierIndex) => {
        resellerChildren.push(
          buildCurrencyPriceColumn({
            title: (
              <span className="text-preline">
                {t(`commissioning.reseller_${unit}_tier${idx}`, {
                  tier,
                  currencySymbol,
                })}
              </span>
            ),
            dataIndex: `net_price_for_orders_${unit}_${idx}`,
            currencySymbol,
            // First column of each unit block gets the group-start marker
            // to mirror the original visual grouping.
            className: tierIndex === 0 ? "column-group-start" : undefined,
            locale,
          }),
        );
      });
    }

    return [
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
      buildTaxRateColumn(t, { locale }),
      {
        title: t("commissioning.for_shares"),
        key: "for_shares",
        dataIndex: "for_shares",
        className: "column-group-start",
        children: boxChildren,
      },
      {
        title: t("commissioning.for_resellers"),
        key: "for_resellers",
        dataIndex: "for_resellers",
        className: "column-group-start",
        children: resellerChildren,
      },
    ] as EditableColumnConfig[];
  }, [
    t,
    currencySymbol,
    locale,
    tiersList,
    activeStatusColumn,
    validFromColumn,
    validUntilColumn,
  ]);

  return (
    <PriceEditorModal<ShareArticleNetPrice, ShareArticleNetPrice>
      visible={visible}
      onClose={onClose}
      title={
        <div>
          {t("commissioning.prices_for_article")}
          {share_article_name}
        </div>
      }
      width="65%"
      fkField="share_article"
      fkValue={share_article}
      defaultTaxRate={defaultTaxRateArticles}
      columns={columns}
      listHook={useCommissioningShareArticleNetPricesList}
      getListQueryKey={getCommissioningShareArticleNetPricesListQueryKey}
      api={{
        create: commissioningShareArticleNetPricesCreate,
        partialUpdate: commissioningShareArticleNetPricesPartialUpdate,
        destroy: commissioningShareArticleNetPricesDestroy,
      }}
    />
  );
}
