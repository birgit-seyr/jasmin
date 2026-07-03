import { useAuth } from "@shared/contexts/AuthContext";
import { ROLES, type Role } from "./roles";

/**
 * `useRoles` — returns a flags object with one boolean per role, plus a few
 * named groups for common combinations across the app.
 *
 *   const r = useRoles();
 *   if (r.canEdit) { ... }            // gardener + office + admin
 *   if (r.isOffice) { ... }           // office + admin
 *   if (r.isStaff) { ... }            // any internal role
 *   if (r.gardener && r.office) ...   // raw role checks still available
 *
 * Add a new group below only when the same combination shows up on several
 * pages — keep this list short. For one-off cases use raw role checks.
 *
 * Reminder: this is UX gating only. Backend must enforce the same rules.
 */
export type RoleFlags = Record<Role, boolean> & {
  /** gardener OR office OR admin — “can edit operational data” */
  canEdit: boolean;
  /** office OR admin — administrative actions (exports, prices, finalize…) */
  isOffice: boolean;
  /** gardener OR admin — cultivation/field work */
  isGardener: boolean;
  /** management OR admin — high-level oversight */
  isManagement: boolean;
  /** admin only */
  isAdmin: boolean;
  /** any internal role (gardener / staff / office / management / admin) */
  isStaff: boolean;
  /** member only, no other role */
  isMemberOnly: boolean;
  /** customer OR office */
  isCustomer: boolean;
  /** raw list, e.g. for sending to backend or debugging */
  roles: readonly Role[];
};

export function useRoles(): RoleFlags {
  const { user } = useAuth();
  const roles = (user?.roles ?? []) as readonly Role[];
  const set = new Set(roles);

  const gardener = set.has(ROLES.GARDENER);
  const office = set.has(ROLES.OFFICE);
  const staff = set.has(ROLES.STAFF);
  const management = set.has(ROLES.MANAGEMENT);
  const member = set.has(ROLES.MEMBER);
  const admin = set.has(ROLES.ADMIN);
  const customer = set.has(ROLES.CUSTOMER);

  return {
    // raw role flags
    gardener,
    office,
    staff,
    management,
    member,
    admin,
    customer,
    // grouped flags
    canEdit: gardener || staff || office || admin,
    isOffice: office || admin,
    isGardener: gardener || office|| admin,
    isManagement: management || admin,
    isAdmin: admin,
    isStaff: gardener || staff || office || management || admin,
    isCustomer: customer || office || admin, 
    isMemberOnly: roles.length === 1 && member,
    // raw access
    roles,
  };
}
