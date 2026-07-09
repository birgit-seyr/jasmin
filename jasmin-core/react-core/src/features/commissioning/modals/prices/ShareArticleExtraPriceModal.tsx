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
  useTimeBoundColumns,
} from "@hooks/index";
import { useOfferTiers } from "@features/commissioning/hooks";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import PriceEditorModal from "./PriceEditorModal";
import { buildCurrencyPriceColumn, buildTaxRateColumn } from "./priceColumns";

interface ShareArticleExtraPriceModalProps {
  visible: boolean;
  onClose: () => void;
  share_article: string | null;
  share_article_name: string;
  onSave?: () => void;
}

/**
 * Price modal for "extra" share articles (``ShareArticle.is_extra=True``).
 *
 * Extras are constrained to ``PCS`` so we only expose the three pieces
 * reseller-tier prices, mirroring the simple structure of the legacy
 * ``ExtraArticlePriceModal`` but backed by ``ShareArticleNetPrice``.
 */
export default function ShareArticleExtraPriceModal({
  visible,
  onClose,
  share_article,
  share_article_name,
}: ShareArticleExtraPriceModalProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { locale } = useNumberFormat();
  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    width: "9em",
  });

  const { articles: defaultTaxRateArticles } = useDefaultTaxRates();

  // Single-tier mode when the tenant hasn't configured tier thresholds:
  // one price column using ``price_1`` only. No silent default to
  // [1, 3, 5] — that bumped non-tier tenants into multi-tier pricing.
  const tiersList = useOfferTiers();

  const columns = useMemo<EditableColumnConfig[]>(
    () =>
      [
        activeStatusColumn,
        validFromColumn,
        validUntilColumn,
        ...tiersList.map((tier, i) =>
          buildCurrencyPriceColumn({
            title: (
              <span className="text-preline">
                {t(`commissioning.reseller_pieces_tier${i + 1}`, {
                  tier,
                  currencySymbol,
                })}
              </span>
            ),
            dataIndex: `net_price_for_orders_pieces_${i + 1}`,
            currencySymbol,
            width: "9em",
            locale,
          }),
        ),
        buildTaxRateColumn(t, { locale }),
      ] as EditableColumnConfig[],
    [
      t,
      currencySymbol,
      locale,
      tiersList,
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
    ],
  );

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
      width="50%"
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
