// EmailStatusTag shows a short status label; a suppressed email also explains,
// on hover and as the tag's accessible description, that onboarding mode kept
// it from being sent.

import React from "react";
import { describe, expect, it, vi } from "vitest";
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

import EmailStatusTag from "../EmailStatusTag";

describe("EmailStatusTag", () => {
  it("shows a sent email's label without a hint", async () => {
    render(<EmailStatusTag status="sent" />);

    const tag = screen.getByText("email_matrix.status.sent");
    expect(tag).toHaveClass("email-status-tag");
    expect(tag).not.toHaveAttribute("aria-describedby");

    await userEvent.hover(tag);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("explains a suppressed email on hover and to assistive technology", async () => {
    render(<EmailStatusTag status="suppressed" />);

    const tag = screen.getByText("email_matrix.status.suppressed");
    expect(tag).toHaveClass("email-status-tag");
    expect(tag).toHaveAccessibleDescription(
      "email_matrix.status_hint.suppressed",
    );

    await userEvent.hover(tag);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("email_matrix.status_hint.suppressed");
    expect(tooltip.closest(".custom-tooltip")).not.toBeNull();
  });
});
