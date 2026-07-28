import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationSeedlingsVendorsCreate,
  cultivationSeedlingsVendorsDestroy,
  cultivationSeedlingsVendorsPartialUpdate,
  getCultivationSeedlingsVendorsListQueryKey,
  useCultivationSeedlingsVendorsList,
} from "@shared/api/generated/cultivation/cultivation";
import type { SeedlingsVendor } from "@shared/api/generated/models";
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

type SeedlingsVendorRow = SeedlingsVendor & TableRecord;

const seedlingsVendorsResource: CrudResource<SeedlingsVendorRow> = {
  useList: useCultivationSeedlingsVendorsList,
  create: cultivationSeedlingsVendorsCreate,
  update: cultivationSeedlingsVendorsPartialUpdate,
  delete: cultivationSeedlingsVendorsDestroy,
  getListQueryKey: getCultivationSeedlingsVendorsListQueryKey,
};

export default function ListSeedlingsVendors() {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<SeedlingsVendorRow>[]>(
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
    <CrudListPage<SeedlingsVendorRow>
      titleKey="cultivation.list_seedlings_vendors"
      descriptionKey="cultivation.seedlings_vendors_description"
      explainerKey="explainers.list_seedlings_vendors"
      resource={seedlingsVendorsResource}
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
