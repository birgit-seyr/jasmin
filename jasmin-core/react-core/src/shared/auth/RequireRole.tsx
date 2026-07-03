import type { ReactNode } from "react";
import { useRoles, type RoleFlags } from "./useRoles";

interface RequireRoleProps {
  /** Name of a flag from `useRoles()` that must be true (e.g. "isOffice"). */
  flag: keyof RoleFlags;
  /** Rendered when the user doesn't have access. Defaults to a simple message. */
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * Whole-page guard. Use to wrap a route element so the page only renders
 * for users matching the given flag from `useRoles()`.
 *
 *   <RequireRole flag="isOffice">
 *     <Invoices />
 *   </RequireRole>
 *
 */
export function RequireRole({ flag, fallback, children }: RequireRoleProps) {
  const flags = useRoles();
  if (!flags[flag]) {
    return (
      <>{fallback ?? <div style={{ padding: 24 }}>Not authorized.</div>}</>
    );
  }
  return <>{children}</>;
}
