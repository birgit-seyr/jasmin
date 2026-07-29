import { isValidElement, useEffect, useMemo } from "react";
import type { MenuProps } from "antd";
import { Layout, Menu } from "antd";
import { useLocation } from "react-router-dom";
import { useNavigation } from "@shared/contexts/NavigationContext";
import "@shared/styles/layout/sidebar.css";

const { Sider } = Layout;

interface SidebarShellProps {
  header: string;
  items: MenuProps["items"];
  openKeys?: string[];
  onOpenChange?: (keys: string[]) => void;
}

type SidebarItem = {
  key?: string | number;
  label?: unknown;
  children?: MenuProps["items"];
};

interface LeafRoute {
  key: string;
  to: string;
  /** Every containing submenu key, outermost first — opened together on a
   *  deep-link so submenus nested more than one level deep still reveal. */
  parentKeys: string[];
}

/** The route a leaf navigates to, read from its `<Link to>` label. */
function leafTo(label: unknown): string | undefined {
  if (isValidElement(label)) {
    const to = (label.props as { to?: unknown })?.to;
    if (typeof to === "string") return to;
  }
  return undefined;
}

/** Flatten the menu tree into the leaves that carry a route, remembering the
 *  full chain of containing submenu keys. */
function flattenLeaves(
  items: MenuProps["items"],
  parentKeys: string[] = [],
): LeafRoute[] {
  const out: LeafRoute[] = [];
  for (const raw of items ?? []) {
    const item = raw as SidebarItem | null;
    if (!item) continue;
    if (item.children?.length) {
      out.push(
        ...flattenLeaves(item.children, [...parentKeys, String(item.key)]),
      );
      continue;
    }
    const to = leafTo(item.label);
    if (to) out.push({ key: String(item.key), to, parentKeys });
  }
  return out;
}

export default function SidebarShell({
  header,
  items,
  openKeys,
  onOpenChange,
}: SidebarShellProps) {
  const { activeSidebarItem, setActiveSidebarItem } = useNavigation();
  const { pathname } = useLocation();

  // Top-level submenu keys. Used to keep the "one root group open at a time"
  // accordion while letting NESTED submenus open freely (a nested key is not a
  // root, so opening it keeps the whole set — including its ancestors).
  const rootSubmenuKeys = useMemo(
    () =>
      (items ?? [])
        .map((raw) => raw as SidebarItem | null)
        .filter((item) => item?.children?.length)
        .map((item) => String(item?.key)),
    [items],
  );

  const handleMenuOpenChange = (keys: string[]) => {
    const latestOpenKey = keys.find((key) => !(openKeys ?? []).includes(key));
    if (latestOpenKey && rootSubmenuKeys.includes(latestOpenKey)) {
      // Opened a top-level group → collapse the other top-level groups.
      onOpenChange?.([latestOpenKey]);
    } else {
      // Opened/closed a nested submenu → keep exactly what antd wants open.
      onOpenChange?.(keys);
    }
  };

  // Match the current URL to a sidebar leaf so following a full link (e.g. from
  // a review doc) highlights the right entry AND opens its submenu — not only
  // when the user clicks. The leaf route comes from its `<Link to>` label.
  const leaves = useMemo(() => flattenLeaves(items), [items]);
  const match = useMemo(() => {
    const hits = leaves.filter(
      (leaf) => pathname === leaf.to || pathname.startsWith(`${leaf.to}/`),
    );
    // Longest route wins, so a nested path picks the most specific entry.
    hits.sort((a, b) => b.to.length - a.to.length);
    return hits[0];
  }, [leaves, pathname]);

  // Sync ONLY on route change. Depending on ``openKeys`` here would re-open a
  // submenu the user just collapsed while staying on the same route. Reading the
  // current ``openKeys``/``onOpenChange`` from the closure is fine: this effect
  // re-runs on navigation, i.e. on the render that already has the latest props.
  useEffect(() => {
    if (!match) return;
    setActiveSidebarItem(match.key);
    const missing = match.parentKeys.filter(
      (key) => !(openKeys ?? []).includes(key),
    );
    if (missing.length) onOpenChange?.([...(openKeys ?? []), ...missing]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.key]);

  return (
    <Sider className="sidebar">
      <div className="sidebar-header">{header}</div>
      <Menu
        mode="inline"
        selectedKeys={activeSidebarItem ? [activeSidebarItem] : []}
        openKeys={openKeys}
        onOpenChange={handleMenuOpenChange}
        items={items}
        onSelect={({ key }) => setActiveSidebarItem(key)}
      />
    </Sider>
  );
}
