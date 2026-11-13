import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningMarketArticlesCreate,
  commissioningMarketArticlesDestroy,
  commissioningMarketArticlesPartialUpdate,
  getCommissioningMarketArticlesListQueryKey,
  useCommissioningMarketArticlesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { MarketArticle } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  useAmountUnitSizeColumns,
  useIsActiveColumn,
  useMarketProductGroups,
  useScaleTaxCodes,
  useShareArticleColumn,
} from "@features/commissioning/hooks";

type MarketArticleRow = MarketArticle & TableRecord;

const marketArticlesResource: CrudResource<MarketArticleRow> = {
  useList: useCommissioningMarketArticlesList,
  create: commissioningMarketArticlesCreate,
  update: commissioningMarketArticlesPartialUpdate,
  delete: commissioningMarketArticlesDestroy,
  getListQueryKey: getCommissioningMarketArticlesListQueryKey,
};

// Module-level, so the hooks below get the same objects on every render.
const ACTIVE_ARTICLES = { is_active: true };
// Bought-in market goods have no share article.
const OPTIONAL_ARTICLE = { required: false };
const NEW_ROW_DEFAULTS: Record<string, unknown> = {
  is_active: true,
  size: "M",
  allows_price_override: true,
  allows_discount_price: true,
};

export default function ListMarketArticles() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const { shareArticleColumn } = useShareArticleColumn({
    filters: ACTIVE_ARTICLES,
    overrides: OPTIONAL_ARTICLE,
  });
  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
  });
  const { productGroups } = useMarketProductGroups();
  const { scaleTaxCodes } = useScaleTaxCodes();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const columns = useMemo<EditableColumnConfig<MarketArticleRow>[]>(
    () => [
      isActiveColumn,
      {
        title: <>{t("commissioning.plu_number")}</>,
        dataIndex: "plu_number",
        key: "plu_number",
        inputType: "positive_integer",
        required: true,
        width: "6em",
        align: "right",
        sortable: true,
      },
      {
        title: <>{t("commissioning.market_label")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "16em",
        align: "left",
        fixed: true,
        sortable: true,
      },
      ...amountUnitSizeColumns,
      {
        title: <>{t("commissioning.sort")}</>,
        dataIndex: "sort",
        key: "sort",
        inputType: "text",
        required: false,
        width: "10em",
        align: "left",
      },
      {
        ...shareArticleColumn,
        title: <>{t("commissioning.market_linked_share_article")}</>,
        // The scale's name stays in view instead.
        fixed: false,
      },
      {
        title: <>{t("commissioning.market_product_group")}</>,
        dataIndex: "product_group_name",
        key: "product_group_name",
        inputType: "select",
        required: false,
        align: "left",
        width: "12em",
        options: productGroups,
        foreignKey: {
          valueField: "product_group",
          displayField: "product_group_name",
        },
        sortable: true,
      },
      {
        // Left empty, the server picks the code; the label comes from the
        // options, so it needs a name apart from the id's.
        title: <>{t("commissioning.scale_tax_code")}</>,
        dataIndex: "scale_tax_code_label",
        key: "scale_tax_code_label",
        inputType: "select",
        required: false,
        align: "left",
        width: "9em",
        options: scaleTaxCodes,
        foreignKey: {
          valueField: "scale_tax_code",
          displayField: "scale_tax_code_label",
        },
      },
      {
        title: <>{t("commissioning.allows_price_override")}</>,
        dataIndex: "allows_price_override",
        key: "allows_price_override",
        inputType: "checkbox",
        required: false,
      },
      {
        title: <>{t("commissioning.allows_discount_price")}</>,
        dataIndex: "allows_discount_price",
        key: "allows_discount_price",
        inputType: "checkbox",
        required: false,
      },
    ],
    [
      isActiveColumn,
      shareArticleColumn,
      amountUnitSizeColumns,
      productGroups,
      scaleTaxCodes,
      t,
    ],
  );

  return (
    <CrudListPage<MarketArticleRow>
      titleKey="commissioning.list_market_articles"
      explainerKey="explainers.list_market_articles"
      resource={marketArticlesResource}
      permissions={permissions}
      columns={columns}
      newRowDefaults={NEW_ROW_DEFAULTS}
      focusIndex="plu_number"
      uniqueCheck={["plu_number"]}
      uniqueCheckMessage={t("validation.unique.plu_number")}
      className="w-max custom-jasmin-table"
    />
  );
}
