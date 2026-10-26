/**
 * ``CoopSharesModal`` grid wiring for the tenant's onboarding mode: ``paid_at``
 * is editable only while the mode is on, and its edit cell starts from the
 * calendar day in the display format although the API sends a datetime. A share
 * is shown and saved at the value it was subscribed at; only a new row takes
 * the tenant's current value.
 *
 * Boundary mocked: react-i18next, the generated coop share API, the roles,
 * the ``@hooks/index`` barrel, the confirm / transfer modals and the
 * EditableTable (a stub that records its props). The real AntD Modal renders.
 */
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const modalState = vi.hoisted(() => ({
  onboardingMode: false,
  tableProps: null as Record<string, unknown> | null,
  rows: [] as Record<string, unknown>[],
  minShares: undefined as number | undefined,
  maxShares: undefined as number | undefined,
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningCoopSharesCreate: vi.fn(),
  commissioningCoopSharesDestroy: vi.fn(),
  commissioningCoopSharesPartialUpdate: vi.fn(),
  getCommissioningCoopSharesListQueryKey: () => ["coop_shares"],
  getCommissioningMembersListQueryKey: () => ["members"],
  useCommissioningCoopSharesConfirmCreate: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useCommissioningCoopSharesList: () => ({
    data: modalState.rows,
    isFetching: false,
  }),
  useCommissioningCoopSharesReverseTransferCreate: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true }),
}));

vi.mock("@shared/tables", () => ({
  adminConfirmationColumn: () => ({
    key: "admin_confirmed",
    dataIndex: "admin_confirmed",
  }),
  EditableTable: (props: Record<string, unknown>) => {
    modalState.tableProps = props;
    return <div data-testid="editable-table" />;
  },
  gatedByPermission: () => ({}),
  wrapApiFunctions: (functions: unknown) => functions,
}));

vi.mock("../AdminConfirmationModalCoopShares", () => ({
  default: () => null,
}));
vi.mock("../CoopShareTransferModal", () => ({ default: () => null }));
vi.mock("@shared/modals/ModalCloseFooter", () => ({ default: () => null }));
vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("@hooks/index", () => {
  const noteColumn = { key: "note", dataIndex: "note" };
  const formatDate = (value: unknown) =>
    value ? dayjs(value as string).format("DD.MM.YYYY") : null;
  const invalidateAfterMutation = {
    onSaveSuccess: () => {},
    onDeleteSuccess: () => {},
  };
  return {
    useCurrency: () => ({
    currencySymbol: "€",
    formatCurrency: (amount: number) => `${amount} €`,
  }),
    useDateFormat: () => ({ formatDate, formatDateWithColor: formatDate }),
    useInvalidateAfterTableMutation: () => invalidateAfterMutation,
    useNoteColumn: () => ({ noteColumn }),
    useNumberFormat: () => ({ format: (value: number) => String(value) }),
    useTenant: () => ({
      getSetting: (key: string, defaultValue?: unknown) => {
        if (key === "onboarding_mode") return modalState.onboardingMode;
        if (key === "value_one_coop_share") return 100;
        if (key === "min_number_coop_shares") return modalState.minShares;
        if (key === "max_number_coop_shares") return modalState.maxShares;
        return defaultValue;
      },
    }),
  };
});

import CoopSharesModal from "../CoopSharesModal";

type ColumnConfig = {
  key: string;
  disabled?: unknown;
  render?: (value: unknown, record: Record<string, unknown>) => React.ReactNode;
};
type CustomEdit = (record: Record<string, unknown>) => Record<string, unknown>;
type CustomSave = (
  transformedData: Record<string, unknown>,
  currentRecord: Record<string, unknown>,
) => Record<string, unknown>;

function renderModal({
  memberCancelledEffectiveAt = null,
}: { memberCancelledEffectiveAt?: string | null } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CoopSharesModal
        isOpen
        onClose={vi.fn()}
        memberId="member-1"
        memberName="Ada Lovelace"
        adminConfirmed
        memberCancelledEffectiveAt={memberCancelledEffectiveAt}
      />
    </QueryClientProvider>,
  );
}

function column(key: string): ColumnConfig {
  const columns = (modalState.tableProps?.columns ?? []) as ColumnConfig[];
  const found = columns.find((col) => col.key === key);
  if (!found) throw new Error(`${key} column not found`);
  return found;
}

function paidAtColumn(): ColumnConfig {
  return column("paid_at");
}

