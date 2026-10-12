import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import NotAuthorizedResult from "../NotAuthorizedResult";

const renderAt = (message?: string) =>
  render(
    <MemoryRouter initialEntries={["/start", "/locked"]}>
      <Routes>
        <Route path="/" element={<p>home</p>} />
        <Route path="/start" element={<p>start</p>} />
        <Route path="/locked" element={<NotAuthorizedResult message={message} />} />
      </Routes>
    </MemoryRouter>,
  );

describe("NotAuthorizedResult", () => {
  it("shows the default reason", () => {
    renderAt();

    expect(screen.getByText("auth.not_authorized.title")).toBeInTheDocument();
    expect(screen.getByText("auth.not_authorized.message")).toBeInTheDocument();
  });

  it("shows a given reason instead of the default one", () => {
    renderAt("The feature is turned off.");

    expect(screen.getByText("The feature is turned off.")).toBeInTheDocument();
    expect(screen.queryByText("auth.not_authorized.message")).not.toBeInTheDocument();
  });

  it("leads home", async () => {
    renderAt();

    await userEvent.click(
      screen.getByRole("button", { name: "auth.not_authorized.back_home" }),
    );

    expect(screen.getByText("home")).toBeInTheDocument();
  });

  it("leads back to the previous page", async () => {
    renderAt();

    await userEvent.click(screen.getByRole("button", { name: "common.back" }));

    expect(screen.getByText("start")).toBeInTheDocument();
  });
});
