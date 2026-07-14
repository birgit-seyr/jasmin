import { Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ImportSharesModeBanner } from '@features/commissioning/components';
import TenantDashboardPage from "@features/platform/pages/TenantDashboard";
import UnauthorizedPage from "../UnauthorizedPage";
import { ProtectedRoute } from "./ProtectedRoute";
import { routeGroups } from "./routeConfig";
import { useRouteTitle } from "./useRouteTitle";

// Route groups that show the "demand comes from the CSV import" banner when
// the tenant runs in weekly-upload mode (the banner self-hides otherwise).
const IMPORT_SHARES_BANNER_GROUPS = new Set(["/members", "/abos"]);

interface AppRouterProps {
  defaultRedirect?: string;
}

export const AppRouter = ({ defaultRedirect = "/" }: AppRouterProps) => {
  // No auth checks here - JasminApp handles that now
  // This component only handles routing for authenticated staff users

  useRouteTitle();

  return (
    <Suspense
      fallback={
        <div className="page-loading" role="status" aria-live="polite">
          <div>Loading page...</div>
        </div>
      }
    >
      <Routes>
        <Route
          path="/"
          element={
            defaultRedirect === "/" ? (
              <TenantDashboardPage />
            ) : (
              <Navigate to={defaultRedirect} replace />
            )
          }
        />
        <Route path="/unauthorized" element={<UnauthorizedPage />} />

        {/* All your tenant route groups */}
        {routeGroups.map(({ path: groupPath, routes }) => {
          const groupRoutes = (
            <Routes>
              {routes.map(({ path, element, meta }) => (
                <Route
                  key={path}
                  path={path.replace(groupPath, "")}
                  element={
                    <ProtectedRoute meta={meta}>{element}</ProtectedRoute>
                  }
                />
              ))}
            </Routes>
          );

          return (
            <Route
              key={groupPath}
              path={`${groupPath}/*`}
              element={
                <>
                  {IMPORT_SHARES_BANNER_GROUPS.has(groupPath) && (
                    <ImportSharesModeBanner />
                  )}
                  {/* Configuration pages get a primary-coloured border on
                      every card via this scoping wrapper (see
                      card-headers.css). */}
                  {groupPath === "/configuration" ? (
                    <div className="configuration-page">{groupRoutes}</div>
                  ) : (
                    groupRoutes
                  )}
                </>
              }
            />
          );
        })}

        <Route path="*" element={<Navigate to={defaultRedirect} replace />} />
      </Routes>
    </Suspense>
  );
};
