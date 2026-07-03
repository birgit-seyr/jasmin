import {
  createContext,
  useCallback,
  useState,
  useEffect,
  useMemo,
} from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { useLocation } from "react-router-dom";
import { useNavigation } from "./NavigationContext";

interface Breadcrumb {
  title: string;
  href: string;
}

interface MenuContextValue {
  breadcrumbs: Breadcrumb[];
  selectedMenuItem: string | null;
  setBreadcrumbs: (newBreadcrumbs: Breadcrumb[]) => void;
  addBreadcrumb: (breadcrumb: Breadcrumb) => void;
  removeBreadcrumb: (href: string) => void;
  clearBreadcrumbs: () => void;
  updateLastBreadcrumb: (title: string) => void;
  setSelectedMenuItem: Dispatch<SetStateAction<string | null>>;
  currentPage: Breadcrumb | undefined;
  isHomePage: boolean;
}

const MenuContext = createContext<MenuContextValue | undefined>(undefined);

export function MenuProvider({ children }: { children: ReactNode }) {
  const [breadcrumbs, setBreadcrumbs] = useState<Breadcrumb[]>([
    { title: "Home", href: "/" },
  ]);
  const [selectedMenuItem, setSelectedMenuItem] = useState<string | null>(null);
  const location = useLocation();
  const { activeSection } = useNavigation();

  // Section-based breadcrumbs mapping. There is no dynamic route-group
  // source (breadcrumb titles come from the static defaults below plus
  // the URL segments), so this stays a stable empty map; kept so a
  // future dynamic source can slot into getRouteBreadcrumbs unchanged.
  const sectionMap = useMemo<Record<string, Breadcrumb>>(() => ({}), []);

  // Route-based breadcrumbs mapping
  const routeMap = useMemo<Record<string, string>>(
    () => ({
      // Default route patterns
      create: "Create",
      edit: "Edit",
      view: "View",
      settings: "Settings",
      profile: "Profile",
      dashboard: "Dashboard",
      reports: "Reports",
      users: "Users",
      roles: "Roles",
      permissions: "Permissions",
    }),
    [],
  );

  // Generate breadcrumbs based on current route and section
  const getRouteBreadcrumbs = useCallback(
    (pathname: string, section: string) => {
      const baseBreadcrumbs: Breadcrumb[] = [{ title: "Home", href: "/" }];

      // Add section breadcrumb if active
      if (section && sectionMap[section]) {
        baseBreadcrumbs.push(sectionMap[section]);
      }

      // Route-specific breadcrumbs
      const pathSegments = pathname.split("/").filter(Boolean);
      let currentPath = "";

      pathSegments.forEach((segment) => {
        currentPath += `/${segment}`;

        // Skip if it's already covered by section
        if (section && sectionMap[section]?.href === currentPath) {
          return;
        }

        const title =
          routeMap[segment] ||
          segment.charAt(0).toUpperCase() + segment.slice(1).replace(/-/g, " ");

        // Don't add if it's a duplicate of the last breadcrumb
        const lastBreadcrumb = baseBreadcrumbs[baseBreadcrumbs.length - 1];
        if (lastBreadcrumb?.href !== currentPath) {
          baseBreadcrumbs.push({
            title,
            href: currentPath,
          });
        }
      });

      return baseBreadcrumbs;
    },
    [sectionMap, routeMap],
  );

  // Auto-update breadcrumbs based on route and section
  useEffect(() => {
    const newBreadcrumbs = getRouteBreadcrumbs(
      location.pathname,
      activeSection,
    );
    setBreadcrumbs(newBreadcrumbs);
  }, [location.pathname, activeSection, getRouteBreadcrumbs]);

  // Manually set breadcrumbs (overrides auto-generation)
  const setBreadcrumbsManual = useCallback((newBreadcrumbs: Breadcrumb[]) => {
    if (!Array.isArray(newBreadcrumbs)) {
      console.error("Breadcrumbs must be an array");
      return;
    }

    // Ensure Home is always first
    const breadcrumbsWithHome =
      newBreadcrumbs[0]?.href === "/"
        ? newBreadcrumbs
        : [{ title: "Home", href: "/" }, ...newBreadcrumbs];

    setBreadcrumbs(breadcrumbsWithHome);
  }, []);

  // Add breadcrumb to the end
  const addBreadcrumb = useCallback((breadcrumb: Breadcrumb) => {
    if (!breadcrumb?.title || !breadcrumb?.href) {
      console.error("Breadcrumb must have title and href");
      return;
    }

    setBreadcrumbs((prev) => {
      // Don't add if it already exists
      if (prev.some((b) => b.href === breadcrumb.href)) {
        return prev;
      }
      return [...prev, breadcrumb];
    });
  }, []);

  // Remove breadcrumb by href
  const removeBreadcrumb = useCallback((href: string) => {
    setBreadcrumbs((prev) => prev.filter((b) => b.href !== href));
  }, []);

  // Clear all except Home
  const clearBreadcrumbs = useCallback(() => {
    setBreadcrumbs([{ title: "Home", href: "/" }]);
  }, []);

  // Update last breadcrumb title (useful for dynamic titles)
  const updateLastBreadcrumb = useCallback((title: string) => {
    setBreadcrumbs((prev) => {
      if (prev.length === 0) return prev;
      const updated = [...prev];
      updated[updated.length - 1] = {
        ...updated[updated.length - 1],
        title,
      };
      return updated;
    });
  }, []);

  const value = useMemo<MenuContextValue>(
    () => ({
      // State
      breadcrumbs,
      selectedMenuItem,

      // Actions
      setBreadcrumbs: setBreadcrumbsManual,
      addBreadcrumb,
      removeBreadcrumb,
      clearBreadcrumbs,
      updateLastBreadcrumb,
      setSelectedMenuItem,

      // Helpers
      currentPage: breadcrumbs[breadcrumbs.length - 1],
      isHomePage: location.pathname === "/",
    }),
    [
      breadcrumbs,
      selectedMenuItem,
      setBreadcrumbsManual,
      addBreadcrumb,
      removeBreadcrumb,
      clearBreadcrumbs,
      updateLastBreadcrumb,
      setSelectedMenuItem,
      location.pathname,
    ],
  );

  return <MenuContext.Provider value={value}>{children}</MenuContext.Provider>;
}
