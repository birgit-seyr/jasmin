import { useQuery } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import axiosService from "@shared/services/api";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import CreateAdminModal from "@features/platform/modals/CreateAdminModal";
import CreateUserModal from "@features/platform/modals/CreateUserModal";
import RoleChipSelector from "@features/platform/components/RoleChipSelector";
import { STATUS_COLORS } from "@features/platform/userManagement";

interface Domain {
  domain: string;
  is_primary: boolean;
}

interface TenantDetail {
  id: number;
  schema_name: string;
  name: string;
  tenant_language: string | null;
  created_on: string;
  is_active: boolean;
  domains?: Domain[];
}

interface TenantUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  roles: string[];
  is_active: boolean;
  account_status: string;
  date_joined: string;
  last_login: string | null;
}

interface TenantUsersResponse {
  admin_users: TenantUser[];
  other_users: TenantUser[];
}

export default function TenantDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [showCreateAdmin, setShowCreateAdmin] = useState(false);
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [togglingActive, setTogglingActive] = useState(false);

  // The super-admin endpoints aren't part of the tenant-scoped orval
  // schema, so we hit them through ``axiosService`` directly. TanStack
  // Query handles caching, deduplication, cancellation on ``id``
  // change, and post-mutation refetch — replacing the previous
  // ``useEffect`` + ``setLoading`` + ``useCallback`` machinery that
  // raced the two fetches against each other on rapid navigation.
  const tenantQuery = useQuery<TenantDetail>({
    queryKey: ["super-admin", "tenant", id],
    enabled: !!id,
    queryFn: async () => {
      const response = await axiosService.get(SUPER_ADMIN_ENDPOINTS.tenant(id!));
      return response.data as TenantDetail;
    },
  });

  const usersQuery = useQuery<TenantUsersResponse>({
    queryKey: ["super-admin", "tenant", id, "users"],
    enabled: !!id,
    queryFn: async () => {
      const response = await axiosService.get(
        SUPER_ADMIN_ENDPOINTS.tenantUsers(id!),
      );
      return response.data as TenantUsersResponse;
    },
  });

  const tenant = tenantQuery.data ?? null;
  const adminUsers = usersQuery.data?.admin_users ?? [];
  const otherUsers = usersQuery.data?.other_users ?? [];
  const usersLoading = usersQuery.isPending;
  // Existing UI only shows the "Loading..." splash on the tenant
  // fetch — keep that contract by deriving from tenantQuery alone.
  const loading = tenantQuery.isPending;

  const refetchUsers = () => {
    void usersQuery.refetch();
  };

  // Activate / deactivate the tenant. ``is_active`` is the operator
  // kill-switch enforced server-side (TenantActiveMiddleware): once off,
  // every request against the tenant's schema returns 403 — login, token
  // refresh, and all APIs — so deactivating locks every user out
  // immediately. Hence the confirm on the destructive direction only.
  const toggleActive = async () => {
    if (!tenant || !id) return;
    const next = !tenant.is_active;
    if (
      !next &&
      !window.confirm(
        `Deactivate "${tenant.name}"? Every user of this tenant will be ` +
          `locked out immediately (login, token refresh, and all API calls ` +
          `return 403) until you re-activate it here.`,
      )
    ) {
      return;
    }
    setTogglingActive(true);
    try {
      await axiosService.patch(SUPER_ADMIN_ENDPOINTS.tenant(id), {
        is_active: next,
      });
      await tenantQuery.refetch();
    } catch (error) {
      notify.error(
        getErrorMessage(error, "Failed to change tenant active state"),
      );
    } finally {
      setTogglingActive(false);
    }
  };

  if (loading) {
    return <div className="sa-section-empty">Loading...</div>;
  }

  if (!tenant) {
    return <div className="sa-section-empty">Tenant not found</div>;
  }

  return (
    <div className="sa-page">
      <header className="sa-app-header sa-detail-header">
        <button
          onClick={() => navigate("/")}
          className="sa-btn sa-btn--cancel"
        >
          ← Back
        </button>
        <h1 className="sa-detail-title">{tenant.name}</h1>
      </header>

      <div className="sa-page-content--narrow">
        <div className="sa-card sa-card--lg">
          <h2 className="sa-detail-heading">Tenant Details</h2>

          <div className="sa-detail-grid">
            <DetailRow label="Schema Name" value={tenant.schema_name} />
            <DetailRow label="Name" value={tenant.name} />
            <DetailRow
              label="Created"
              value={new Date(tenant.created_on).toLocaleString()}
            />
            <DetailRow
              label="Main Language"
              value={tenant.tenant_language || "—"}
            />
            <DetailRow
              label="Status"
              value={
                <span className="sa-status-control">
                  <span
                    className={`sa-badge ${tenant.is_active ? "sa-badge--active" : "sa-badge--inactive"}`}
                  >
                    {tenant.is_active ? "Active" : "Inactive"}
                  </span>
                  <button
                    onClick={toggleActive}
                    disabled={togglingActive}
                    className={`sa-btn ${tenant.is_active ? "sa-btn--danger" : "sa-btn--success"}`}
                  >
                    {togglingActive
                      ? "..."
                      : tenant.is_active
                        ? "Deactivate"
                        : "Activate"}
                  </button>
                </span>
              }
            />
          </div>

          <h3 className="sa-subheading">Domains</h3>
          <div className="sa-domain-list">
            {tenant.domains?.map((domain) => (
              <div key={domain.domain} className="sa-domain-row">
                <span>{domain.domain}</span>
                {domain.is_primary && (
                  <span className="sa-domain-primary">Primary</span>
                )}
              </div>
            ))}
          </div>

          <h3 className="sa-subheading">Admin Users</h3>
          <div className="sa-toolbar">
            <button
              onClick={() => setShowCreateAdmin(true)}
              className="sa-btn sa-btn--primary"
            >
              + Create Admin User
            </button>
            <button
              onClick={() => setShowCreateUser(true)}
              className="sa-btn sa-btn--detail"
            >
              + Create User
            </button>
          </div>

          {usersLoading ? (
            <div className="text-muted">Loading users...</div>
          ) : (
            <>
              <UserTable
                users={adminUsers}
                emptyText="No admin users found"
                tenantId={id!}
                onRolesUpdated={refetchUsers}
              />

              <h3 className="sa-subheading">Other Users</h3>
              <UserTable
                users={otherUsers}
                emptyText="No other users found"
                tenantId={id!}
                onRolesUpdated={refetchUsers}
              />
            </>
          )}
        </div>
      </div>

      {showCreateAdmin && id && (
        <CreateAdminModal
          tenantId={id}
          onClose={() => setShowCreateAdmin(false)}
          onSuccess={() => {
            setShowCreateAdmin(false);
            refetchUsers();
          }}
        />
      )}

      {showCreateUser && id && (
        <CreateUserModal
          tenantId={id}
          onClose={() => setShowCreateUser(false)}
          onSuccess={() => {
            setShowCreateUser(false);
            refetchUsers();
          }}
        />
      )}
    </div>
  );
}

