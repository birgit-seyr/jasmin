/**
 * The confirmation date in ``AdminConfirmationModalCoopShares``.
 *
 * Boundary mocked: react-i18next and the tenant / date / currency hooks from
 * ``@hooks/index``. The real AntD DatePicker, ``useOnboardingConfirmationDate``
 * and the shared confirmation footer run. The clock is pinned (Date only) so
 * "today" and the disabled future days are stable.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    formatDateForAPI: (value: unknown) =>
      value ? dayjs(value as string).format("YYYY-MM-DD") : null,
  }),
  useTimeFormat: () => ({
    formatDateTime: (value: unknown) => String(value ?? ""),
  }),
  useCurrency: () => ({ currencySymbol: "€" }),
}));

import {
  AdminConfirmationModalCoopShares,
  type CoopShareConfirmRecord,
} from "../AdminConfirmationModalCoopShares";

const DATE_LABEL = "onboarding.confirmation_date.label";

function pendingShare(
  overrides: Partial<CoopShareConfirmRecord> = {},
): CoopShareConfirmRecord {
  return {
    key: "share-1",
    id: "share-1",
    amount_of_coop_shares: "2",
    value_one_coop_share: 100,
    member_string: "Ada Lovelace",
    admin_confirmed: false,
    admin_rejected_at: null,
    cancelled_at: null,
    ...overrides,
  };
}

function renderModal(
  coopShare: CoopShareConfirmRecord,
  props: { memberEntryDate?: string | null; memberExitDate?: string | null } = {},
) {
  const onConfirm = vi.fn();
  render(
    <AdminConfirmationModalCoopShares
      isOpen
      onClose={vi.fn()}
      coopShare={coopShare}
      onConfirm={onConfirm}
      {...props}
    />,
  );
  return onConfirm;
}

const confirmButton = () =>
  screen.getByRole("button", { name: /members\.confirm_coop_share/ });

beforeEach(() => {
  tenantState.onboardingMode = false;
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 6, 15, 10, 0));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AdminConfirmationModalCoopShares confirmation date", () => {
  it("shows no date picker and sends an empty body while onboarding mode is off", async () => {
    const onConfirm = renderModal(pendingShare(), {
      memberEntryDate: "2019-04-01",
    });

    expect(screen.queryByLabelText(DATE_LABEL)).not.toBeInTheDocument();
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({});
  });

  it("defaults to the member's entry date and sends it while on", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingShare(), {
      memberEntryDate: "2019-04-01",
    });

    expect(screen.getByLabelText(DATE_LABEL)).toHaveValue("01.04.2019");
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2019-04-01" });
  });

  it("caps the default at a departed member's exit date", async () => {
    tenantState.onboardingMode = true;
    const onConfirm = renderModal(pendingShare(), {
      memberEntryDate: null,
      memberExitDate: "2024-12-31",
    });

    const input = screen.getByLabelText(DATE_LABEL);
    expect(input).toHaveValue("31.12.2024");
    expect(input).toHaveAccessibleDescription(
      "onboarding.confirmation_date.hint_departed",
    );
    await userEvent.click(confirmButton());

    expect(onConfirm).toHaveBeenCalledWith({ confirmed_at: "2024-12-31" });
  });

  it("shows no date picker for a confirmed share", () => {
    tenantState.onboardingMode = true;
    renderModal(pendingShare({ admin_confirmed: true }));

    expect(screen.queryByLabelText(DATE_LABEL)).not.toBeInTheDocument();
  });
});
