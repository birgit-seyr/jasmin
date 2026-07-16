import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { useAuth } from "@shared/contexts/AuthContext";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import {
  type AdminTicketDetail,
  type AdminTicketListRow,
  type Paginated,
  SUPPORT_STATUS_COLORS,
  TICKET_STATUSES,
} from "@features/platform/supportTickets";

// Rank statuses by their canonical order (open first) so actionable tickets
// bubble to the top of each tenant group. Derived from TICKET_STATUSES so a
// status add/reorder can't silently drift this ordering.
const STATUS_RANK: Record<string, number> = Object.fromEntries(
  TICKET_STATUSES.map((status, index) => [status, index]),
);

function StatusPill({ status }: { status: string }) {
  const c = SUPPORT_STATUS_COLORS[status] ?? { bg: "#eee", color: "#555" };
  return (
    <span
      className="sa-status-pill"
      style={{ background: c.bg, color: c.color }}
    >
      {status.replace("_", " ")}
    </span>
  );
}

export default function SuperAdminSupportTickets() {
  const navigate = useNavigate();
  const { isAuthenticated, isSuperAdmin, loading: authLoading } = useAuth();
  const authorized = !authLoading && isAuthenticated && isSuperAdmin;

  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated || !isSuperAdmin) navigate("/login");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, isAuthenticated, isSuperAdmin]);

  const listQuery = useQuery<Paginated<AdminTicketListRow>>({
    queryKey: ["super-admin", "support-tickets", statusFilter],
    enabled: authorized,
    queryFn: async () => {
      const response = await axiosService.get(
        SUPER_ADMIN_ENDPOINTS.supportTickets,
        { params: statusFilter ? { status: statusFilter } : undefined },
      );
      return response.data;
    },
  });

  const rows = useMemo(() => listQuery.data?.results ?? [], [listQuery.data]);

  // Group by tenant; within each tenant sort open-first, then most-recent-first.
  const groups = useMemo(() => {
    const map = new Map<string, AdminTicketListRow[]>();
    for (const row of rows) {
      const key = row.tenant_name || row.tenant_schema;
      const list = map.get(key);
      if (list) list.push(row);
      else map.set(key, [row]);
    }
    for (const list of map.values()) {
      list.sort((a, b) => {
        const rank =
          (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
        if (rank !== 0) return rank;
        return b.updated_at.localeCompare(a.updated_at);
      });
    }
    return [...map.entries()];
  }, [rows]);

  if (authorized && listQuery.isPending) {
    return <div className="sa-fullscreen-state">Loading tickets...</div>;
  }

  return (
    <div className="sa-page">
      <header className="sa-app-header">
        <button
          onClick={() => navigate("/")}
          className="sa-btn sa-btn--header"
          style={{ marginRight: 8 }}
        >
          ← Dashboard
        </button>
      </header>

      <div className="sa-page-content">
        {selectedId ? (
          <TicketDetailPanel
            id={selectedId}
            onBack={() => setSelectedId(null)}
          />
        ) : (
          <div className="sa-section">
            <div className="sa-section-header">
              <h2 className="sa-section-title">Support Tickets</h2>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="sa-form-input"
                aria-label="Filter by status"
                style={{ width: "10em" }}
              >
                <option value="">All statuses</option>
                {TICKET_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace("_", " ")}
                  </option>
                ))}
              </select>
            </div>

            {rows.length === 0 ? (
              <div className="sa-section-empty">No support tickets.</div>
            ) : (
              groups.map(([tenantName, tenantRows]) => (
                <div key={tenantName} className="sa-ticket-group">
                  <h3 className="sa-ticket-group-title">{tenantName}</h3>
                  <table className="sa-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>status</th>
                        <th>subject</th>
                        <th>from</th>
                        <th>priority</th>
                        <th>updated</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tenantRows.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <button
                              onClick={() => setSelectedId(row.id)}
                              className="sa-btn sa-btn--detail"
                            >
                              Open
                            </button>
                          </td>
                          <td>
                            <StatusPill status={row.status} />
                          </td>
                          <td>{row.subject}</td>
                          <td>{row.creator_name}</td>
                          <td>{row.priority}</td>
                          <td>
                            {new Date(row.updated_at).toLocaleString("de-DE")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function TicketDetailPanel({ id, onBack }: { id: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const [replyBody, setReplyBody] = useState("");

  const detailQuery = useQuery<AdminTicketDetail>({
    queryKey: ["super-admin", "support-ticket", id],
    queryFn: async () =>
      (await axiosService.get(SUPER_ADMIN_ENDPOINTS.supportTicket(id))).data,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ["super-admin", "support-ticket", id],
    });
    void queryClient.invalidateQueries({
      queryKey: ["super-admin", "support-tickets"],
    });
  };

  const replyMutation = useMutation({
    mutationFn: async (body: string) =>
      (
        await axiosService.post(SUPER_ADMIN_ENDPOINTS.supportTicketReply(id), {
          body,
        })
      ).data,
    onSuccess: () => {
      setReplyBody("");
      invalidate();
    },
    onError: (e) => notify.error(getErrorMessage(e, "Failed to send reply")),
  });

  const statusMutation = useMutation({
    mutationFn: async (status: string) =>
      (
        await axiosService.post(
          SUPER_ADMIN_ENDPOINTS.supportTicketSetStatus(id),
          { status },
        )
      ).data,
    onSuccess: invalidate,
    onError: (e) => notify.error(getErrorMessage(e, "Failed to update status")),
  });

  const ticket = detailQuery.data;
  const sendReply = () => {
    const trimmed = replyBody.trim();
    if (trimmed) replyMutation.mutate(trimmed);
  };

  return (
    <div className="sa-section">
      <div className="sa-section-header">
        <button onClick={onBack} className="sa-btn sa-btn--primary">
          ← Back to list
        </button>
      </div>

      {!ticket ? (
        <div className="sa-section-empty">Loading ticket...</div>
      ) : (
        <div className="sa-card-compact sa-card--lg">
          <div className="sa-detail-header">
            <h2 className="sa-detail-title">{ticket.subject}</h2>
            <StatusPill status={ticket.status} />
          </div>

          <div className="sa-ticket-meta">
            <span className="sa-ticket-meta-label">Tenant</span>
            <span>{ticket.tenant_name}</span>

            <span className="sa-ticket-meta-label">Reporter</span>
            <span>
              {ticket.creator_name}{" "}
              <span style={{ color: "var(--color-text-secondary)" }}>
                &lt;{ticket.creator_email}&gt;
              </span>
            </span>

            <span className="sa-ticket-meta-label">Priority</span>
            <span>{ticket.priority}</span>

            <span className="sa-ticket-meta-label">Created</span>
            <span>{new Date(ticket.created_at).toLocaleString("de-DE")}</span>

            <span className="sa-ticket-meta-label">Status</span>
            <span>
              <select
                value={ticket.status}
                onChange={(e) => statusMutation.mutate(e.target.value)}
                className="sa-form-input"
                aria-label="Change status"
                style={{ maxWidth: 200 }}
              >
                {TICKET_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace("_", " ")}
                  </option>
                ))}
              </select>
            </span>
          </div>

          <h3 className="sa-subheading">Conversation</h3>
          <div className="sa-ticket-thread">
            {ticket.messages.map((m) => (
              <div
                key={m.id}
                className={`sa-ticket-message sa-ticket-message--${m.author_kind}`}
              >
                <div className="sa-ticket-message-head">
                  <span className="sa-ticket-message-author">
                    {m.author_name}
                  </span>
                  <span className="sa-ticket-message-role">
                    {m.author_kind === "super_admin" ? "Support" : "Staff"}
                  </span>
                  <span className="sa-ticket-message-time">
                    {new Date(m.created_at).toLocaleString("de-DE")}
                  </span>
                </div>
                <div className="sa-ticket-message-body">{m.body}</div>
              </div>
            ))}
          </div>

          <h3 className="sa-subheading">Reply</h3>
          <textarea
            value={replyBody}
            onChange={(e) => setReplyBody(e.target.value)}
            placeholder=""
            className="sa-form-input sa-ticket-reply"
            rows={3}
            aria-label="Reply"
          />
          <button
            onClick={sendReply}
            disabled={!replyBody.trim() || replyMutation.isPending}
            className="sa-btn sa-btn--primary"
            style={{ marginTop: 8 }}
          >
            {replyMutation.isPending ? "Sending…" : "Send reply"}
          </button>
        </div>
      )}
    </div>
  );
}
