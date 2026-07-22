import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { useAuth } from "@shared/contexts/AuthContext";
import { getErrorMessage } from "@shared/utils/apiError";
import { notify } from "@shared/utils";
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

interface Backup {
  filename: string;
  size_human: string;
  created_at: string;
}

export default function SuperAdminDashboard() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
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
  // refetch — replacing the previous ``useEffect`` + ``setLoading``
  // machinery.
  const tenantsQuery = useQuery<Tenant[]>({
    queryKey: ["super-admin", "tenants"],
    enabled: authorized,
    queryFn: async () => {
      const response = await axiosService.get(SUPER_ADMIN_ENDPOINTS.tenants);
      return response.data as Tenant[];
    },
  });

  const backupsQuery = useQuery<Backup[]>({
    queryKey: ["super-admin", "backups"],
    enabled: authorized,
    // Backups may not be configured yet — swallow errors to an empty list.
    queryFn: async () => {
      try {
        const response = await axiosService.get(SUPER_ADMIN_ENDPOINTS.backups);
        return (response.data.backups || []) as Backup[];
      } catch {
        return [];
      }
    },
  });

  const triggerBackupMutation = useMutation({
    mutationFn: async () => {
      await axiosService.post(SUPER_ADMIN_ENDPOINTS.triggerBackup);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["super-admin", "backups"],
      });
    },
    onError: (error) => {
      console.error("Operation failed:", error);
      notify.error(getErrorMessage(error, "Failed to load data"));
    },
  });

  const tenants = tenantsQuery.data ?? [];
  const backups = backupsQuery.data ?? [];
  const loading = tenantsQuery.isPending;
  const error = tenantsQuery.isError
    ? getErrorMessage(tenantsQuery.error, "Failed to load tenants")
    : null;
  const backupLoading = backupsQuery.isPending;
  const backupTriggering = triggerBackupMutation.isPending;

  const refetchTenants = () => {
    void tenantsQuery.refetch();
  };

  const triggerBackup = () => {
    triggerBackupMutation.mutate();
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
            <p className="sa-stat-value" style={{ color: "#333" }}>
              {tenants.length}
            </p>
          </div>

          <div className="sa-card">
            <h3 className="sa-stat-label">Active Tenants</h3>
            <p className="sa-stat-value" style={{ color: "#4caf50" }}>
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
                      ></span>
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

        {/* Database Backups */}
        <div className="sa-section" style={{ marginTop: "30px" }}>
          <div className="sa-section-header">
            <h2 className="sa-section-title">Database Backups</h2>
            <button
              onClick={triggerBackup}
              disabled={backupTriggering}
              className="sa-btn sa-btn--success"
            >
              {backupTriggering ? "Creating backup..." : "Backup Now"}
            </button>
          </div>

          {backupLoading ? (
            <div className="sa-section-empty">Loading backups...</div>
          ) : backups.length === 0 ? (
            <div className="sa-section-empty">
              No backups found. Trigger a backup or configure the backup
              container.
            </div>
          ) : (
            <table className="sa-table">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Size</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {backups.map((backup) => (
                  <tr key={backup.filename}>
                    <td>
                      <code style={{ fontSize: "13px" }}>
                        {backup.filename}
                      </code>
                    </td>
                    <td>{backup.size_human}</td>
                    <td>
                      {new Date(backup.created_at).toLocaleString("de-DE")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="sa-section-footer">
            Backups are encrypted (AES-256) and automatically pruned after 30
            days.
          </div>
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
