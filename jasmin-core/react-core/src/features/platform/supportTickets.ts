/**
 * Local types + constants for the super-admin Support Tickets page.
 *
 * The super-admin API lives on the public schema and is excluded from the Orval
 * schema, so — like the rest of the platform app — these are hand-written
 * interfaces over the raw JSON rather than generated types.
 */

export interface AdminTicketMessage {
  id: string;
  author_kind: "staff" | "super_admin";
  author_name: string;
  body: string;
  created_at: string;
}

export interface AdminTicketListRow {
  id: string;
  tenant_schema: string;
  tenant_name: string;
  subject: string;
  status: string;
  priority: string;
  creator_name: string;
  creator_email: string;
  created_at: string;
  updated_at: string;
}

export interface AdminTicketDetail extends AdminTicketListRow {
  creator_id: string;
  creator_roles: string[];
  context: Record<string, string>;
  resolved_at: string | null;
  messages: AdminTicketMessage[];
}

/** DRF LimitOffsetPagination envelope. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export const TICKET_STATUSES = [
  "open",
  "in_progress",
  "resolved",
  "closed",
] as const;

// Mirrors the userManagement.ts STATUS_COLORS pattern (inline bg/color on a
// sa-badge-style pill), so the platform page needs no new CSS class.
export const SUPPORT_STATUS_COLORS: Record<string, { bg: string; color: string }> =
  {
    open: { bg: "#e3f2fd", color: "#1565c0" },
    // Darkened from #e65100 → #b34700 to clear WCAG AA (4.5:1) on the pale bg.
    in_progress: { bg: "#fff3e0", color: "#b34700" },
    resolved: {
      bg: "var(--color-success-bg)",
      color: "var(--color-share-content)",
    },
    closed: { bg: "#eeeeee", color: "#555" },
  };
