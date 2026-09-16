/**
 * The confirmation date in ``AdminConfirmationModalMembers``.
 *
 * Boundary mocked: react-i18next, the tenant / date / time hooks from
 * ``@hooks/index``, the paper-received toggle and the generated member PATCH
 * hook. The real AntD DatePicker, ``useOnboardingConfirmationDate`` and the
 * shared confirmation footer run. The clock is pinned (Date only) so "today"
 * and the disabled future days are stable.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const tenantState = vi.hoisted(() => ({ onboardingMode: false }));

vi.mock("@hooks/index", () => ({
  useTenant: () => ({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "onboarding_mode" ? tenantState.onboardingMode : defaultValue,
  }),
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: unknown) =>
      value ? dayjs(value as string).format("DD.MM.YYYY") : null,
    formatDateWithFallback: (value: unknown, fallback = "-") =>
      value ? dayjs(value as string).format("DD.MM.YYYY") : fallback,
    formatDateForAPI: (value: unknown) =>
      value ? dayjs(value as string).format("YYYY-MM-DD") : null,
  }),
  useTimeFormat: () => ({
    formatDateTime: (value: unknown) => String(value ?? ""),
  }),
}));

vi.mock("@hooks/usePaperReceivedToggle", () => ({
  usePaperReceivedToggle: () => ({
    paperReceived: false,
    handlePaperToggle: () => {},
  }),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  getCommissioningMembersListQueryKey: () => ["members"],
  useCommissioningMembersPartialUpdate: () => ({
    mutateAsync: () => Promise.resolve(),
    isPending: false,
  }),
}));

import { AdminConfirmationModalMembers } from "../AdminConfirmationModalMembers";
import type { MemberRecord } from "@features/members/pages/types";

const DATE_LABEL = "onboarding.confirmation_date.label";
const DISABLED_CELL = "ant-picker-cell-disabled";

function pendingMember(overrides: Partial<MemberRecord> = {}): MemberRecord {
  return {
    key: "member-1",
    id: "member-1",
    first_name: "Ada",
    last_name: "Lovelace",
    admin_confirmed: false,
    admin_rejected_at: null,
    cancelled_at: null,
    cancelled_effective_at: null,
    entry_date: null,
    is_trial: false,
    ...overrides,
  };
}

function renderModal(member: MemberRecord) {
  const onConfirm = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AdminConfirmationModalMembers
        isOpen
        onClose={vi.fn()}
        member={member}
        onConfirm={onConfirm}
      />
    </QueryClientProvider>,
  );
  return onConfirm;
}

const confirmButton = () =>
  screen.getByRole("button", { name: /members\.confirm_member/ });

function dayCell(isoDate: string): HTMLElement {
  const cell = document.querySelector<HTMLElement>(`td[title="${isoDate}"]`);
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  return cell;
}

beforeEach(() => {
  tenantState.onboardingMode = false;
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 6, 15, 10, 0));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AdminConfirmationModalMembers confirmation date", () => {
  it("shows no date picker and sends an empty body while onboarding mode is off", async () => {
    const onConfirm = renderModal(pendingMember({ entry_date: "2019-04-01" }));

    expect(screen.queryByLabelText(DATE_LABEL)).not.toBeInTheDocument();
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({});
  });

  it("defaults to the member's entry date and sends it as confirmed_at while on", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingMember({ entry_date: "2019-04-01" }));

    const input = screen.getByLabelText(DATE_LABEL);
    expect(input).toHaveValue("01.04.2019");
    expect(input).toHaveAccessibleDescription(
      "onboarding.confirmation_date.hint",
    );
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2019-04-01" });
  });

  it("defaults to today when the member has no entry date", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingMember());

    expect(screen.getByLabelText(DATE_LABEL)).toHaveValue("15.07.2026");
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2026-07-15" });
  });

  it("defaults to today when the member's entry date lies in the future", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingMember({ entry_date: "2026-08-17" }));

    expect(screen.getByLabelText(DATE_LABEL)).toHaveValue("15.07.2026");
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2026-07-15" });
  });

  it("disables future days and sends a picked past day", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingMember());

    await userEvent.click(screen.getByLabelText(DATE_LABEL));
    expect(dayCell("2026-07-16")).toHaveClass(DISABLED_CELL);
    expect(dayCell("2026-07-14")).not.toHaveClass(DISABLED_CELL);
    await userEvent.click(dayCell("2026-07-14"));
    expect(screen.getByLabelText(DATE_LABEL)).toHaveValue("14.07.2026");
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2026-07-14" });
  });

  it("caps the default at a departed member's exit date and disables later days", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(
      pendingMember({
        cancelled_at: "2024-11-30T09:00:00Z",
        cancelled_effective_at: "2024-12-31",
      }),
    );

    const input = screen.getByLabelText(DATE_LABEL);
    expect(input).toHaveValue("31.12.2024");
    expect(input).toHaveAccessibleDescription(
      "onboarding.confirmation_date.hint_departed",
    );
    await userEvent.click(input);
    expect(dayCell("2025-01-01")).toHaveClass(DISABLED_CELL);
    expect(dayCell("2024-12-30")).not.toHaveClass(DISABLED_CELL);
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2024-12-31" });
  });

  it("shows no date picker for an already confirmed member", () => {
    tenantState.onboardingMode = true;
    renderModal(pendingMember({ admin_confirmed: true }));

    expect(screen.queryByLabelText(DATE_LABEL)).not.toBeInTheDocument();
  });
});
