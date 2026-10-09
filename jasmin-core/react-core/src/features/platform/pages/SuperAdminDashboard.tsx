import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { useAuth } from "@shared/contexts/AuthContext";
import { getErrorMessage } from "@shared/utils/apiError";
import CreateTenantModal from "@features/platform/modals/CreateTenantModal";

interface Tenant {
  id: number;
  schema_name: string;
  name: string;
  domain?: string;
  is_active?: boolean;
  created_on?: string;
  user_count?: number;
}

export default function SuperAdminDashboard() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation();
  const {
    isAuthenticated,
    isSuperAdmin,
    loading: authLoading,
    logout,
  } = useAuth();

  // Only authorized super-admins may hit these endpoints; gate the
  // queries on the same condition the redirect effect uses so we don't
  // fire requests we know will 403.
  const authorized = !authLoading && isAuthenticated && isSuperAdmin;

  useEffect(() => {
    // Wait for AuthContext to finish its boot-time silent refresh before
    // deciding whether to bounce to login.
    if (authLoading) return;
    if (!isAuthenticated || !isSuperAdmin) {
      navigate("/login");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, isAuthenticated, isSuperAdmin]);

  // The super-admin endpoints aren't part of the tenant-scoped orval
  // schema, so we hit them through ``axiosService`` directly while
  // letting TanStack Query handle caching, dedup, and post-mutation
  // refetch.
  const tenantsQuery = useQuery<Tenant[]>({
    queryKey: ["super-admin", "tenants"],
    enabled: authorized,
    queryFn: async () => {
      const response = await axiosService.get(SUPER_ADMIN_ENDPOINTS.tenants);
      return response.data as Tenant[];
    },
  });

  const tenants = tenantsQuery.data ?? [];
  const loading = tenantsQuery.isPending;
  const error = tenantsQuery.isError
    ? getErrorMessage(tenantsQuery.error, "Failed to load tenants")
    : null;

  const refetchTenants = () => {
    void tenantsQuery.refetch();
  };

  const handleLogout = async () => {
    // AuthContext.logout() POSTs to /api/super-admin/auth/logout/ with an
    // empty body (the HttpOnly sa_refresh_token cookie carries the token),
    // clears the in-memory access token, wipes user metadata, and navigates.
    await logout();
  };

  if (loading) {
    return <div className="sa-fullscreen-state">Loading tenants...</div>;
  }

  if (error) {
    return (
      <div className="sa-fullscreen-error">
        <div style={{ fontSize: "18px", color: "var(--color-error)" }}>
          {error}
        </div>
        <button onClick={refetchTenants} className="sa-btn sa-btn--info">
          Retry
        </button>
        <button onClick={handleLogout} className="sa-btn sa-btn--danger">
          Logout
        </button>
      </div>
    );
  }

  return (
    <div className="sa-page">
      <header className="sa-app-header">
        <button
          onClick={() => navigate("/ops-checklist")}
          className="sa-btn sa-btn--header"
          style={{ marginRight: 8 }}
        >
          Ops Checklist
        </button>
        <button
          onClick={() => navigate("/support-tickets")}
          className="sa-btn sa-btn--header"
          style={{ marginRight: 8 }}
        >
          Support Tickets
        </button>
        <button onClick={handleLogout} className="sa-btn sa-btn--header">
          Logout
        </button>
      </header>
      <div className="sa-hero-band"></div>

      <div className="sa-page-content">
        <div className="sa-stats-grid">
          <div className="sa-card">
            <h3 className="sa-stat-label">Total Tenants</h3>
            <p className="sa-stat-value">
              {tenants.length}
            </p>
          </div>

          <div className="sa-card">
            <h3 className="sa-stat-label">Active Tenants</h3>
            <p className="sa-stat-value sa-stat-value--success">
              {tenants.filter((t) => t.is_active !== false).length}
            </p>
          </div>
        </div>

        <div className="sa-section">
          <div className="sa-section-header">
            <h2 className="sa-section-title">All Tenants</h2>
            <button
              onClick={() => setShowCreateModal(true)}
              className="sa-btn sa-btn--primary"
            >
              + Create Tenant
            </button>
          </div>

          {tenants.length === 0 ? (
            <div className="sa-section-empty">
              No tenants yet. Create your first tenant to get started.
            </div>
          ) : (
            <table className="sa-table">
              <thead>
                <tr>
                  <th>status</th>
                  <th>schema name</th>
                  <th>name</th>
                  <th>domain</th>
                  <th>created</th>
                  <th>duration</th>
                  <th>users</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr key={tenant.id}>
                    <td>
                      <span
                        className={`sa-badge ${tenant.is_active !== false ? "sa-badge--active" : "sa-badge--inactive"}`}
                        title={tenant.is_active !== false ? "Active" : "Inactive"}
                      >
                        <span className="sr-only">
                          {tenant.is_active !== false ? "Active" : "Inactive"}
                        </span>
                      </span>
                    </td>
                    <td>{tenant.schema_name}</td>
                    <td>{tenant.name}</td>
                    <td>{tenant.domain || "No domain"}</td>
                    <td>
                      {tenant.created_on
                        ? new Date(tenant.created_on).toLocaleDateString(
                            "de-DE",
                          )
                        : "N/A"}
                    </td>
                    <td>
                      {tenant.created_on
                        ? formatDuration(tenant.created_on)
                        : "N/A"}
                    </td>

                    <td>{tenant.user_count || 0}</td>
                    <td>
                      <button
                        onClick={() => navigate(`/tenants/${tenant.id}`)}
                        className="sa-btn sa-btn--detail"
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* The backup sidecar owns the backups; the backend container can
            neither see nor make them, so the dashboard only says where they are. */}
        <div className="sa-section sa-section--spaced">
          <div className="sa-section-header">
            <h2 className="sa-section-title">{t("platform.backups.title")}</h2>
          </div>
          <p className="sa-section-note">{t("platform.backups.note")}</p>
        </div>
      </div>

      {showCreateModal && (
        <CreateTenantModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            refetchTenants();
          }}
        />
      )}
    </div>
  );
}

function formatDuration(dateStr: string): string {
  const createdDate = new Date(dateStr);
  const today = new Date();
  const diffTime = Math.abs(today.getTime() - createdDate.getTime());
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "1 day";
  if (diffDays < 30) return `${diffDays} days`;
  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30);
    return months === 1 ? "1 month" : `${months} months`;
  }
  const years = Math.floor(diffDays / 365);
  return years === 1 ? "1 year" : `${years} years`;
}
