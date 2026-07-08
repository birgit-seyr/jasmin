import { EditOutlined, MailOutlined, PlusOutlined } from "@ant-design/icons";
import {  Badge, Button, Space, Typography } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { memo, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ROLES, type Role } from "@shared/auth/roles";
import { RoleTags } from "@shared/auth";
import { InviteUserModal } from '@shared/modals';
import { EditUserRolesModal } from '@features/configuration/modals';
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText } from "@shared/ui";
import { getErrorMessage } from "@shared/utils/apiError";
import { useDateFormat } from "@hooks/index";
import {
  authAdminUsersPartialUpdate,
  authAdminUsersResendInvitationCreate,
  getAuthAdminUsersListQueryKey,
  useAuthAdminUsersList,
} from "@shared/api/generated/auth/auth";
import type { AdminUserRow } from "@shared/api/generated/models";
import { notify } from "@shared/utils";

const { Text } = Typography;

type UserRow = Omit<AdminUserRow, "account_status"> &
  TableRecord & {
    account_status:
      | "active"
      | "pending_approval"
      | "pending_invitation"
      | "inactive";
  };

const STAFF_ROLES: Role[] = [
  ROLES.ADMIN,
  ROLES.MANAGEMENT,
  ROLES.OFFICE,
  ROLES.STAFF,
  ROLES.GARDENER,
];

const STATUS_BADGE_COLOR: Record<UserRow["account_status"], string> = {
  active: "success",
  pending_approval: "warning",
  pending_invitation: "processing",
  inactive: "default",
};

// Display order for the status sorter: pending items first (need
// attention), then active, then inactive (no work needed).
const STATUS_SORT_ORDER: Record<UserRow["account_status"], number> = {
  pending_approval: 0,
  pending_invitation: 1,
  active: 2,
  inactive: 3,
};


interface UsersSectionProps {
  titleKey: string;
  rows: UserRow[];
  columns: EditableColumnConfig<TableRecord>[];
  loading: boolean;
}

// Each section is memoized so the parent re-rendering (e.g. resendingId
// flips, modals open/close) doesn't force all three EditableTables to
// re-render. Each section only re-renders when its own rows / columns /
// loading change.
const UsersSection = memo(function UsersSection({
  titleKey,
  rows,
  columns,
  loading,
}: UsersSectionProps) {
  const { t } = useTranslation();
  // UserRow already intersects TableRecord, so this is a plain widening.
  const data = useMemo<TableRecord[]>(() => rows, [rows]);
  return (
    <div style={{ marginBottom: 32 }}>
      <h4>
        {t(titleKey)} ({rows.length})
      </h4>
      <EditableTable
        columns={columns}
        initialData={data}
        loading={loading}
        permissions={READ_ONLY_PERMISSION}
        pagination={true}
        showSearchBar={true}
      />
    </div>
  );
});

