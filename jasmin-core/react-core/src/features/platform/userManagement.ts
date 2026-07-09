/**
 * Shared constants for the super-admin tenant user-management UI
 * (``TenantDetail`` page + its create-user modal).
 */

import { ROLES } from "@shared/auth/roles";

export const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  active: { bg: "#e8f5e9", color: "var(--color-share-content)" },
  pending_approval: { bg: "#fff3e0", color: "#e65100" },
  pending_invitation: { bg: "#e3f2fd", color: "#1565c0" },
  inactive: { bg: "#ffebee", color: "#c62828" },
};

// Derived from the shared ``ROLES`` single-source-of-truth (which carries the
// "keep in sync with accounts/constants.py" contract) so a backend role rename
// can't silently drift this list.
//
// 'customer' is intentionally excluded: customers must be linked to a Reseller,
// which is tenant-scoped, and the super-admin tenant management view doesn't
// load tenant-specific resellers reliably. Use the per-tenant
// "Configuration → Users" UI to create/edit customer users.
export const AVAILABLE_ROLES: string[] = Object.values(ROLES).filter(
  (role) => role !== ROLES.CUSTOMER,
);
