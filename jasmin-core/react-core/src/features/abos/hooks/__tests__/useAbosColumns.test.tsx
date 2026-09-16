/**
 * ``useAbosColumns`` passes the tenant's onboarding mode to
 * ``useSubscriptionTerm`` as ``allowPastStart``: the Abos grid is edited by the
 * office only, so while the mode is on any Monday may be the start date.
 *
 * Boundary mocked: react-i18next, every hook the column factory reads and the
 * shared column / UI modules. The term hook records the options it receives.
 */
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const hookState = vi.hoisted(() => ({
  onboardingMode: false,
  termOptions: undefined as { allowPastStart?: boolean } | undefined,
}));

vi.mock("@hooks/configuration/useTenant", () => ({
  useTenant: () => ({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "onboarding_mode" ? hookState.onboardingMode : defaultValue,
  }),
}));
vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({ currencySymbol: "€" }),
}));
vi.mock("@hooks/configuration/useDateFormat", () => ({
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (value: unknown) => (value ? String(value) : null),
  }),
}));
vi.mock("@hooks/useNumberFormat", () => ({
  useNumberFormat: () => ({ format: (value: number) => String(value) }),
}));
vi.mock("@hooks/useSubscriptionTerm", () => ({
  useSubscriptionTerm: (options?: { allowPastStart?: boolean }) => {
    hookState.termOptions = options;
    return {
      allowsTrial: false,
      computeValidUntil: () => null,
      disabledValidFromDate: () => false,
    };
  },
}));
vi.mock("@hooks/columns/useActiveStatusColumn", () => ({
  useActiveStatusColumn: () => ({ key: "active_status" }),
}));
vi.mock("@hooks/columns/useSepaMandateColumn", () => ({
  useSepaMandateColumn: () => ({ key: "sepa_mandate" }),
}));
vi.mock("@hooks/columns/useTimeBoundColumns", () => ({
  useTimeBoundColumns: () => ({
    validFromColumn: { key: "valid_from", dataIndex: "valid_from" },
    validUntilColumn: { key: "valid_until", dataIndex: "valid_until" },
  }),
}));
vi.mock("../columns/useSharedAboColumns", () => ({
  useSharedAboColumns: () => ({
    displayIdColumn: { key: "display_id" },
    memberColumn: { key: "member" },
    shareTypeVariationColumn: { key: "share_type_variation" },
    quantityColumn: { key: "quantity" },
    deliveryStationDayColumn: { key: "delivery_station_day" },
  }),
}));
vi.mock("@shared/tables", () => ({
  adminConfirmationColumn: () => ({ key: "admin_confirmed" }),
}));
vi.mock("@shared/ui", () => ({
  LinkButton: () => null,
  StatusButton: () => null,
  ToolTipIcon: () => null,
}));

import { useAbosColumns } from "../columns/useAbosColumns";

function renderColumns() {
  return renderHook(() =>
    useAbosColumns({
      members: [],
      paymentCycles: [],
      allShareTypeVariations: [],
      variationDeliveryCycleById: new Map(),
      getDeliveryStationDaysForRow: () => [],
      getShareTypeVariationsForRow: () => [],
      getAdminStatus: () => ({ variant: "adminPending", key: "admin_pending" }),
      onOpenAdminConfirmation: () => {},
      adminStatusSorter: () => 0,
      recentlyAddedIds: new Set<string>(),
      onCancel: () => {},
      onShowLog: () => {},
      getMandateForMember: () => undefined,
      onShowSepaDetails: () => {},
    } as unknown as Parameters<typeof useAbosColumns>[0]),
  );
}

beforeEach(() => {
  hookState.onboardingMode = false;
  hookState.termOptions = undefined;
});

describe("useAbosColumns start-date rule", () => {
  it("keeps the lead time while onboarding mode is off", () => {
    const { result } = renderColumns();

    expect(result.current.columns.length).toBeGreaterThan(0);
    expect(hookState.termOptions).toEqual({ allowPastStart: false });
  });

  it("allows any Monday as the start while onboarding mode is on", () => {
    hookState.onboardingMode = true;
    renderColumns();

    expect(hookState.termOptions).toEqual({ allowPastStart: true });
  });
});
