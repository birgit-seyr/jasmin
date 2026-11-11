import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningMarketProductGroupsCreate,
  commissioningMarketProductGroupsDestroy,
  commissioningMarketProductGroupsPartialUpdate,
  getCommissioningMarketProductGroupsListQueryKey,
  useCommissioningMarketProductGroupsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { MarketProductGroup } from "@shared/api/generated/models";
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
import { useIsActiveColumn } from "@features/commissioning/hooks";

type MarketProductGroupRow = MarketProductGroup & TableRecord;

const marketProductGroupsResource: CrudResource<MarketProductGroupRow> = {
  useList: useCommissioningMarketProductGroupsList,
  create: commissioningMarketProductGroupsCreate,
  update: commissioningMarketProductGroupsPartialUpdate,
  delete: commissioningMarketProductGroupsDestroy,
  getListQueryKey: getCommissioningMarketProductGroupsListQueryKey,
};

export default function ListMarketProductGroups() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const columns = useMemo<EditableColumnConfig<MarketProductGroupRow>[]>(
    () => [
      isActiveColumn,
      {
        title: "#",
        dataIndex: "number",
        key: "number",
        inputType: "positive_integer",
        required: true,
        width: "5em",
        align: "right",
        sortable: true,
      },
      {
        title: <>{t("commissioning.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "18em",
        align: "left",
        sortable: true,
      },
    ],
    [isActiveColumn, t],
  );

  return (
    <CrudListPage<MarketProductGroupRow>
      titleKey="commissioning.list_market_product_groups"
      explainerKey="explainers.list_market_product_groups"
      resource={marketProductGroupsResource}
      permissions={permissions}
      columns={columns}
      focusIndex="number"
      uniqueCheck={["number"]}
      uniqueCheckMessage={t("validation.unique.number")}
      className="w-max custom-jasmin-table"
    />
  );
}
