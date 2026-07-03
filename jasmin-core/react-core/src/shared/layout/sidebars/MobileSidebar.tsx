import { MenuOutlined } from "@ant-design/icons";
import { Drawer, Menu } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export default function MobileSidebar() {
  const [visible, setVisible] = useState(false);
  const { t } = useTranslation();

  const menuItemsCommissioning = [
    {
      key: "commissioning-forecast",
      label: (
        <Link to="/commissioning/forecast">{t("commissioning.forecast")}</Link>
      ),
      permission: "commissioning.view",
    },

    {
      key: "commissioning-documentation-current-stock",
      label: (
        <Link to="/commissioning/documentation-current-stock">
          {t("commissioning.documentation_amounts")}
        </Link>
      ),
      permission: "commissioning.view",
    },

    {
      key: "commissioning-documentation-harvest",
      label: (
        <Link to="/commissioning/documentation-harvest">
          {t("commissioning.documentation_harvest")}
        </Link>
      ),
      permission: "commissioning.view",
    },
    
    {
      key: "commissioning-washing-list",
      label: (
        <Link to="/commissioning/washing-list">
          {t("commissioning.washing_list")}
        </Link>
      ),
      permission: "commissioning.projects.view",
    },
    {
      key: "commissioning-harvesting-lists",
      label: (
        <Link to="/commissioning/harvesting-list">
          {t("commissioning.harvesting_lists")}
        </Link>
      ),
      permission: "commissioning.projects.view",
    },
    {
      key: "commissioning-packing-lists",
      label: (
        <Link to="/commissioning/packing-list-boxes">
          {t("commissioning.packing_lists")}
        </Link>
      ),
      permission: "commissioning.projects.view",
    },
    {
      key: "commissioning-commissioning-lists",
      label: (
        <Link to="/commissioning/commissioning-list">
          {t("commissioning.commissioning_lists")}
        </Link>
      ),
      permission: "commissioning.projects.view",
    },
  ];

  return (
    <>
      {/* Hamburger menu trigger */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Navigation"
        style={{
          position: "fixed",
          top: "10px",
          left: "10px",
          zIndex: 1000,
          cursor: "pointer",
          padding: "4px",
          backgroundColor: "var(--color-bg-base)",
          borderRadius: "4px",
          boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
        }}
        onClick={() => setVisible(true)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setVisible(true); } }}
      >
        <MenuOutlined style={{ fontSize: "30px" }} />
      </div>

      {/* Sidebar drawer */}
      <Drawer
        title="Navigation"
        placement="left"
        onClose={() => setVisible(false)}
        open={visible}
        width={250}
      >
        {" "}
        <div className="sidebar-header">{t("nav.commissioning")}</div>
        <Menu
          mode="vertical"
          items={menuItemsCommissioning}
          onClick={() => setVisible(false)}
        />
        <div className="sidebar-header">{t("nav.cultivation")}</div>
      </Drawer>
    </>
  );
}
