import type { RoleFlags } from "./useRoles";

/**
 * Item shape for role-gated menus / nav lists.
 *
 * Add `requireRole: "isOffice"` (or any other flag from `useRoles()`) on any
 * item that should only show for users with that flag set. Items without
 * `requireRole` always show.
 *
 * Used by sidebar menus and the top navigation. Recursively drops items whose
 * flag is false; section parents whose children all got dropped are removed
 * too, so you don't get empty headers.
 */
export type RoleGatedItem = {
  key: string;
  requireRole?: keyof RoleFlags;
  children?: RoleGatedItem[];
  // antd menu items carry many other fields we pass through untouched
  [k: string]: unknown;
};

export function filterByRole<T extends RoleGatedItem>(
  items: T[],
  flags: RoleFlags,
): T[] {
  return items.flatMap((item) => {
    if (item.requireRole && !flags[item.requireRole]) return [];
    // Strip `requireRole` before returning so antd Menu doesn't forward it
    // as an unknown prop to the underlying DOM element (React warning).
    const { requireRole: _omit, ...rest } = item;
    if (item.children) {
      const children = filterByRole(item.children, flags);
      if (children.length === 0) return [];
      return [{ ...rest, children } as T];
    }
    return [rest as T];
  });
}
