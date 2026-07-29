import { Suspense, lazy, useState } from "react";
import type { ComponentType, LazyExoticComponent } from "react";
import { useTranslation } from "react-i18next";
import { useLocale } from "@shared/contexts/LocalContext";
import { useNavigation } from "@shared/contexts/NavigationContext";
import { useIsMobile } from "@hooks/index";

// Lazy load sidebar components - only load when needed
const CommissioningSidebar = lazy(
  () => import("./sidebars/CommissioningSidebar"),
);
const CultivationSidebar = lazy(
  () => import("./sidebars/CultivationSidebar"),
);
const ConfigurationSidebar = lazy(
  () => import("./sidebars/ConfigurationSidebar"),
);
const EconomicsSidebar = lazy(() => import("./sidebars/EconomicsSidebar"));
const MembersSidebar = lazy(() => import("./sidebars/MembersSidebar"));
const ExportSidebar = lazy(() => import("./sidebars/ExportSidebar"));
const StaffSidebar = lazy(() => import("./sidebars/StaffSidebar"));
const WarehouseSidebar = lazy(() => import("./sidebars/WarehouseSidebar"));
const AboSidebar = lazy(() => import("./sidebars/AboSidebar"));
const MobileSidebar = lazy(() => import("./sidebars/MobileSidebar"));

export default function DynamicSidebar() {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { activeSection, NAVIGATION_SECTIONS } = useNavigation();
  const { sidebarCollapsed } = useLocale();
  const [isHovered, setIsHovered] = useState(false);

  // Add submenu state management here
  const [openKeys, setOpenKeys] = useState<string[]>([]);

  // SidebarShell resolves the open set (it knows the menu tree, so it can keep
  // a nested submenu's ancestors open while still collapsing sibling top-level
  // groups). We just store what it computes.
  const handleOpenChange = (keys: string[]) => {
    setOpenKeys(keys);
  };

  // If mobile, only return the single MobileSidebar
  if (isMobile) {
    return (
      <Suspense
        fallback={
          <div className="sidebar-loading">{t("common.loading_sidebar")}</div>
        }
      >
        <MobileSidebar />
      </Suspense>
    );
  }


  // Desktop sidebar logic
  const desktopSidebarMap: Record<string, LazyExoticComponent<ComponentType<{ openKeys?: string[]; onOpenChange?: (keys: string[]) => void }>>> = {
    [NAVIGATION_SECTIONS.MEMBERS]: MembersSidebar,
    [NAVIGATION_SECTIONS.ABOS]: AboSidebar,
    [NAVIGATION_SECTIONS.COMMISSIONING]: CommissioningSidebar,
    [NAVIGATION_SECTIONS.STAFF]: StaffSidebar,
    [NAVIGATION_SECTIONS.WAREHOUSE]: WarehouseSidebar,
    [NAVIGATION_SECTIONS.ECONOMICS]: EconomicsSidebar,
    [NAVIGATION_SECTIONS.CULTIVATION]: CultivationSidebar,
    [NAVIGATION_SECTIONS.EXPORTS]: ExportSidebar,
    [NAVIGATION_SECTIONS.CONFIGURATION]: ConfigurationSidebar,
  };

  const shouldShowCollapsed = sidebarCollapsed && !isHovered;

  const SidebarComponent = desktopSidebarMap[activeSection];

  return SidebarComponent ? (
    // Mouse-only hover affordance (expand-on-hover when collapsed) — a pointer
    // enhancement; the collapsed sidebar is fully usable and its nav links are
    // keyboard-reachable, so no keyboard handler is owed here.
    <div
      className={`sidebar-container ${
        shouldShowCollapsed ? "collapsed" : "expanded"
      }`}
      onMouseEnter={() => sidebarCollapsed && setIsHovered(true)}
      onMouseLeave={() => sidebarCollapsed && setIsHovered(false)}
    >
      <Suspense
        fallback={
          <div className="sidebar-loading">{t("common.loading_sidebar")}</div>
        }
      >
        <SidebarComponent
          openKeys={openKeys}
          onOpenChange={handleOpenChange}
        />
      </Suspense>
    </div>
  ) : null;
}
