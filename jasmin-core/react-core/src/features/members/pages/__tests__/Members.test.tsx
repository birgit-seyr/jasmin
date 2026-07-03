// Members is a heavy page: it builds a ~20-column EditableTable, wires up six
// modals (admin-confirm, reject, user-info, logging, member-emails,
// coop-shares, invite), reads a pile of column/format hooks from the @hooks
// barrel, and owns its data via ``useCommissioningMembersList``. This is a
// render-loop SMOKE TEST per the CLAUDE.md "heavy page" rule — we mock the API
// boundary + every heavy child/modal so the mount is deterministic, then assert
// (a) it mounts and shows the heading, and (b) it doesn't commit in a loop.
//
// Strategy: vi.mock the generated API module (so no network), the @hooks barrel
// (so column/format/modal hooks return stable stubs), AuthContext + useRoles
// (auth), @shared/tables (EditableTable stub; gatedByPermission/wrapApiFunctions
// kept as passthroughs the page calls at module/render time), @shared/modals,
// @features/members/modals + the two source-module modals, @shared/ui
// SummaryStatsCard, and the two app modal hooks. The page imported AFTER mocks.

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { profileRenders, flushMicrotasks } from "@/test/profileRenders";

// ── react-i18next (full surface — Trans + initReactI18next are load-bearing) ──
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// ── @hooks/index barrel — every hook the page destructures from it ────────────
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  // Built once → reference-stable across renders, so the page's column useMemo
  // (which depends on these) doesn't rebuild every commit.
  const tenant = makeUseTenantMock();
  const noop = () => {};
  const activeStatusColumn = {
    title: "active",
    dataIndex: "is_approved",
    key: "is_approved",
  };
  const noteColumn = { title: "note", dataIndex: "note", key: "note" };
  // useContactColumns returns one column descriptor per contact field; the
  // page spreads each into the columns array, so each must be a plain object.
  const contactColumns = {
    firstName: { title: "first_name", dataIndex: "first_name", key: "first_name" },
    lastName: { title: "last_name", dataIndex: "last_name", key: "last_name" },
    companyName: { title: "company_name", dataIndex: "company_name", key: "company_name" },
    email: { title: "email", dataIndex: "email", key: "email" },
    address: { title: "address", dataIndex: "address", key: "address" },
    zipCode: { title: "zip_code", dataIndex: "zip_code", key: "zip_code" },
    city: { title: "city", dataIndex: "city", key: "city" },
    country: { title: "country", dataIndex: "country", key: "country" },
  };
  const rowSelection = {
    selectedRowKeys: [] as React.Key[],
    setSelectedRowKeys: noop,
    onSelectedRowsChange: noop,
    rowSelection: {},
    clearSelection: noop,
  };
  const userInfoModal = {
    isUserInfoModalOpen: false,
    selectedUserRecord: null,
    handleOpenUserInfoModal: noop,
    handleCloseUserInfoModal: noop,
    getUserStatus: () => ({ variant: "userNotInvited", key: "status_no_user" }),
    getUserStatusSorter: () => 0,
  };
  return {
    useTenant: () => tenant,
    useActiveStatusColumn: () => activeStatusColumn,
    useContactColumns: () => contactColumns,
    useDateFormat: () => ({
      formatDate: (v: unknown) => (v ? String(v) : ""),
      formatDateWithFallback: (v: unknown, fallback = "-") =>
        v ? String(v) : fallback,
      formatDateForAPI: (v: unknown) => (v ? String(v) : null),
    }),
    useNoteColumn: () => ({ noteColumn }),
    useNumberFormat: () => ({ format: (value: unknown) => String(value ?? "") }),
    useTableRowSelection: () => rowSelection,
    useUserInfoModal: () => userInfoModal,
    useInvalidateAfterTableMutation: () => ({
      onSaveSuccess: vi.fn(),
      onDeleteSuccess: vi.fn(),
      recentlyAddedIds: new Set<unknown>(),
    }),
  };
});

// ── Auth ──────────────────────────────────────────────────────────────────────
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn(), user: { roles: ["office"] } }),
}));
vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true, isAdmin: false, isMember: false }),
}));

// ── API boundary — every named export the page imports from this module ───────
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  // Mount data hook — must return an array under ``data`` (page coerces to []).
  useCommissioningMembersList: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
  getCommissioningMembersListQueryKey: () => ["members", "list"],
  commissioningMembersCreate: vi.fn().mockResolvedValue({}),
  commissioningMembersDestroy: vi.fn().mockResolvedValue({}),
  commissioningMembersPartialUpdate: vi.fn().mockResolvedValue({}),
  commissioningMembersSendInvitationCreate: vi.fn().mockResolvedValue({}),
}));
vi.mock("@shared/api/generated/auth/auth", () => ({
  authAdminUsersPartialUpdate: vi.fn().mockResolvedValue({}),
}));

