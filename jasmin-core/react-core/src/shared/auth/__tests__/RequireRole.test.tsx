import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const viewer = vi.hoisted(() => ({ isOffice: false }));

vi.mock("../useRoles", () => ({
  useRoles: () => ({ isOffice: viewer.isOffice }),
}));

import { RequireRole } from "../RequireRole";

const renderGuarded = (fallback?: React.ReactNode) =>
  render(
    <MemoryRouter>
      <RequireRole flag="isOffice" fallback={fallback}>
        <p>office page</p>
      </RequireRole>
    </MemoryRouter>,
  );

beforeEach(() => {
  viewer.isOffice = false;
});

describe("RequireRole", () => {
  it("renders the page for a viewer with the flag", () => {
    viewer.isOffice = true;
    renderGuarded();

    expect(screen.getByText("office page")).toBeInTheDocument();
    expect(screen.queryByText("auth.not_authorized.title")).not.toBeInTheDocument();
  });

  it("shows the translated no-access view to a viewer without the flag", () => {
    renderGuarded();

    expect(screen.queryByText("office page")).not.toBeInTheDocument();
    expect(screen.getByText("auth.not_authorized.title")).toBeInTheDocument();
    expect(screen.getByText("auth.not_authorized.message")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "auth.not_authorized.back_home" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "common.back" })).toBeInTheDocument();
  });

  it("shows a given fallback instead of the no-access view", () => {
    renderGuarded(<p>custom fallback</p>);

    expect(screen.getByText("custom fallback")).toBeInTheDocument();
    expect(screen.queryByText("auth.not_authorized.title")).not.toBeInTheDocument();
  });
});
