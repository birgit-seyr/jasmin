/**
 * Shared constants for the super-admin tenant user-management UI
 * (``TenantDetail`` page + its create-user modal).
 */

export const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  active: { bg: "#e8f5e9", color: "var(--color-share-content)" },
  pending_approval: { bg: "#fff3e0", color: "#e65100" },
  pending_invitation: { bg: "#e3f2fd", color: "#1565c0" },
  inactive: { bg: "#ffebee", color: "#c62828" },
};

// 'customer' is intentionally NOT in this list: customers must be linked to
// a Reseller, which is tenant-scoped, and the super-admin tenant management
// view doesn't load tenant-specific resellers reliably. Use the per-tenant
// "Configuration → Users" UI to create/edit customer users.
export const AVAILABLE_ROLES = [
  "admin",
  "office",
  "management",
  "gardener",
  "staff",
  "member",
];
