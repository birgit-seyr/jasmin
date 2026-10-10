import { MenuOutlined } from "@ant-design/icons";
import { Drawer, Menu } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { usePackingListVisibility } from "./usePackingListVisibility";

export default function MobileSidebar() {
  const [visible, setVisible] = useState(false);
  const { t } = useTranslation();
  const { showBoxesPackingList } = usePackingListVisibility();

  const menuItemsCommissioning = [
    {
      key: "commissioning-forecast",
      label: (
        <Link to="/commissioning/forecast">{t("commissioning.forecast")}</Link>
      ),
    },

    {
      key: "commissioning-documentation-current-stock",
      label: (
        <Link to="/commissioning/documentation-current-stock">
          {t("commissioning.documentation_amounts")}
        </Link>
      ),
    },

    {
      key: "commissioning-documentation-harvest",
      label: (
        <Link to="/commissioning/documentation-harvest">
          {t("commissioning.documentation_harvest")}
        </Link>
      ),
    },

    {
      key: "commissioning-washing-list",
      label: (
        <Link to="/commissioning/washing-list">
          {t("commissioning.washing_list")}
        </Link>
      ),
    },
    {
      key: "commissioning-harvesting-lists",
      label: (
        <Link to="/commissioning/harvesting-list">
          {t("commissioning.harvesting_lists")}
        </Link>
      ),
    },
    // Box packing only, as in the desktop sidebar.
    ...(showBoxesPackingList
      ? [
          {
            key: "commissioning-packing-lists",
            label: (
              <Link to="/commissioning/packing-list-boxes">
                {t("commissioning.packing_lists")}
              </Link>
            ),
          },
          {
            key: "commissioning-commissioning-list-packing",
            label: (
              <Link to="/commissioning/commissioning-list-packing">
                {t("commissioning.commissioning_list_packing")}
              </Link>
            ),
          },
        ]
      : []),
    {
      key: "commissioning-commissioning-list-resellers",
      label: (
        <Link to="/commissioning/commissioning-list-resellers">
          {t("commissioning.commissioning_list_resellers_short")}
        </Link>
      ),
    },
  ];

  return (
    <>
      {/* Hamburger menu trigger */}
      <div
        role="button"
        tabIndex={0}
        aria-label={t("nav.open_menu")}
        style={{
          position: "fixed",
          top: "10px",
          left: "10px",
          zIndex: 1000,
          cursor: "pointer",
          padding: "4px",
          backgroundColor: "var(--color-bg-base)",
          borderRadius: "4px",
          boxShadow: "0 2px 8px var(--color-shadow)",
        }}
        onClick={() => setVisible(true)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setVisible(true); } }}
      >
        <MenuOutlined style={{ fontSize: "30px" }} />
      </div>

      {/* Sidebar drawer */}
      <Drawer
        title={t("nav.navigation")}
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
      </Drawer>
    </>
  );
}
