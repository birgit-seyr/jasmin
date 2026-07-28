import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationSeedsVendorsCreate,
  cultivationSeedsVendorsDestroy,
  cultivationSeedsVendorsPartialUpdate,
  getCultivationSeedsVendorsListQueryKey,
  useCultivationSeedsVendorsList,
} from "@shared/api/generated/cultivation/cultivation";
import type { SeedsVendor } from "@shared/api/generated/models";
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

type SeedsVendorRow = SeedsVendor & TableRecord;

const seedsVendorsResource: CrudResource<SeedsVendorRow> = {
  useList: useCultivationSeedsVendorsList,
  create: cultivationSeedsVendorsCreate,
  update: cultivationSeedsVendorsPartialUpdate,
  delete: cultivationSeedsVendorsDestroy,
  getListQueryKey: getCultivationSeedsVendorsListQueryKey,
};

export default function ListSeedsVendors() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<SeedsVendorRow>[]>(
    () => [
      {
        title: <>{t("cultivation.vendor_name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "18em",
        align: "left",
      },
      {
        title: <>{t("cultivation.vendor_email")}</>,
        dataIndex: "email",
        key: "email",
        inputType: "text",
        required: false,
        width: "18em",
        align: "left",
      },
    ],
    [t],
  );

  return (
    <CrudListPage<SeedsVendorRow>
      titleKey="cultivation.list_seeds_vendors"
      descriptionKey="cultivation.seeds_vendors_description"
      explainerKey="explainers.list_seeds_vendors"
      resource={seedsVendorsResource}
      permissions={permissions}
      withHideInactive={false}
      columns={columns}
      uniqueCheck={["name"]}
      uniqueCheckMessage={t("validation.unique.name")}
      focusIndex="name"
      className="w-max custom-jasmin-table"
    />
  );
}
