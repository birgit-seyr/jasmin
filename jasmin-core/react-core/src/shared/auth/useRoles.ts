import { useAuth } from "@shared/contexts/AuthContext";
import { ROLES, type Role } from "./roles";

/**
 * `useRoles` — returns a flags object with one boolean per role, plus a few
 * named groups for common combinations across the app.
 *
 *   const r = useRoles();
 *   if (r.canEdit) { ... }            // gardener + staff + office + admin
 *   if (r.isOffice) { ... }           // office + admin
 *   if (r.isStaff) { ... }            // any internal role
 *   if (r.gardener && r.office) ...   // raw role checks still available
 *
 * Add a new group below only when the same combination shows up on several
 * pages — keep this list short. For one-off cases use raw role checks.
 *
 * Reminder: this is UX gating only. Backend must enforce the same rules.
 */
export type RoleFlags = Omit<Record<Role, boolean>, "member" | "customer"> & {
  /** holds the member role, whether or not it is the only one */
  hasMemberRole: boolean;
  /** holds the customer role */
  hasCustomerRole: boolean;
  /**
   * gardener OR staff OR office OR admin — "can edit operational data".
   * Only correct for resources whose backend write gate is `IsStaff`. Pages on
   * an `IsOffice` write gate must use `isOffice`, or they render controls the
   * API refuses.
   */
  canEdit: boolean;
  /** office OR admin — administrative actions (exports, prices, finalize…) */
  isOffice: boolean;
  /** gardener OR office OR admin — cultivation pages */
  canEditCultivation: boolean;
  /** management OR admin — high-level oversight */
  isManagement: boolean;
  /** admin only */
  isAdmin: boolean;
  /** any internal role (gardener / staff / office / management / admin) */
  isStaff: boolean;
  /** member only, no other role */
  isMemberOnly: boolean;
  /** raw list, e.g. for sending to backend or debugging */
  roles: readonly Role[];
};

export function useRoles(): RoleFlags {
  const { user } = useAuth();
  const roles = (user?.roles ?? []) as readonly Role[];
  const roleSet = new Set(roles);

  const gardener = roleSet.has(ROLES.GARDENER);
  const office = roleSet.has(ROLES.OFFICE);
  const staff = roleSet.has(ROLES.STAFF);
  const management = roleSet.has(ROLES.MANAGEMENT);
  const hasMemberRole = roleSet.has(ROLES.MEMBER);
  const admin = roleSet.has(ROLES.ADMIN);
  const hasCustomerRole = roleSet.has(ROLES.CUSTOMER);

  return {
    // raw role flags
    gardener,
    office,
    staff,
    management,
    hasMemberRole,
    admin,
    hasCustomerRole,
    // grouped flags
    canEdit: gardener || staff || office || admin,
    isOffice: office || admin,
    canEditCultivation: gardener || office || admin,
    isManagement: management || admin,
    isAdmin: admin,
    isStaff: gardener || staff || office || management || admin,
    isMemberOnly: roles.length === 1 && hasMemberRole,
    // raw access
    roles,
  };
}
