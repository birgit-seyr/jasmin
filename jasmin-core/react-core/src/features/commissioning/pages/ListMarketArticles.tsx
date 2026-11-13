import { useQueryClient } from "@tanstack/react-query";
import { Flex } from "antd";
import { useCallback, useMemo, useState } from "react";
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
  EditableTable,
  type CrudResource,
  permissionsWithDeletable,
  useCrudListPage,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import {
  useAmountUnitSizeColumns,
  useIsActiveColumn,
  useMarketProductGroups,
  useScaleTaxCodes,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import { MarketProductGroupSelector } from "@features/commissioning/selectors";

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
  const [productGroup, setProductGroup] = useState<string | null>(null);
  // A new PLU goes into the group the list shows, so it stays in view once
  // saved. The group select's form field holds the group's id under its
  // display field; the save sends it as ``product_group``.
  const newRowDefaults = useMemo(
    () =>
      productGroup
        ? { ...NEW_ROW_DEFAULTS, product_group_name: productGroup }
        : NEW_ROW_DEFAULTS,
    [productGroup],
  );
  const list = useCrudListPage<MarketArticleRow>({
    resource: marketArticlesResource,
    permissions,
    newRowDefaults,
  });
  const rows = useMemo(
    () =>
      productGroup
        ? list.filteredData.filter((plu) => plu.product_group === productGroup)
        : list.filteredData,
    [list.filteredData, productGroup],
  );
  // A save doesn't refetch the list, but the group filter reads it: a new PLU
  // is fetched into it and an updated one written into it, so each shows
  // under its own group only.
  const queryClient = useQueryClient();
  const { onSaveSuccess, invalidate } = list;
  const handleSaveSuccess = useCallback(
    (saved: MarketArticleRow, action: "create" | "update") => {
      if (action === "create") {
        invalidate();
      } else {
        queryClient.setQueriesData<MarketArticle[]>(
          { queryKey: getCommissioningMarketArticlesListQueryKey() },
          (cached) =>
            cached?.map((plu) => (plu.id === saved.id ? { ...plu, ...saved } : plu)),
        );
      }
      onSaveSuccess?.(saved, action);
    },
    [queryClient, invalidate, onSaveSuccess],
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
    <div>
      <h1>{t("commissioning.list_market_articles")}</h1>
      <Flex align="center" gap={16}>
        <MarketProductGroupSelector
          selectedProductGroup={productGroup}
          setSelectedProductGroup={setProductGroup}
        />
        <HideInactiveSwitch
          value={list.hideInactive}
          onChange={list.setHideInactive}
        />
      </Flex>
      <EditableTable<MarketArticleRow>
        // One table per group: the table keeps a row saved on this mount
        // pinned, whatever its rows become.
        key={productGroup ?? "all"}
        columns={columns}
        apiFunctions={list.apiFunctions}
        initialData={rows}
        loading={list.isLoading}
        onSaveSuccess={handleSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customEdit={list.customEdit}
        permissions={list.permissions}
        uniqueCheck={["plu_number"]}
        uniqueCheckMessage={t("validation.unique.plu_number")}
        uniqueCheckRows={list.data}
        focusIndex="plu_number"
        pagination={true}
        className="w-max custom-jasmin-table"
        keyboardAddShortcut={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_market_articles")}
      </ExplainerText>
    </div>
  );
}
