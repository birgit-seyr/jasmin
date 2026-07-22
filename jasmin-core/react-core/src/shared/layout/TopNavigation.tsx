import { Divider, Layout, Menu, Space } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useRoles, type RoleFlags } from "@shared/auth";
import { useNavigation } from "@shared/contexts/NavigationContext";
import { useIsMobile, useTenant } from "@hooks/index";
import HelpButton from "./HelpButton";
import ModalToggle from "./ModalToggle";
import SidebarToggle from "./SidebarToggle";
import UserMenu from "./UserMenu";

import { SettingOutlined, TeamOutlined, UserOutlined } from "@ant-design/icons";
import AgricultureIcon from "@mui/icons-material/Agriculture";
import AppsIcon from "@mui/icons-material/Apps";
import BarChartIcon from "@mui/icons-material/BarChart";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import GrassIcon from "@mui/icons-material/Grass";

const { Header } = Layout;

function PrimaryNavigation() {
  const { displayLogoUrl, tenantName } = useTenant();
  const { t } = useTranslation();
  const isMobile = useIsMobile();

  return (
    <Header
      className="flex-between"
      style={{
        background: "var(--color-bg-base)",
        height: isMobile ? "60px" : "100px",
        paddingLeft: isMobile ? "12px" : "24px",
        paddingRight: isMobile ? "12px" : "24px",
        paddingTop: isMobile ? "0px" : "10px",
        paddingBottom: "0px",
        borderTop: "solid 1px rgb(32, 95, 82)",
        borderBottom: "solid 1px rgb(32, 95, 82)",
        position: "relative",
      }}
    >
      <div
        className="logo"
        style={{
          display: "flex",
          alignItems: "center",
          position: "absolute",
          left: "50%",
          transform: "translateX(-50%)",
        }}
      >
        {displayLogoUrl && (
          <img
            src={displayLogoUrl}
            alt={tenantName ?? t("common.logo")}
            width={isMobile ? 160 : 200}
            height={isMobile ? 50 : 75}
            {...({ fetchpriority: "high" } as Record<string, string>)}
            style={{
              height: isMobile ? "50px" : "75px",
              width: "auto",
              objectFit: "contain",
            }}
          />
        )}
      </div>
      <div style={{ marginLeft: "auto" }} />
      <Space size={isMobile ? "small" : "middle"}>
        {!isMobile && <SidebarToggle />}
        {!isMobile && (
          <Divider
            type="vertical"
            style={{ height: "24px", margin: "0 0px" }}
          />
        )}
        {!isMobile && <ModalToggle />}
        {!isMobile && (
          <Divider
            type="vertical"
            style={{ height: "24px", margin: "0 0px" }}
          />
        )}
        <HelpButton />
        {!isMobile && (
          <Divider
            type="vertical"
            style={{ height: "24px", margin: "0 0px" }}
          />
        )}
        <UserMenu />
      </Space>
    </Header>
  );
}

function SecondaryNavigation() {
  const { activeSection, switchSection, NAVIGATION_SECTIONS } = useNavigation();
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const flags = useRoles();

  const navigationSettings = useMemo(
    () => ({
      members: getSetting("navigation.show_members", true),
      abos: getSetting("navigation.show_abos", true),
      commissioning: getSetting("navigation.show_commissioning", true),
      staff: getSetting("navigation.show_staff", true),
      warehouse: getSetting("navigation.show_warehouse", true),
      economics: getSetting("navigation.show_economics", true),
      cultivation: getSetting("navigation.show_cultivation", true),
      exports: getSetting("navigation.show_exports", true),
      configuration: getSetting("navigation.show_configuration", true),
    }),
    [getSetting],
  );

  const topMenuItems = useMemo(() => {
    const menuItemsConfig: Array<{
      key: string;
      icon: React.ReactNode;
      label: React.ReactNode;
      show: unknown;
      requireRole: keyof RoleFlags;
    }> = [
      {
        key: NAVIGATION_SECTIONS.COMMISSIONING,
        icon: <BubbleChartIcon />,
        label: (
          <Link to="/commissioning/dashboard">{t("nav.commissioning")}</Link>
        ),
        show: navigationSettings.commissioning,
        requireRole: "isStaff",
      },
      {
        key: NAVIGATION_SECTIONS.MEMBERS,
        icon: <UserOutlined />,
        label: <Link to="/members/dashboard">{t("nav.members")}</Link>,
        show: navigationSettings.members,
        requireRole: "isOffice",
      },
      {
        key: NAVIGATION_SECTIONS.ABOS,
        icon: <AppsIcon />,
        label: <Link to="/abos/dashboard">{t("nav.abos")}</Link>,
        show: navigationSettings.abos,
        requireRole: "isOffice",
      },

      {
        key: NAVIGATION_SECTIONS.STAFF,
        icon: <TeamOutlined />,
        label: <Link to="/staff/dashboard">{t("nav.staff")}</Link>,
        show: navigationSettings.staff,
        requireRole: "isOffice",
      },
      {
        key: NAVIGATION_SECTIONS.WAREHOUSE,
        icon: <AgricultureIcon />,
        label: <Link to="/warehouse/dashboard">{t("nav.warehouse")}</Link>,
        show: navigationSettings.warehouse,
        requireRole: "isStaff",
      },
      {
        key: NAVIGATION_SECTIONS.ECONOMICS,
        icon: <BarChartIcon />,
        label: <Link to="/economics/dashboard">{t("nav.economics")}</Link>,
        show: navigationSettings.economics,
        requireRole: "isManagement",
      },
      {
        key: NAVIGATION_SECTIONS.CULTIVATION,
        icon: <GrassIcon />,
        label: <Link to="/cultivation/dashboard">{t("nav.cultivation")}</Link>,
        show: navigationSettings.cultivation,
        requireRole: "isGardener",
      },
      {
        key: NAVIGATION_SECTIONS.CONFIGURATION,
        icon: <SettingOutlined />,
        label: (
          <Link to="/configuration/dashboard">{t("nav.configuration")}</Link>
        ),
        show: navigationSettings.configuration,
        requireRole: "isAdmin",
      },
    ];

    return menuItemsConfig
      .filter((item) => item.show && flags[item.requireRole])
      .map(({ show: _show, requireRole: _requireRole, ...item }) => item);
  }, [navigationSettings, t, flags, NAVIGATION_SECTIONS]);

  return (
    <Header
      className="flex-between"
      style={{
        padding: "0 24px",
        background: "var(--color-bg-base)",
        borderBottom: "solid 1px rgb(32, 95, 82)",
        overflow: "visible",
      }}
    >
      <div className="flex-1"></div> {/* Left spacer */}
      {/* Semantic landmark for the section navigation. display:contents so the
          <nav> generates no box — the Menu stays the flex child between the
          spacers and the layout is unchanged (A11Y-9). */}
      <nav aria-label={t("nav.main")} style={{ display: "contents" }}>
        <Menu
          mode="horizontal"
          selectedKeys={[activeSection]}
          items={topMenuItems}
          onSelect={({ key }) => switchSection(key as typeof activeSection)}
          style={{
            borderBottom: "none",
            minWidth: "max-content",
            whiteSpace: "nowrap",
          }}
        />
      </nav>
      <div className="flex-1"></div> {/* Right spacer */}
    </Header>
  );
}

export default function DoubleTopNavigation() {
  const isMobile = useIsMobile();
  return (
    <>
      <PrimaryNavigation />
      {!isMobile && <SecondaryNavigation />}
    </>
  );
}
