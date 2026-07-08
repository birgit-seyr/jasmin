import { LockOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningOfferGroupsCreate,
  commissioningOfferGroupsDestroy,
  commissioningOfferGroupsPartialUpdate,
  getCommissioningOfferGroupsListQueryKey,
  useCommissioningOfferGroupsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { OfferGroup } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  CrudListPage,
  type CrudResource,
  permissionsWithDeletable,
} from "@shared/tables";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { useDateFormat } from "@hooks/index";
import { useIsActiveColumn, useOfferTiers } from "@features/commissioning/hooks";

type OfferGroupRow = OfferGroup & TableRecord;

const offerGroupsResource: CrudResource<OfferGroupRow> = {
  useList: useCommissioningOfferGroupsList,
  create: commissioningOfferGroupsCreate,
  update: commissioningOfferGroupsPartialUpdate,
  delete: commissioningOfferGroupsDestroy,
  getListQueryKey: getCommissioningOfferGroupsListQueryKey,
};

export default function ListOfferGroups() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { formatDateForAPI } = useDateFormat();
  const isActiveColumn = useIsActiveColumn();
  // Same tier source as the offers price columns, so these tier-rabatt columns
  // always match the tiers the tenant actually has.
  const finalTiers = useOfferTiers();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      valid_from: formatDateForAPI(dayjs()),
    }),
    [formatDateForAPI],
  );

  const columns = useMemo<any[]>(
    () => [
      isActiveColumn,
      {
        title: "#",
        dataIndex: "number",
        key: "number",
        inputType: "positive_integer",
        required: true,
        width: "4em",
        align: "left",
      },
      {
        title: <>{t("resellers.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: false,
        width: "16em",
        align: "left",
        // The seeded default group can't be deleted (its delete icon is hidden
        // via can_be_deleted) — flag it so the office knows why.
        render: (value: unknown, record: TableRecord) =>
          record.is_default ? (
            <span>
              {(value as string) ?? ""}{" "}
              <Tooltip title={t("commissioning.offer_group_default_hint")}>
                <LockOutlined className="text-muted" />
              </Tooltip>
            </span>
          ) : (
            ((value as string) ?? "")
          ),
      },
      // One rabatt column per active tier beyond the first (the base price has
      // no rabatt). The model carries tier 2 + 3, so cap at the 2nd/3rd tier.
      ...finalTiers.slice(1, 3).map((tierThreshold, index) => {
        const ordinal = index + 2;
        return {
          title: (
            <>{t("commissioning.rabatt_price_tier", { tier: tierThreshold })}</>
          ),
          dataIndex: `rabatt_price_tier_${ordinal}`,
          key: `rabatt_price_tier_${ordinal}`,
          inputType: "positive_integer",
          required: false,
          suffix: "%",
          width: "12em",
          align: "center",
          render: (value: unknown) => (value ? `${value} %` : ""),
        };
      }),
    ],
    [isActiveColumn, t, finalTiers],
  );

  return (
    <CrudListPage<OfferGroupRow>
      titleKey="commissioning.list_offer_groups"
      explainerKey="explainers.list_offer_groups"
      resource={offerGroupsResource}
      permissions={permissions}
      columns={columns}
      customSave={customSave}
      deleteContext="resellers"
      focusIndex="number"
      uniqueCheck={["number"]}
      uniqueCheckMessage={t("validation.unique.number")}
      className="w-max custom-jasmin-table"
    />
  );
}
