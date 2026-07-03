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
  parentKey?: string;
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
 *  containing submenu key so we can open it on a deep-link. */
function flattenLeaves(
  items: MenuProps["items"],
  parentKey?: string,
): LeafRoute[] {
  const out: LeafRoute[] = [];
  for (const raw of items ?? []) {
    const item = raw as SidebarItem | null;
    if (!item) continue;
    if (item.children?.length) {
      out.push(...flattenLeaves(item.children, String(item.key)));
      continue;
    }
    const to = leafTo(item.label);
    if (to) out.push({ key: String(item.key), to, parentKey });
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
    if (match.parentKey && !(openKeys ?? []).includes(match.parentKey)) {
      onOpenChange?.([match.parentKey]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.key, match?.parentKey]);

  return (
    <Sider className="sidebar">
      <div className="sidebar-header">{header}</div>
      <Menu
        mode="inline"
        selectedKeys={activeSidebarItem ? [activeSidebarItem] : []}
        openKeys={openKeys}
        onOpenChange={onOpenChange}
        items={items}
        onSelect={({ key }) => setActiveSidebarItem(key)}
      />
    </Sider>
  );
}
