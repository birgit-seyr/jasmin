import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useLocale } from "@shared/contexts/LocalContext";
import { ToolTipIcon } from "../ui";

export default function SidebarToggle() {
  const { sidebarCollapsed, toggleSidebar } = useLocale();
  const { t } = useTranslation();

  return (
    <>
      <Button
        type="text"
        icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        onClick={toggleSidebar}
        style={{
          fontSize: "16px",
          width: 32,
          height: 32,
        }}
        title={sidebarCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
      />
      <ToolTipIcon title={t("tooltip.sidebar_collapse")} />
    </>
  );
}
