/**
 * ``CoopSharesModal`` grid wiring for the tenant's onboarding mode: ``paid_at``
 * is editable only while the mode is on, and its edit cell starts from the
 * calendar day in the display format although the API sends a datetime.
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
  useCommissioningCoopSharesList: () => ({ data: [], isFetching: false }),
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
    useCurrency: () => ({ currencySymbol: "€" }),
    useDateFormat: () => ({ formatDate, formatDateWithColor: formatDate }),
    useInvalidateAfterTableMutation: () => invalidateAfterMutation,
    useNoteColumn: () => ({ noteColumn }),
    useNumberFormat: () => ({ format: (value: number) => String(value) }),
    useTenant: () => ({
      getSetting: (key: string, defaultValue?: unknown) => {
        if (key === "onboarding_mode") return modalState.onboardingMode;
        if (key === "value_one_coop_share") return 100;
        return defaultValue;
      },
    }),
  };
});

import CoopSharesModal from "../CoopSharesModal";

type ColumnConfig = { key: string; disabled?: unknown };
type CustomEdit = (record: Record<string, unknown>) => Record<string, unknown>;

function renderModal() {
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
      />
    </QueryClientProvider>,
  );
}

function paidAtColumn(): ColumnConfig {
  const columns = (modalState.tableProps?.columns ?? []) as ColumnConfig[];
  const column = columns.find((col) => col.key === "paid_at");
  if (!column) throw new Error("paid_at column not found");
  return column;
}

beforeEach(() => {
  modalState.onboardingMode = false;
  modalState.tableProps = null;
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
