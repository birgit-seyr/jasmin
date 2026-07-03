import { useTranslation } from "react-i18next";
import { ROLES, type Role } from "./roles";

/** Returns the full role list with translated labels. */
export function useRoleOptions(): { label: string; value: Role }[] {
  const { t } = useTranslation();
  return [
    { label: t("users.role_admin"), value: ROLES.ADMIN },
    { label: t("users.role_management"), value: ROLES.MANAGEMENT },
    { label: t("users.role_office"), value: ROLES.OFFICE },
    { label: t("users.role_staff"), value: ROLES.STAFF },
    { label: t("users.role_gardener"), value: ROLES.GARDENER },
    { label: t("users.role_member"), value: ROLES.MEMBER },
    { label: t("users.role_customer"), value: ROLES.CUSTOMER },
  ];
}
