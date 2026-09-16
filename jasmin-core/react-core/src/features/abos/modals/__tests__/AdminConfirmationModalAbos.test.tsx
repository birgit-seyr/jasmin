/**
 * The onboarding hint in ``AdminConfirmationModalAbos``: while the tenant's
 * onboarding mode is on, a pending subscription's confirm modal says that the
 * subscription confirm admits a not-yet-confirmed member with today's date.
 *
 * Boundary mocked: react-i18next, the date / time / currency / tenant hooks,
 * the paper-received toggle and the generated billing profile API. The real
 * AntD Modal and the shared confirmation toolkit render.
 */
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
  useVariationLabel: () => (label: unknown) => String(label ?? ""),
  // The rejected-status banner reads the time format from the barrel.
  useTimeFormat: () => ({
    formatDateTime: (value: unknown) => String(value ?? ""),
  }),
}));
vi.mock("@hooks/configuration/useDateFormat", () => ({
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: unknown) => (value ? String(value) : null),
    formatDateWithFallback: (value: unknown, fallback = "-") =>
      value ? String(value) : fallback,
  }),
}));
vi.mock("@hooks/configuration/useTimeFormat", () => ({
  useTimeFormat: () => ({
    formatDateTime: (value: unknown) => String(value ?? ""),
  }),
}));
vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({ formatCurrency: (value: unknown) => String(value) }),
}));
vi.mock("@hooks/usePaperReceivedToggle", () => ({
  usePaperReceivedToggle: () => ({
    paperReceived: false,
    handlePaperToggle: () => {},
  }),
}));
vi.mock(
  "@shared/api/generated/payments-—-billing-profiles/payments-—-billing-profiles",
  () => ({
    getPaymentsBillingProfilesListQueryKey: () => ["billing_profiles"],
    usePaymentsBillingProfilesList: () => ({ data: [] }),
    usePaymentsBillingProfilesPartialUpdate: () => ({
      mutateAsync: () => Promise.resolve(),
      isPending: false,
    }),
  }),
);

import { AdminConfirmationModalAbos } from "../AdminConfirmationModalAbos";
import type { AboRecord } from "@features/abos/pages/types";

const HINT = "onboarding.mode.subscription_confirm_hint";

function pendingAbo(overrides: Partial<AboRecord> = {}): AboRecord {
  return {
    key: "abo-1",
    id: "abo-1",
    member: "member-1",
    member_first_name: "Ada",
    member_last_name: "Lovelace",
    admin_confirmed: false,
    admin_rejected_at: null,
    is_trial: false,
    valid_from: "2026-06-01",
    valid_until: "2027-05-30",
    price_per_delivery: "10.00",
    ...overrides,
  } as AboRecord;
}

function renderModal(abo: AboRecord) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AdminConfirmationModalAbos
        isOpen
        onClose={vi.fn()}
        abo={abo}
        onConfirm={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  tenantState.onboardingMode = false;
});

describe("AdminConfirmationModalAbos onboarding hint", () => {
  it("is not shown while onboarding mode is off", () => {
    renderModal(pendingAbo());

    expect(screen.getByText("members.confirm_abo")).toBeInTheDocument();
    expect(screen.queryByText(HINT)).not.toBeInTheDocument();
  });

  it("is shown for a pending subscription while onboarding mode is on", () => {
    tenantState.onboardingMode = true;
    renderModal(pendingAbo());

    expect(screen.getByText(HINT)).toBeInTheDocument();
  });

  it("is not shown for a confirmed subscription", () => {
    tenantState.onboardingMode = true;
    renderModal(pendingAbo({ admin_confirmed: true }));

    expect(screen.queryByText(HINT)).not.toBeInTheDocument();
  });

  it("is not shown for a rejected subscription", () => {
    tenantState.onboardingMode = true;
    renderModal(pendingAbo({ admin_rejected_at: "2026-07-01T09:00:00Z" }));

    expect(screen.queryByText(HINT)).not.toBeInTheDocument();
  });
});
