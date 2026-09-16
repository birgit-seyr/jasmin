// CancelMembershipModal notes in the office mode that no email is sent while
// onboarding mode is on. Member self-service shows no such note.

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

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningMembersCancelCreate: vi.fn().mockResolvedValue({}),
  commissioningMyMembershipCancelCreate: vi.fn().mockResolvedValue({}),
}));

const hookState = vi.hoisted(() => ({ onboardingMode: false }));

vi.mock("@hooks/index", () => ({
  useDateFormat: () => ({ dateFormat: "DD.MM.YYYY" }),
  useOnboardingMode: () => hookState.onboardingMode,
}));

import { CancelMembershipModal } from "../CancelMembershipModal";

function renderModal(self = false) {
  render(
    <CancelMembershipModal
      isOpen
      onClose={vi.fn()}
      memberId={self ? null : "member-1"}
      memberName="Ada Lovelace"
      self={self}
      onCancelled={vi.fn()}
    />,
  );
}

beforeEach(() => {
  hookState.onboardingMode = false;
});

describe("CancelMembershipModal onboarding note", () => {
  it("shows no note while onboarding mode is off", () => {
    renderModal();
    expect(
      screen.queryByText("onboarding.mode.no_email_hint"),
    ).not.toBeInTheDocument();
  });

  it("notes that no email is sent while onboarding mode is on", () => {
    hookState.onboardingMode = true;
    renderModal();
    expect(
      screen.getByText("onboarding.mode.no_email_hint"),
    ).toBeInTheDocument();
  });

  it("shows no note to a member cancelling their own membership", () => {
    hookState.onboardingMode = true;
    renderModal(true);
    expect(
      screen.getByText("members.cancel_membership_restraint"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("onboarding.mode.no_email_hint"),
    ).not.toBeInTheDocument();
  });
});
