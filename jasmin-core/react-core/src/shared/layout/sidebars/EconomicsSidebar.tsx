import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { filterByRole, useRoles, type RoleGatedItem } from "@shared/auth";
import SidebarShell from "./SidebarShell";

interface EconomicsSidebarProps {
  collapsed?: boolean;
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function EconomicsSidebar({
  openKeys,
  onOpenChange,
}: EconomicsSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();

  const items = [
    {
      key: "economics-key_data",

      requireRole: "isManagement",
      label: <Link to="/economics/key_data">{t("economics.key_data")}</Link>,
    },
    {
      key: "economics-businessplan",

      requireRole: "isManagement",
      label: (
        <Link to="/economics/businessplan">{t("economics.businessplan")}</Link>
      ),
    },
    {
      key: "budgets",

      requireRole: "isManagement",
      label: <Link to="/economics/budgets">{t("economics.budgets")}</Link>,
    },
    {
      key: "upload_data",

      requireRole: "isManagement",
      label: (
        <Link to="/economics/upload_data">{t("economics.upload_data")}</Link>
      ),
    },
  ];

  return (
    <SidebarShell
      header={t("nav.economics")}
      items={filterByRole(items as unknown as RoleGatedItem[], flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
