import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@shared/contexts/AuthContext";

interface ProtectedRouteProps {
  children: ReactNode;
}

/**
 * Authentication only — it decides whether you are logged in, never what you
 * may reach.
 *
 * Authorization is ``RequireRole`` inside the route files, which reads the
 * full role list. Nothing here should gate on a role: the one singular role
 * value available (``userRole``) collapses a multi-role user to one string,
 * so a check against it would answer differently depending on the order the
 * backend happened to store them in.
 */
export const ProtectedRoute = ({
  children,
}: ProtectedRouteProps): ReactNode => {
  const { isAuthenticated, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div role="status" aria-live="polite">
        Loading...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
};
