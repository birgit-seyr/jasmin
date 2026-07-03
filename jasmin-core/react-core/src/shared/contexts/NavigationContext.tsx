import { createContext, useContext, useState, useCallback, useMemo } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

const NAVIGATION_SECTIONS = {
  MEMBERS: "members",
  ABOS: "abos",
  COMMISSIONING: "commissioning",
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
    // Map URL paths to navigation sections
    if (path.includes("/members")) return NAVIGATION_SECTIONS.MEMBERS;
    if (path.includes("/abos")) return NAVIGATION_SECTIONS.ABOS;
    if (path.includes("/staff")) return NAVIGATION_SECTIONS.STAFF;
    if (path.includes("/warehouse")) return NAVIGATION_SECTIONS.WAREHOUSE;
    if (path.includes("/economics")) return NAVIGATION_SECTIONS.ECONOMICS;
    if (path.includes("/cultivation")) return NAVIGATION_SECTIONS.CULTIVATION;
    if (path.includes("/exports")) return NAVIGATION_SECTIONS.EXPORTS;
    if (path.includes("/configuration"))
      return NAVIGATION_SECTIONS.CONFIGURATION;
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