interface DetailRowProps {
  label: string;
  value: ReactNode;
}

function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div className="sa-detail-row">
      <strong className="sa-detail-row-label">{label}:</strong>
      <span>{value}</span>
    </div>
  );
}

function UserTable({
  users,
  emptyText,
  tenantId,
  onRolesUpdated,
}: {
  users: TenantUser[];
  emptyText: string;
  tenantId: string;
  onRolesUpdated: () => void;
}) {
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [savingRoles, setSavingRoles] = useState(false);
  const [editedRoles, setEditedRoles] = useState<string[]>([]);

  if (users.length === 0) {
    return <div className="sa-table-empty">{emptyText}</div>;
  }

  const startEditing = (user: TenantUser) => {
    setEditingUserId(user.id);
    setEditedRoles([...(Array.isArray(user.roles) ? user.roles : [])]);
  };

  const toggleRole = (role: string) => {
    setEditedRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  const saveRoles = async (userId: string) => {
    setSavingRoles(true);
    try {
      await axiosService.patch(
        SUPER_ADMIN_ENDPOINTS.tenantUserRoles(tenantId, userId),
        { roles: editedRoles },
      );
      setEditingUserId(null);
      onRolesUpdated();
    } catch (error) {
      notify.error(getErrorMessage(error, "Failed to update roles"));
    } finally {
      setSavingRoles(false);
    }
  };

  return (
    <div className="sa-table-scroll">
      <table className="sa-table">
        <thead>
          <tr>
            <th>Active</th>
            <th>Name</th>
            <th>Email</th>
            <th>Roles</th>
            <th>Status</th>
            <th>Joined</th>
            <th>Last Login</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => {
            const statusStyle =
              STATUS_COLORS[user.account_status] || STATUS_COLORS.inactive;
            return (
              <tr key={user.id}>
                <td>
                  <span
                    className={`sa-status-dot ${user.is_active ? "sa-status-dot--on" : "sa-status-dot--off"}`}
                    title={user.is_active ? "Active" : "Inactive"}
                  />
                </td>
                <td>
                  {user.first_name} {user.last_name}
                </td>
                <td>{user.email}</td>
                <td>
                  {editingUserId === user.id ? (
                    <div className="sa-roles-edit">
                      <RoleChipSelector
                        selectedRoles={editedRoles}
                        onToggle={toggleRole}
                      />
                      <button
                        onClick={() => saveRoles(user.id)}
                        disabled={savingRoles}
                        className="sa-icon-btn sa-icon-btn--save"
                      >
                        {savingRoles ? "..." : "✓"}
                      </button>
                      <button
                        onClick={() => setEditingUserId(null)}
                        className="sa-icon-btn sa-icon-btn--cancel"
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <div
                      className="sa-roles-view"
                      role="button"
                      tabIndex={0}
                      onClick={() => startEditing(user)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          startEditing(user);
                        }
                      }}
                      title="Click to edit roles"
                    >
                      {(Array.isArray(user.roles) ? user.roles : []).length >
                      0 ? (
                        user.roles.map((role) => (
                          <span key={role} className="sa-role-chip">
                            {role}
                          </span>
                        ))
                      ) : (
                        <span className="sa-role-empty">No roles</span>
                      )}
                    </div>
                  )}
                </td>

                <td>
                  <span
                    className="sa-status-pill"
                    style={{
                      background: statusStyle.bg,
                      color: statusStyle.color,
                    }}
                  >
                    {user.account_status}
                  </span>
                </td>
                <td>{new Date(user.date_joined).toLocaleDateString()}</td>
                <td>
                  {user.last_login
                    ? new Date(user.last_login).toLocaleDateString()
                    : "N/A"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
