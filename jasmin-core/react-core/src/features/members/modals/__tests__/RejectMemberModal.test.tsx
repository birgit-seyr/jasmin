// RejectMemberModal warns that the applicant gets a rejection email, except
// while onboarding mode is on, when no email is sent and the copy says so.

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

import { RejectMemberModal } from "../RejectMemberModal";
import type { MemberRecord } from "@features/members/pages/types";

const MEMBER = {
  key: "member-1",
  id: "member-1",
  first_name: "Ada",
  last_name: "Lovelace",
} as MemberRecord;

function renderModal() {
  render(
    <RejectMemberModal
      isOpen
      onClose={vi.fn()}
      member={MEMBER}
      reason=""
      onReasonChange={vi.fn()}
      onReject={vi.fn()}
    />,
  );
}

beforeEach(() => {
  hookState.onboardingMode = false;
});

describe("RejectMemberModal", () => {
  it("warns about the rejection email while onboarding mode is off", () => {
    renderModal();

    expect(screen.getByText("members.reject_warning_title")).toBeInTheDocument();
    expect(screen.getByText("members.reject_warning_body")).toBeInTheDocument();
    expect(screen.getByText("members.reject_reason_label")).toBeInTheDocument();
    expect(
      screen.queryByText("onboarding.mode.reject_warning_title"),
    ).not.toBeInTheDocument();
  });

  it("says no rejection email is sent while onboarding mode is on", () => {
    hookState.onboardingMode = true;
    renderModal();

    expect(
      screen.getByText("onboarding.mode.reject_warning_title"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("onboarding.mode.reject_warning_body"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("onboarding.mode.reject_reason_label"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("members.reject_warning_title"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("members.reject_reason_label"),
    ).not.toBeInTheDocument();
  });
});