// ── @shared/tables — EditableTable stub; keep helpers as real passthroughs ────
// gatedByPermission is called during render (spread into ``permissions``) and
// wrapApiFunctions inside a useMemo — both must be callable, so we return plain
// functions rather than testid stubs.
vi.mock("@shared/tables", () => ({
  EditableTable: () => <div data-testid="editable-table" />,
  gatedByPermission: () => ({}),
  gatedByPermissionOnlyEdit: () => ({}),
  wrapApiFunctions: (fns: unknown) => fns,
  // Called during column build — return a minimal column config.
  adminConfirmationColumn: () => ({
    key: "admin_confirmed",
    dataIndex: "admin_confirmed",
  }),
}));

// ── Modals (generic + member-specific) — respect their visible/open prop ──────
vi.mock("@shared/modals", () => ({
  InviteUserModal: ({ open }: { open?: boolean }) =>
    open ? <div data-testid="invite-user-modal" /> : null,
  LoggingModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="logging-modal" /> : null,
  UserInfoModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="user-info-modal" /> : null,
}));
vi.mock("@features/members/modals", () => ({
  CoopSharesModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="coop-shares-modal" /> : null,
  MemberEmailsModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="member-emails-modal" /> : null,
  CancelMembershipModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="cancel-membership-modal" /> : null,
  MemberBankDetailsModal: ({ open }: { open?: boolean }) =>
    open ? <div data-testid="member-bank-details-modal" /> : null,
}));
// Imported from source modules directly (named exports) to dodge a chunk cycle.
vi.mock("@features/members/modals/AdminConfirmationModalMembers", () => ({
  AdminConfirmationModalMembers: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="admin-confirmation-modal" /> : null,
}));
vi.mock("@features/members/modals/RejectMemberModal", () => ({
  RejectMemberModal: ({ isOpen }: { isOpen?: boolean }) =>
    isOpen ? <div data-testid="reject-member-modal" /> : null,
}));
vi.mock("@features/members/modals/ExportCsvMemberRegister", () => ({
  default: ({ open }: { open?: boolean }) =>
    open ? <div data-testid="export-csv-member-register" /> : null,
}));

// ── @shared/ui — SummaryStatsCard + the bits used inside column renderers ─────
// The column factory references LinkButton/StatusButton/ToolTipIcon/etc. inside
// ``render`` callbacks that the stubbed EditableTable never invokes, but the
// module-level imports still resolve, so we provide light stubs for all of them.
vi.mock("@shared/ui", () => ({
  SummaryStatsCard: () => <div data-testid="summary-stats-card" />,
  DownloadCsvTemplateButton: () => <div data-testid="download-csv-template" />,
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer-text">{children}</div>
  ),
  LinkButton: () => <span data-testid="link-button" />,
  StatusButton: () => <span data-testid="status-button" />,
  ToolTipIcon: () => <span data-testid="tooltip-icon" />,
}));

// ── App modal hooks ───────────────────────────────────────────────────────────
vi.mock("@features/members/hooks/modals/useAdminConfirmationModalMembers", () => ({
  useAdminConfirmationModalMembers: () => ({
    isAdminConfirmationModalOpen: false,
    selectedMemberForConfirmation: null,
    loading: false,
    handleOpenAdminConfirmationModal: vi.fn(),
    handleCloseAdminConfirmationModal: vi.fn(),
    confirmMember: vi.fn().mockResolvedValue(undefined),
    getAdminStatus: () => ({ variant: "adminPending", key: "admin_pending" }),
    getAdminStatusSorter: () => 0,
  }),
}));
vi.mock("@features/members/hooks/modals/useRejectMemberModal", () => ({
  useRejectMemberModal: () => ({
    isRejectModalOpen: false,
    selectedMemberForRejection: null,
    loading: false,
    reason: "",
    setReason: vi.fn(),
    handleOpenRejectModal: vi.fn(),
    handleCloseRejectModal: vi.fn(),
    rejectMember: vi.fn().mockResolvedValue(undefined),
  }),
}));

// ── Import under test (AFTER the mocks) ───────────────────────────────────────
import Members from "../Members";

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe("Members (render-loop smoke test)", () => {
  it("renders without crashing", async () => {
    const client = makeQueryClient();
    render(
      <QueryClientProvider client={client}>
        <Members />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("members.list_members")).toBeInTheDocument();
    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
  });

  // Members orchestrates a ~20-column table + seven modals + a dozen barrel
  // hooks. A healthy mount commits a handful of times (initial + memo settling);
  // a real setState-in-render loop produces thousands. 80 is a loose ceiling
  // (10× headroom) that still catches the bug.
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    const profiler = profileRenders();
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        {profiler.wrap(<Members />, "members")}
      </QueryClientProvider>,
    );

    await screen.findByText("members.list_members");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
