// OnboardingNoEmailHint shows its note only while onboarding mode is on.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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

import OnboardingNoEmailHint from "../OnboardingNoEmailHint";

beforeEach(() => {
  hookState.onboardingMode = false;
});

describe("OnboardingNoEmailHint", () => {
  it("renders nothing while onboarding mode is off", () => {
    const { container } = render(<OnboardingNoEmailHint />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says that no email is sent while onboarding mode is on", () => {
    hookState.onboardingMode = true;
    render(<OnboardingNoEmailHint />);
    expect(
      screen.getByText("onboarding.mode.no_email_hint"),
    ).toBeInTheDocument();
  });
});
