import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@shared/contexts/AuthContext";
import { useTenant } from "@hooks/index";
import UnauthorizedPage from "../UnauthorizedPage";
import { logger } from "@shared/utils";
import type { RouteMeta } from "./types";

interface ProtectedRouteProps {
  children: ReactNode;
  /** Route meta information (access requirements). */
  meta?: RouteMeta;
}

export const ProtectedRoute = ({
  children,
  meta,
}: ProtectedRouteProps): ReactNode => {
  const { isAuthenticated, hasPermission, loading, userRole, isSuperAdmin } =
    useAuth();
  const location = useLocation();
  const { getSetting } = useTenant();

  if (loading) {
    return (
      <div role="status" aria-live="polite">
        Loading...
      </div>
    );
  }

  // 1. Authentication check
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 2. Super admin bypass
  if (isSuperAdmin) {
    return children; // Super admins can access everything
  }

  // 3. Tenant superuser bypass
  if (userRole === "superuser") {
    return children; // Tenant superusers can access everything in their tenant
  }

  // 4. Meta-based checks
  if (meta) {
    // If user has a role, check role-based access first
    if (userRole && userRole !== "member" && meta.requiredRole) {
      const roles = Array.isArray(meta.requiredRole)
        ? meta.requiredRole
        : [meta.requiredRole];
      if (!roles.includes(userRole)) {
        return <Navigate to="/unauthorized" replace />;
      }
    }
    // If no role or role check passed, fall back to permission check
    else if (
      meta.requiredPermission &&
      !hasPermission(meta.requiredPermission)
    ) {
      return <Navigate to="/unauthorized" replace />;
    }
  }

  if (meta?.requiredSetting) {
    const settingEnabled = getSetting(meta.requiredSetting, false);

    if (!settingEnabled) {
      logger.debug(`🚫 Route blocked: ${meta.requiredSetting} is disabled`);
      return (
        <UnauthorizedPage message={`Feature not enabled for this tenant`} />
      );
    }
  }

  // 5. All checks passed
  return children;
};
