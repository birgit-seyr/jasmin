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
  // Support tickets (public-schema aggregate; ticket ids are STR nanoids).
  supportTickets: "/api/super-admin/support-tickets/",
  supportTicket: (id: string) => `/api/super-admin/support-tickets/${id}/`,
  supportTicketReply: (id: string) =>
    `/api/super-admin/support-tickets/${id}/reply/`,
  supportTicketSetStatus: (id: string) =>
    `/api/super-admin/support-tickets/${id}/set-status/`,
} as const;