export default function ConfigurationUsers() {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const [resendingId, setResendingId] = useState<string | null>(null);

  const [roleEditUser, setRoleEditUser] = useState<UserRow | null>(null);

  // React Query — failures route through the global queryCache.onError
  // toast. Writes call `fetchUsers()` to invalidate and refetch.
  const { data: rawUsers, isFetching: loading } = useAuthAdminUsersList();
  const users = useMemo<UserRow[]>(
    () => (rawUsers ?? []) as UserRow[],
    [rawUsers],
  );
  const fetchUsers = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getAuthAdminUsersListQueryKey(),
    });
  }, [queryClient]);

  // ---- Resend invitation -----------------------------------------------
  const handleResend = async (userId: string) => {
    setResendingId(userId);
    try {
      await authAdminUsersResendInvitationCreate(userId);
      notify.success(t("users.invitation_resent"));
      fetchUsers();
    } catch (error) {
      console.error("Operation failed:", error);
      notify.error(t("users.resend_failed"));
    } finally {
      setResendingId(null);
    }
  };

  // ---- Toggle active/inactive -------------------------------------------
  const handleToggleActive = async (u: UserRow) => {
    const next = u.account_status === "active" ? "inactive" : "active";
    try {
      await authAdminUsersPartialUpdate(u.id, { account_status: next });
      notify.success(
        next === "inactive"
          ? t("users.deactivated")
          : t("users.activated"),
      );
      fetchUsers();
    } catch (err: unknown) {
      notify.error(
        getErrorMessage(
          err,
          t("users.toggle_active_failed"),
        ),
      );
    }
  };

  // ---- Edit roles -------------------------------------------------------
  const openRoleEditor = (u: UserRow) => {
    setRoleEditUser(u);
  };

  // ---- Splitting users into three buckets ------------------------------
  const { staffUsers, customerUsers, memberOnlyUsers } = useMemo(() => {
    const staff: UserRow[] = [];
    const customers: UserRow[] = [];
    const memberOnly: UserRow[] = [];
    for (const u of users) {
      const roles = u.roles || [];
      const isStaff = roles.some((r) => (STAFF_ROLES as string[]).includes(r));
      const isCustomer = roles.includes(ROLES.CUSTOMER);
      const isMember = roles.includes(ROLES.MEMBER);

      if (isStaff) staff.push(u);
      if (isCustomer) customers.push(u);
      if (isMember && !isStaff && !isCustomer) memberOnly.push(u);
    }
    // Sort each bucket so rows that need attention (pending) come first
    // and active/inactive rows (no work needed) come last. Within the same
    // status, sort alphabetically by last name.
    const sortByStatusThenName = (a: UserRow, b: UserRow) => {
      const diff =
        (STATUS_SORT_ORDER[a.account_status] ?? 99) -
        (STATUS_SORT_ORDER[b.account_status] ?? 99);
      if (diff !== 0) return diff;
      const na = `${a.last_name || ""} ${a.first_name || ""}`
        .trim()
        .toLocaleLowerCase();
      const nb = `${b.last_name || ""} ${b.first_name || ""}`
        .trim()
        .toLocaleLowerCase();
      return na.localeCompare(nb);
    };
    staff.sort(sortByStatusThenName);
    customers.sort(sortByStatusThenName);
    memberOnly.sort(sortByStatusThenName);
    return {
      staffUsers: staff,
      customerUsers: customers,
      memberOnlyUsers: memberOnly,
    };
  }, [users]);

  // ---- Shared columns ---------------------------------------------------
  const buildColumns = useCallback(
    (): EditableColumnConfig<TableRecord>[] => [
      {
        title: <>{t("users.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        width: "14em",
        readOnly: true,
        render: (_: unknown, record: TableRecord) => {
          const u = record as UserRow;
          const name = `${u.first_name || ""} ${u.last_name || ""}`.trim();
          return name || "—";
        },
      },
      {
        title: <>{t("users.email")}</>,
        dataIndex: "email",
        key: "email",
        width: "15em",
        readOnly: true,
      },
      {
        title: <>{t("users.status")}</>,
        dataIndex: "account_status",
        key: "account_status",
        inputType: "text",
        width: "10em",
        sortable: true,
        readOnly: true,

        render: (s: unknown) => {
          const status = s as UserRow["account_status"];
          const color = STATUS_BADGE_COLOR[status] ?? "default";
          const label = status ? t(`users.status_${status}`) : "";
          return <Badge status={color as never} text={label} />;
        },
      },
      {
        title: <>{t("users.roles")}</>,
        dataIndex: "roles",
        key: "roles",
        width: "20em",
        readOnly: true,
        render: (_: unknown, record: TableRecord) => {
          const u = record as UserRow;
          return (
            <Space size={4} wrap>
              <Button
                type="primary"
                size="small"
                icon={<EditOutlined />}
                aria-label={t("users.edit_roles")}
                onClick={() => openRoleEditor(u)}
              />
              <RoleTags roles={u.roles} />
            </Space>
          );
        },
      },
      {
        title: <>{t("users.active_since")}</>,
        dataIndex: "activated_at",
        key: "activated_at",
        width: "8em",
        readOnly: true,
        sortable: true,
        sorter: (a: TableRecord, b: TableRecord) => {
          const va = (a as UserRow).activated_at;
          const vb = (b as UserRow).activated_at;
          if (!va && !vb) return 0;
          if (!va) return 1;
          if (!vb) return -1;
          return new Date(va).getTime() - new Date(vb).getTime();
        },
        render: (v: unknown) =>
          v ? formatDate(v as string) : <Text type="secondary">—</Text>,
      },
      {
        title: <>{t("users.last_login")}</>,
        dataIndex: "last_login",
        key: "last_login",
        width: "8em",
        readOnly: true,
        sortable: true,
        sorter: (a: TableRecord, b: TableRecord) => {
          const va = (a as UserRow).last_login;
          const vb = (b as UserRow).last_login;
          if (!va && !vb) return 0;
          if (!va) return 1;
          if (!vb) return -1;
          return new Date(va).getTime() - new Date(vb).getTime();
        },
        render: (v: unknown) =>
          v ? (
            formatDate(v as string)
          ) : (
            <Text type="secondary">{t("users.never")}</Text>
          ),
      },
      {
        title: <>{t("users.inactivated_at")}</>,
        dataIndex: "inactivated_at",
        key: "inactivated_at",
        width: "8em",
        readOnly: true,
        sortable: true,
        sorter: (a: TableRecord, b: TableRecord) => {
          const va = (a as UserRow).inactivated_at;
          const vb = (b as UserRow).inactivated_at;
          if (!va && !vb) return 0;
          if (!va) return 1;
          if (!vb) return -1;
          return new Date(va).getTime() - new Date(vb).getTime();
        },
        render: (v: unknown, record: TableRecord) => {
          const u = record as UserRow;
          if (u.account_status !== "inactive")
            return <Text type="secondary">—</Text>;
          return v ? formatDate(v as string) : <Text type="secondary">—</Text>;
        },
      },
      {
        title: <>{t("users.actions")}</>,
        dataIndex: "_actions",
        key: "_actions",
        width: "14em",
        readOnly: true,
        render: (_: unknown, record: TableRecord) => {
          const u = record as UserRow;
          const isPendingInvite = u.account_status === "pending_invitation";
          const isActive = u.account_status === "active";
          const isInactive = u.account_status === "inactive";
          const invitationExpired =
            !!u.invitation_expires_at &&
            new Date(u.invitation_expires_at).getTime() < Date.now();
          const expiryDate = u.invitation_expires_at
            ? formatDate(u.invitation_expires_at)
            : null;
          return (
            <Space size={4} wrap>
              {isPendingInvite &&
                t("users.invitation_expires_on") +
                  ` ${expiryDate}`}
              {isPendingInvite && (
                <Button
                  size="small"
                  icon={<MailOutlined />}
                  loading={resendingId === u.id}
                  disabled={invitationExpired}
                  onClick={() => handleResend(u.id)}
                >
                  {t("users.resend_invitation")}
                </Button>
              )}
              {(isActive || isInactive) && (
                <Button
                  size="small"
                  danger={isActive}
                  onClick={() => handleToggleActive(u)}
                >
                  {isActive
                    ? t("users.deactivate")
                    : t("users.activate")}
                </Button>
              )}
            </Space>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, formatDate, resendingId],
  );

  const columns = useMemo(() => buildColumns(), [buildColumns]);

  return (
    <div>
      <h1>{t("users.title")}</h1>
      <div style={{ marginBottom: "2em", marginTop: "2em" }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
        >
          {t("users.invite_user")}
        </Button>
      </div>

      <UsersSection
        titleKey="users.section_staff"
        rows={staffUsers}
        columns={columns}
        loading={loading}
      />
      <UsersSection
        titleKey="users.section_customers"
        rows={customerUsers}
        columns={columns}
        loading={loading}
      />
      <UsersSection
        titleKey="users.section_members_only"
        rows={memberOnlyUsers}
        columns={columns}
        loading={loading}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.users")}
      </ExplainerText>

      <InviteUserModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => fetchUsers()}
        defaultRoles={[ROLES.STAFF]}
        disallowedRoles={[ROLES.MEMBER]}
      />

      <EditUserRolesModal
        user={roleEditUser}
        onClose={() => setRoleEditUser(null)}
        onSaved={fetchUsers}
      />
    </div>
  );
}
