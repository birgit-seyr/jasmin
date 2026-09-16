// The waiting-list "Notify member" button is disabled while onboarding mode is
// on, with the reason in a hover tooltip and as its accessible description.

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
  useOnboardingMode: () => hookState.onboardingMode,
}));

import { WaitingListOfferButton } from "../WaitingListOfferButton";

beforeEach(() => {
  hookState.onboardingMode = false;
});

describe("WaitingListOfferButton", () => {
  it("opens the offer while onboarding mode is off", async () => {
    const onClick = vi.fn();
    render(<WaitingListOfferButton onClick={onClick} />);

    const button = screen.getByRole("button", { name: "abos.notify_member" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-describedby");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is disabled with the reason while onboarding mode is on", async () => {
    hookState.onboardingMode = true;
    const onClick = vi.fn();
    render(<WaitingListOfferButton onClick={onClick} />);

    const button = screen.getByRole("button", { name: "abos.notify_member" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(
      "onboarding.mode.offer_spot_disabled",
    );

    await userEvent.hover(button.parentElement!);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("onboarding.mode.offer_spot_disabled");
    expect(tooltip.closest(".custom-tooltip")).not.toBeNull();
    expect(onClick).not.toHaveBeenCalled();
  });
});
