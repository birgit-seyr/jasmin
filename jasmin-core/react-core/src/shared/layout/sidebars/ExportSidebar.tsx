import { DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import SidebarShell from "./SidebarShell";

interface ExportSidebarProps {
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

export default function ExportSidebar({
  openKeys,
  onOpenChange,
}: ExportSidebarProps) {
  const { t } = useTranslation();

  const items = [
    {
      key: "exports-members",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/members">{t("exports.members")}</Link>
        </div>
      ),
    },
    {
      key: "exports-commissioning",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/commissioning">{t("exports.commissioning")}</Link>
        </div>
      ),
    },
    {
      key: "exports-staff",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/staff">{t("exports.staff")}</Link>
        </div>
      ),
    },
    {
      key: "exports-warehouse",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/warehouse">{t("exports.warehouse")}</Link>
        </div>
      ),
    },
    {
      key: "exports-economics",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/economics">{t("exports.economics")}</Link>
        </div>
      ),
    },
    {
      key: "exports-cultivation",
      icon: <DownloadOutlined />,
      label: (
        <div className="sidebar-section-header">
          <Link to="/exports/cultivation">{t("exports.cultivation")}</Link>
        </div>
      ),
    },
  ];

  return (
    <SidebarShell
      header={t("nav.exports")}
      items={items}
      openKeys={openKeys}
      onOpenChange={onOpenChange}
    />
  );
}