beforeEach(() => {
  modalState.onboardingMode = false;
  modalState.tableProps = null;
  modalState.rows = [];
  modalState.minShares = undefined;
  modalState.maxShares = undefined;
});

describe("CoopSharesModal paid_at", () => {
  it("is disabled while onboarding mode is off", () => {
    renderModal();

    expect(screen.getByTestId("editable-table")).toBeInTheDocument();
    expect(paidAtColumn().disabled).toBe(true);
  });

  it("is editable while onboarding mode is on", () => {
    modalState.onboardingMode = true;
    renderModal();

    expect(paidAtColumn().disabled).toBe(false);
  });

  it("starts editing from the display-format day of the stored datetime", () => {
    modalState.onboardingMode = true;
    renderModal();

    const customEdit = modalState.tableProps?.customEdit as CustomEdit;
    expect(
      customEdit({ key: "share-1", paid_at: "2026-07-13T10:00:00+00:00" }),
    ).toEqual({ key: "share-1", paid_at: "13.07.2026" });
  });

  it("leaves an unpaid share unchanged when editing starts", () => {
    renderModal();

    const customEdit = modalState.tableProps?.customEdit as CustomEdit;
    const record = { key: "share-1", paid_at: null };
    expect(customEdit(record)).toBe(record);
  });
});

describe("CoopSharesModal share value", () => {
  it("sends the tenant's current value with a new row", () => {
    renderModal();

    const customSave = modalState.tableProps?.customSave as CustomSave;
    expect(
      customSave({ amount_of_coop_shares: 2 }, { key: -1 }),
    ).toEqual({
      amount_of_coop_shares: 2,
      member: "member-1",
      value_one_coop_share: 100,
    });
  });

  it("sends no value when a saved row is edited", () => {
    renderModal();

    const customSave = modalState.tableProps?.customSave as CustomSave;
    const payload = customSave(
      { amount_of_coop_shares: 2, note: "paid in cash" },
      { key: "share-1", id: "share-1", value_one_coop_share: 80 },
    );
    expect(payload).not.toHaveProperty("value_one_coop_share");
    expect(payload).toMatchObject({ member: "member-1", note: "paid in cash" });
  });

  it("values a saved row at its own share value, a new row at the tenant's", () => {
    renderModal();

    const render = column("value").render!;
    const { rerender } = renderStandalone(
      render(undefined, {
        key: "share-1",
        amount_of_coop_shares: "2.00",
        value_one_coop_share: 80,
      }),
    );
    expect(screen.getByTestId("value-cell")).toHaveTextContent("160 €");

    rerender(
      <div data-testid="value-cell">
        {render(undefined, { key: -1, amount_of_coop_shares: 2 })}
      </div>,
    );
    expect(screen.getByTestId("value-cell")).toHaveTextContent("200 €");
  });
});

function renderStandalone(node: React.ReactNode) {
  return render(<div data-testid="value-cell">{node}</div>);
}

describe("CoopSharesModal coop-share bounds", () => {
  const cancelledShare = {
    key: "share-9",
    id: "share-9",
    amount_of_coop_shares: 2,
    cancelled_at: "2025-12-31T10:00:00Z",
  };

  it("refuses a total below the minimum for a current member", () => {
    modalState.minShares = 3;
    renderModal();

    const customSave = modalState.tableProps?.customSave as CustomSave;
    expect(() => customSave({ amount_of_coop_shares: 1 }, { key: -1 })).toThrow(
      "members.below_min_shares",
    );
  });

  it("lets the office record the payback on a departed member's share", () => {
    // Every share of a departed member is cancelled, so their total is 0.
    modalState.minShares = 3;
    modalState.rows = [cancelledShare];
    renderModal({ memberCancelledEffectiveAt: "2025-12-31" });

    const customSave = modalState.tableProps?.customSave as CustomSave;
    expect(
      customSave(
        { amount_of_coop_shares: 2, paid_back_date: "2026-07-15" },
        cancelledShare,
      ),
    ).toMatchObject({ paid_back_date: "2026-07-15" });
  });

  it("counts an edited cancelled share as 0, like the server", () => {
    modalState.maxShares = 3;
    modalState.rows = [
      { key: "share-1", id: "share-1", amount_of_coop_shares: 3 },
      cancelledShare,
    ];
    renderModal();

    const customSave = modalState.tableProps?.customSave as CustomSave;
    expect(
      customSave({ amount_of_coop_shares: 2, note: "Paid back." }, cancelledShare),
    ).toMatchObject({ note: "Paid back." });
  });
});

