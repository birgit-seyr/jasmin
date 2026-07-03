import type { ReactElement } from "react";

/** Per-route access metadata, consumed by ``ProtectedRoute``. */
export interface RouteMeta {
  title?: string;
  requiredRole?: string | string[];
  requiredPermission?: string;
  requiredSetting?: string;
}

/** A single tenant route: path + element, with optional access metadata. */
export interface AppRoute {
  path: string;
  element: ReactElement;
  meta?: RouteMeta;
}

/** A feature group of routes, mounted under ``path`` in ``AppRouter``. */
export interface RouteGroup {
  path: string;
  feature: string;
  routes: AppRoute[];
}
