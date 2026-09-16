// OfferSpotModal sends the offer with the reviewed price, and can't send while
// onboarding mode is on (it may be switched on while the modal is open).

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const hookState = vi.hoisted(() => ({ onboardingMode: false }));

vi.mock("@hooks/index", () => ({
  useCurrency: () => ({ currencySymbol: "€" }),
  useDateFormat: () => ({ formatDate: (value: unknown) => String(value ?? "") }),
  useVariationLabel: () => (value: unknown) => String(value ?? ""),
  useOnboardingMode: () => hookState.onboardingMode,
}));

import { OfferSpotModal } from "../OfferSpotModal";
import type { AboRecord } from "@features/abos/pages/types";

const RECORD = {
  key: "abo-1",
  id: "abo-1",
  member_string: "Ada Lovelace",
  share_type_variation_string: "Vegetables large",
  default_delivery_station_day_string: "Market hall (Tuesday)",
  valid_from: "2026-10-05",
  quantity: 1,
  price_per_delivery: "11.00",
} as AboRecord;

function renderModal(onConfirm = vi.fn()) {
  render(
    <OfferSpotModal
      open
      record={RECORD}
      suggestedPrice={12.5}
      loading={false}
      onCancel={vi.fn()}
      onConfirm={onConfirm}
    />,
  );
  return onConfirm;
}

beforeEach(() => {
  hookState.onboardingMode = false;
});

describe("OfferSpotModal", () => {
  it("sends the offer with the suggested price while onboarding mode is off", async () => {
    const onConfirm = renderModal();

    const send = screen.getByRole("button", { name: "abos.notify_member" });
    expect(send).toBeEnabled();
    expect(
      screen.queryByText("onboarding.mode.offer_spot_disabled"),
    ).not.toBeInTheDocument();
    await userEvent.click(send);
    expect(onConfirm).toHaveBeenCalledWith(12.5);
  });

  it("can't send while onboarding mode is on and says why", async () => {
    hookState.onboardingMode = true;
    const onConfirm = renderModal();

    const send = screen.getByRole("button", { name: "abos.notify_member" });
    expect(send).toBeDisabled();
    expect(send).toHaveAccessibleDescription(
      "onboarding.mode.offer_spot_disabled",
    );
    await userEvent.click(send);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
