/**
 * The /configuration/crates, storages and plots addresses forward to
 * commissioning's data lists, so bookmarks of them keep working.
 */
import { render, screen } from "@testing-library/react";
import { isValidElement } from "react";
import {
  MemoryRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
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

import { commissioningRoutes } from "../routes/commissioning";
import { configurationRoutes } from "../routes/configuration";

function Location() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

describe("forwarded configuration addresses", () => {
  it.each([
    ["/configuration/crates", "/commissioning/list-crates"],
    ["/configuration/storages", "/commissioning/list-storages"],
    ["/configuration/plots", "/commissioning/list-plots"],
  ])("forwards %s to %s", (from, to) => {
    const route = configurationRoutes.find((entry) => entry.path === from);
    if (!route) throw new Error(`No route for ${from}`);
    render(
      <MemoryRouter initialEntries={[from]}>
        <Routes>
          <Route path={from} element={route.element} />
          <Route path={to} element={<Location />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("location")).toHaveTextContent(to);
    const target = commissioningRoutes.find((entry) => entry.path === to);
    expect(target, `${to} has a route`).toBeDefined();
    expect(
      isValidElement(target?.element) && target.element.type === Navigate,
      `${to} is a page of its own, not another forward`,
    ).toBe(false);
  });
});
