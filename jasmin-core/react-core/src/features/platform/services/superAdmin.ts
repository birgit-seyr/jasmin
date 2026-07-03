/**
 * Super-admin resource endpoints (tenants, backups, ops-checklist).
 *
 * These live on the public schema, so ``make generate-schema`` (which runs
 * under ``tenant_urls``) never includes them — there is no Orval client for
 * the super-admin API. Centralized here so the super-admin pages share one
 * URL definition instead of scattering ``/api/super-admin/...`` literals.
 *
 * Auth endpoints (login/refresh/...) live in ``authEndpoints.ts``.
 */

export const SUPER_ADMIN_ENDPOINTS = {
  /** List + create tenants. */
  tenants: "/api/super-admin/tenants/",
  tenant: (tenantId: string) => `/api/super-admin/tenants/${tenantId}/`,
  tenantUsers: (tenantId: string) =>
    `/api/super-admin/tenants/${tenantId}/users/`,
  tenantCreateAdmin: (tenantId: string) =>
    `/api/super-admin/tenants/${tenantId}/create-admin/`,
  tenantCreateUser: (tenantId: string) =>
    `/api/super-admin/tenants/${tenantId}/create-user/`,
  tenantUserRoles: (tenantId: string, userId: string) =>
    `/api/super-admin/tenants/${tenantId}/users/${userId}/roles/`,
  backups: "/api/super-admin/backups/",
  triggerBackup: "/api/super-admin/backups/trigger/",
  opsChecklist: "/api/super-admin/ops-checklist/",
  // OpsChecklistItem has an int PK (a public-schema model), unlike the
  // STR-id tenant resources above — hence ``string | number``.
  opsChecklistRunRotation: (itemId: string | number) =>
    `/api/super-admin/ops-checklist/${itemId}/run-rotation/`,
  opsChecklistMarkDone: (itemId: string | number) =>
    `/api/super-admin/ops-checklist/${itemId}/mark-done/`,
} as const;
