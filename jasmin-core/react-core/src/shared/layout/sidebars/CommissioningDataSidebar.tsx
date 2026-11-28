import { filterByRole, useRoles } from "@shared/auth";
import { useTranslation } from "react-i18next";
import SidebarShell from "./SidebarShell";
import { useCommissioningDataNavItems } from "./useCommissioningDataNavItems";

interface CommissioningDataSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

/**
 * Commissioning's data lists as a section of their own, where the
 * configuration isn't a section of the navigation (``configuration_section``);
 * elsewhere they are a group of the commissioning sidebar.
 */
export default function CommissioningDataSidebar({
  openKeys = [],
  onOpenChange,
}: CommissioningDataSidebarProps) {
  const { t } = useTranslation();
  const flags = useRoles();
  const items = useCommissioningDataNavItems();

  return (
    <SidebarShell
      header={t("commissioning.data")}
      items={filterByRole(items, flags)}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
