import { createContext, useMemo } from "react";
import type { ReactNode } from "react";

interface PermissionUser {
  roles?: string[];
  [key: string]: unknown;
}

interface PermissionTenant {
  [key: string]: unknown;
}

interface PermissionContextValue {
  hasRole: (role: string) => boolean;
  hasAnyRole: (roles: string[]) => boolean;
  getRoles: () => string[];
  isGardener: () => boolean;
  isOfficeStaff: () => boolean;
  isManagement: () => boolean;
  isPackTeam: () => boolean;
  isHarvestTeam: () => boolean;
  isItAdmin: () => boolean;
  isMember: () => boolean;
  isMemberOnly: () => boolean;
  isSuperuser: () => boolean;
  isStaffMember: () => boolean;
  isFieldWorker: () => boolean;
  isOperational: () => boolean;
  canAccess?: (resource: string) => boolean;
  canPerformAction?: (action: string) => boolean;
  user?: PermissionUser;
  tenant?: PermissionTenant;
  userRoles?: string[];
}

interface PermissionProviderProps {
  children: ReactNode;
  user: PermissionUser | null;
  tenant: PermissionTenant | null;
}

const PermissionContext = createContext<PermissionContextValue | undefined>(
  undefined,
);

export const PermissionProvider = ({
  children,
  user,
  tenant,
}: PermissionProviderProps) => {
  const permissions = useMemo<PermissionContextValue>(() => {
    if (!user || !tenant) {
      return {
        // Role checking functions
        hasRole: () => false,
        hasAnyRole: () => false,
        getRoles: () => [],

        // Specific role checks
        isGardener: () => false,
        isOfficeStaff: () => false,
        isManagement: () => false,
        isPackTeam: () => false,
        isHarvestTeam: () => false,
        isItAdmin: () => false,
        isMember: () => false,
        isMemberOnly: () => false,
        isSuperuser: () => false,

        // Role groups
        isStaffMember: () => false,
        isFieldWorker: () => false,
        isOperational: () => false,

        // Access control
        canAccess: () => false,
        canPerformAction: () => false,
      };
    }

    // Get user's roles array from Django backend
    const userRoles = user.roles || []; // This should be the roles array from your JasminUser

    // Role checking functions (matching your Django backend)
    const hasRole = (role: string) => {
      return userRoles.includes(role);
    };

    const hasAnyRole = (roles: string[]) => {
      return roles.some((role) => userRoles.includes(role));
    };

    const getRoles = () => {
      return [...userRoles]; // Return a copy of the roles array
    };

    // Specific role checks (matching your Django methods)
    const isGardener = () => hasRole("gardener");
    const isOfficeStaff = () => hasRole("office");
    const isManagement = () => hasRole("management");
    const isPackTeam = () => hasRole("pack_team");
    const isHarvestTeam = () => hasRole("harvest_team");
    const isItAdmin = () => hasRole("it_admin");
    const isMember = () => hasRole("member");
    const isMemberOnly = () =>
      userRoles.length === 1 && userRoles[0] === "member";
    const isSuperuser = () => hasRole("superuser");

    // Convenience role groups
    const isStaffMember = () =>
      hasAnyRole(["office", "management", "it_admin"]);
    const isFieldWorker = () => hasAnyRole(["gardener", "harvest_team"]);
    const isOperational = () =>
      hasAnyRole(["gardener", "harvest_team", "pack_team"]);

    return {
      // Core role functions
      hasRole,
      hasAnyRole,
      getRoles,

      // Specific role checks
      isGardener,
      isOfficeStaff,
      isManagement,
      isPackTeam,
      isHarvestTeam,
      isItAdmin,
      isMember,
      isMemberOnly,
      isSuperuser,

      // Role groups
      isStaffMember,
      isFieldWorker,
      isOperational,

      // User data
      user,
      tenant,
      userRoles,
    };
  }, [user, tenant]);

  return (
    <PermissionContext.Provider value={permissions}>
      {children}
    </PermissionContext.Provider>
  );
};
