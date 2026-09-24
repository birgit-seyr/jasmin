import { BarChartOutlined, UserOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import SidebarShell from "./SidebarShell";

interface WarehouseSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function WarehouseSidebar({
  openKeys,
  onOpenChange,
}: WarehouseSidebarProps) {
  const { t } = useTranslation();

  const items = [
    {
      key: "warehouse-fertilizer",
      icon: <UserOutlined />,
      label: t("warehouse.fertilizer"),
    },
    {
      key: "warehouse-pesticides",
      icon: <BarChartOutlined />,
      label: t("warehouse.pesticides"),
    },
    {
      key: "warehouse-tools",
      icon: <BarChartOutlined />,
      label: t("warehouse.tools"),
    },
    {
      key: "warehouse-others",
      icon: <BarChartOutlined />,
      label: t("warehouse.others"),
    },
  ];

  return (
    <SidebarShell
      header={t("nav.warehouse")}
      items={items}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
