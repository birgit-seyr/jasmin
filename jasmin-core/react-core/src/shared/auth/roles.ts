/**
 * Single source of truth for user roles in the frontend.
 * Mirrors `apps/accounts/constants.py::Role` on the backend — keep in sync.
 *
 * A user can have multiple roles (e.g. ["member", "office"]).
 *
 * Authoritative checks must always happen on the backend; the helpers below
 * are for UX (showing/hiding UI), not security.
 */

export const ROLES = {
  GARDENER: "gardener",
  OFFICE: "office",
  STAFF: "staff",
  MANAGEMENT: "management",
  MEMBER: "member",
  ADMIN: "admin",
  CUSTOMER: "customer",
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];

/**
 * A "customer" is exclusive and can only co-exist with "member".
 * Keep in sync with `apps/authz/roles.py::CUSTOMER_COMPATIBLE_ROLES`.
 */
export const CUSTOMER_COMPATIBLE_ROLES: readonly Role[] = [
  ROLES.CUSTOMER,
  ROLES.MEMBER,
];
