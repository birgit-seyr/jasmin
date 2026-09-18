// The language picker may only offer languages the backend will provision:
// the create-tenant serializer constrains tenant_language to the platform's
// LanguageChoices (en/de), so any other option would be a guaranteed 400.

import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@shared/services/api", () => ({
  default: { post: vi.fn() },
}));

import CreateTenantModal from "../CreateTenantModal";

function languageSelect(): HTMLSelectElement {
  // The only <select> in the form; its label has no htmlFor, so the
  // accessible-name lookup would not find it.
  return screen.getByRole("combobox") as HTMLSelectElement;
}

describe("CreateTenantModal language picker", () => {
  it("offers exactly the languages the platform supports", () => {
    render(<CreateTenantModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    const options = within(languageSelect()).getAllByRole("option");

    expect(options.map((option) => option.getAttribute("value"))).toEqual([
      "de",
      "en",
    ]);
  });

  it("does not offer a language the backend rejects", () => {
    render(<CreateTenantModal onClose={vi.fn()} onSuccess={vi.fn()} />);

    const options = within(languageSelect()).queryAllByRole("option");
    const values = options.map((option) => option.getAttribute("value"));

    expect(values).not.toContain("fr");
    expect(
      within(languageSelect()).queryByText("Français"),
    ).not.toBeInTheDocument();
  });
});
