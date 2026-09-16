// The onboarding-mode banner shows only while the tenant setting is on, and the
// switch reflects and persists the setting through useTenantSettingToggle.

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

const hookState = vi.hoisted(() => ({
  settingValue: false,
  saving: false,
  onChange: vi.fn(),
}));

vi.mock("@hooks/index", () => ({
  useTenant: () => ({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "onboarding_mode" ? hookState.settingValue : defaultValue,
  }),
  useTenantSettingToggle: (key: string) => ({
    value: key === "onboarding_mode" ? hookState.settingValue : false,
    onChange: hookState.onChange,
    saving: hookState.saving,
  }),
}));

import { OnboardingModeBanner, OnboardingModeSwitch } from "../OnboardingMode";

beforeEach(() => {
  hookState.settingValue = false;
  hookState.saving = false;
  hookState.onChange = vi.fn().mockResolvedValue(undefined);
});

describe("OnboardingModeBanner", () => {
  it("renders nothing while onboarding mode is off", () => {
    const { container } = render(<OnboardingModeBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a labelled warning with every effect while on", () => {
    hookState.settingValue = true;
    render(<OnboardingModeBanner />);

    const region = screen.getByRole("region", {
      name: "onboarding.mode.banner_title",
    });
    expect(region).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    const effects = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(effects).toEqual([
      "onboarding.mode.effects.no_emails",
      "onboarding.mode.effects.confirmation_dates",
      "onboarding.mode.effects.member_fields",
      "onboarding.mode.effects.past_start",
      "onboarding.mode.effects.backfill",
      "onboarding.mode.effects.departed_members",
      "onboarding.mode.effects.confirm_members_first",
    ]);
  });
});

describe("OnboardingModeSwitch", () => {
  it("is a labelled, described switch reflecting the setting", () => {
    hookState.settingValue = true;
    render(<OnboardingModeSwitch />);

    const toggle = screen.getByRole("switch", {
      name: "onboarding.mode.switch_label",
    });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveAccessibleDescription("onboarding.mode.switch_hint");
  });

  it("turns the setting on when clicked", async () => {
    render(<OnboardingModeSwitch />);

    const toggle = screen.getByRole("switch", {
      name: "onboarding.mode.switch_label",
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);

    expect(hookState.onChange).toHaveBeenCalledTimes(1);
    expect(hookState.onChange.mock.calls[0][0]).toBe(true);
  });
});
