import dayjs from "dayjs";
import { useMemo } from "react";
import { useTenant } from "./useTenant";

// Fallback creation year when the tenant record carries no ``created_at`` (e.g.
// the anonymous ``/tenants/current/`` payload). The selectable window spans this
// many years starting at the tenant's creation year.
const DEFAULT_TENANT_CREATION_YEAR = 2025;
const YEAR_WINDOW = 3;

/**
 * Single source of truth for the year range the Year / Week selectors offer:
 * the tenant's creation year (or the default fallback) plus a fixed forward
 * window. Both selectors must present the same range, so they read it here
 * instead of each re-deriving the magic fallback + ``Array.from`` window.
 */
export function useTenantYearOptions() {
  const { tenant } = useTenant();

  const tenantCreationYear = tenant?.created_at
    ? dayjs(tenant.created_at as string).year()
    : DEFAULT_TENANT_CREATION_YEAR;

  const yearOptions = useMemo(
    () =>
      Array.from({ length: YEAR_WINDOW }, (_, index) => ({
        value: index + tenantCreationYear,
        label: index + tenantCreationYear,
      })),
    [tenantCreationYear],
  );

  return { tenantCreationYear, yearOptions };
}
