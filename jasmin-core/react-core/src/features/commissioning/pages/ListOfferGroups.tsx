import { LockOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningOfferGroupsCreate,
  commissioningOfferGroupsDestroy,
  commissioningOfferGroupsPartialUpdate,
  useCommissioningOfferGroupsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { OfferGroup } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import { useInvalidateAfterTableMutation } from "@hooks/index";
import {
  useIsActiveColumn,
  useOfferTiers,
} from "@features/commissioning/hooks";

export default function ListOfferGroups() {
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const [hideInactive, setHideInactive] = useState(true);
  const { t } = useTranslation();
  const isActiveColumn = useIsActiveColumn();
  // Same tier source as the offers price columns (useOfferTiers), so these
  // tier-rabatt columns always match the tiers the tenant actually has.
  const finalTiers = useOfferTiers();

  // React Query handles the initial load + caching. Saves do NOT
  // refetch (EditableTable's local state is authoritative — see
  // ``useInvalidateAfterTableMutation``); deletes do, so the row
  // disappears from any downstream cached view.
  const {
    data: offerGroupsData,
    refetch,
    isLoading,
  } = useCommissioningOfferGroupsList();
  const data = useMemo<TableRecord[]>(
    () => (offerGroupsData ?? []) as unknown as TableRecord[],
    [offerGroupsData],
  );

  const invalidateData = useCallback(() => {
    void refetch();
  }, [refetch]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<OfferGroup & TableRecord>({
        create: (payload) => commissioningOfferGroupsCreate(payload),
        update: (id, payload) =>
          commissioningOfferGroupsPartialUpdate(id, payload),
        delete: (id) => commissioningOfferGroupsDestroy(id),
      }),
    [],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { is_active: true };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    return {
      ...transformedData,
      valid_from: dayjs().format("YYYY-MM-DD"),
    };
  }, []);

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
        // The seeded default group can't be deleted (its delete icon is
        // hidden via can_be_deleted) — flag it so the office knows why.
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
      // One rabatt column per active tier beyond the first (the base price
      // has no rabatt). The model carries tier 2 + 3, so cap at the 2nd/3rd
      // tier; each is labelled by its threshold, matching the offers' tiers.
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
          // suffix shows "%" in the edit input; render shows it in the cell.
          render: (value: unknown) => (value ? `${value} %` : ""),
        };
      }),
    ],
    [isActiveColumn, t, finalTiers],
  );

  const visibleData = useMemo<TableRecord[]>(
    () => (hideInactive ? data.filter((r) => r.is_active) : data),
    [hideInactive, data],
  );

  return (
    <div>
      <h1>{t("commissioning.list_offer_groups")}</h1>

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="number"
        initialData={visibleData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        className="w-max custom-jasmin-table"
        deleteContext={"resellers"}
        uniqueCheck={["number"]}
        uniqueCheckMessage={t("validation.unique.number")}
        permissions={permissions}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_offer_groups")}
      </ExplainerText>
    </div>
  );
}
