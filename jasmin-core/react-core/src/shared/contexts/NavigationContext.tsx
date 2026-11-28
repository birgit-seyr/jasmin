import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
} from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { useLocation } from "react-router-dom";
import { useCapability } from "@shared/hooks/configuration/useCapability";
import { isCommissioningDataPath } from "@shared/layout/sidebars/commissioningDataPaths";

const NAVIGATION_SECTIONS = {
  MEMBERS: "members",
  ABOS: "abos",
  COMMISSIONING: "commissioning",
  // Commissioning's data lists, a section of their own only where the
  // configuration isn't one (``configuration_section``).
  COMMISSIONING_DATA: "commissioning-data",
  STAFF: "staff",
  WAREHOUSE: "warehouse",
  ECONOMICS: "economics",
  CULTIVATION: "cultivation",
  EXPORTS: "exports",
  CONFIGURATION: "configuration",
  MY_MEMBER_PAGE: "my-member-page",
  MY_STAFF_PAGE: "my-staff-page",
} as const;

type NavigationSection =
  (typeof NAVIGATION_SECTIONS)[keyof typeof NAVIGATION_SECTIONS];

interface NavigationContextValue {
  activeSection: NavigationSection;
  activeSidebarItem: string | null;
  setActiveSidebarItem: Dispatch<SetStateAction<string | null>>;
  switchSection: (section: NavigationSection) => void;
  NAVIGATION_SECTIONS: typeof NAVIGATION_SECTIONS;
}

const NavigationContext = createContext<NavigationContextValue | undefined>(
  undefined,
);

/* eslint-disable-next-line react-refresh/only-export-components --
   the hook is the only way into the private context above */
export function useNavigation() {
  const context = useContext(NavigationContext);
  if (!context) {
    throw new Error("useNavigation must be used within NavigationProvider");
  }
  return context;
}

export function NavigationProvider({
  children,
}: {
  children: ReactNode;
}) {
  const getInitialSection = (): NavigationSection => {
    const path = window.location.pathname;
    // Map URL paths to navigation sections. The configuration comes first:
    // some of its addresses name another section (/configuration/members).
    if (path.includes("/configuration"))
      return NAVIGATION_SECTIONS.CONFIGURATION;
    if (path.includes("/members")) return NAVIGATION_SECTIONS.MEMBERS;
    if (path.includes("/abos")) return NAVIGATION_SECTIONS.ABOS;
    if (path.includes("/staff")) return NAVIGATION_SECTIONS.STAFF;
    if (path.includes("/warehouse")) return NAVIGATION_SECTIONS.WAREHOUSE;
    if (path.includes("/economics")) return NAVIGATION_SECTIONS.ECONOMICS;
    if (path.includes("/cultivation")) return NAVIGATION_SECTIONS.CULTIVATION;
    if (path.includes("/exports")) return NAVIGATION_SECTIONS.EXPORTS;
    return NAVIGATION_SECTIONS.COMMISSIONING; // fallback
  };

  const [activeSection, setActiveSection] =
    useState<NavigationSection>(getInitialSection());
  const [activeSidebarItem, setActiveSidebarItem] = useState<string | null>(
    null,
  );

  const switchSection = useCallback((section: NavigationSection) => {
    setActiveSection(section);
    setActiveSidebarItem(null); // Reset sidebar selection when switching sections
  }, []);

  // Commissioning and the configuration never show each other's pages: a
  // link out of the configuration, the browser's back button after it, or an
  // old configuration address that forwards to a data list lands in
  // commissioning, and a link from commissioning to a configuration page (a
  // banner's, say) lands in the configuration. The data lists live under
  // /commissioning, so where they are a section of their own the section
  // follows the page between the two: a reload or a link onto a data list
  // lands in the data section, and one back out of it in commissioning. The
  // capability is known only once the tenant has loaded, which is why this is
  // an effect and not the initial section.
  const dataHasOwnSection = !useCapability("configuration_section");
  const { pathname } = useLocation();
  useEffect(() => {
    const onCommissioningPage = pathname.startsWith("/commissioning");
    const onDataList = isCommissioningDataPath(pathname);
    const commissioningSectionHere =
      dataHasOwnSection && onDataList
        ? NAVIGATION_SECTIONS.COMMISSIONING_DATA
        : NAVIGATION_SECTIONS.COMMISSIONING;
    setActiveSection((section) => {
      if (section === NAVIGATION_SECTIONS.CONFIGURATION) {
        return onCommissioningPage ? commissioningSectionHere : section;
      }
      if (
        section !== NAVIGATION_SECTIONS.COMMISSIONING &&
        section !== NAVIGATION_SECTIONS.COMMISSIONING_DATA
      ) {
        return section;
      }
      if (onCommissioningPage) return commissioningSectionHere;
      if (pathname.startsWith("/configuration")) {
        return NAVIGATION_SECTIONS.CONFIGURATION;
      }
      return section;
    });
  }, [dataHasOwnSection, pathname]);

  // Memoized so consumers of useNavigation() don't re-render on every
  // NavigationProvider render — only when a value here actually changes.
  const value: NavigationContextValue = useMemo(
    () => ({
      activeSection,
      activeSidebarItem,
      setActiveSidebarItem,
      switchSection,
      NAVIGATION_SECTIONS,
    }),
    [activeSection, activeSidebarItem, switchSection],
  );

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  );
}
