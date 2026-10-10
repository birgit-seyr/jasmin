/**
 * MobileSidebar — the phone drawer's curated list of field jobs.
 *
 * Every link has to land on a route the router serves: the drawer is
 * hand-maintained, so a renamed route leaves a dead link behind without this
 * check. The drawer lists commissioning only, so it renders one group header
 * and no empty ones, and its trigger and title are translated.
 *
 * The packing lists follow the tenant's ``packing_mode`` as in the desktop
 * sidebar: box packing (``BOXES`` / ``MIXED``) links them, bulk packing hides
 * them.
 *
 * ``t`` is stubbed to return the key, so the assertions read as i18n keys.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, matchPath } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routeGroups } from "@app/routing/routeConfig";

import { makeUseTenantMock } from "../../../../test/tenantMock";
import MobileSidebar from "../MobileSidebar";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

let packingMode: string | undefined;

vi.mock("@hooks/index", () => ({
  useTenant: () =>
    makeUseTenantMock({
      getSetting: (key: string, defaultValue?: unknown) =>
        key === "packing_mode" && packingMode !== undefined
          ? packingMode
          : defaultValue,
    }),
}));

afterEach(() => {
  packingMode = undefined;
});

const routePaths = routeGroups.flatMap((group) =>
  group.routes.map((route) => route.path),
);

async function openDrawer() {
  render(
    <MemoryRouter>
      <MobileSidebar />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "nav.open_menu" }));
  return screen.findByRole("dialog");
}

describe("MobileSidebar", () => {
  it("links only to routes the router serves", async () => {
    const drawer = await openDrawer();
    const hrefs = within(drawer)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href") ?? "");

    expect(hrefs.length).toBeGreaterThan(0);
    const deadLinks = hrefs.filter(
      (href) => !routePaths.some((path) => matchPath(path, href)),
    );
    expect(deadLinks).toEqual([]);
  });

  it("links both commissioning lists", async () => {
    const drawer = await openDrawer();
    expect(
      within(drawer).getByRole("link", {
        name: "commissioning.commissioning_list_packing",
      }),
    ).toHaveAttribute("href", "/commissioning/commissioning-list-packing");
    expect(
      within(drawer).getByRole("link", {
        name: "commissioning.commissioning_list_resellers_short",
      }),
    ).toHaveAttribute("href", "/commissioning/commissioning-list-resellers");
  });

  it.each(["BOXES", "MIXED"])(
    "links the packing lists when packing mode is %s",
    async (mode) => {
      packingMode = mode;
      const drawer = await openDrawer();
      expect(
        within(drawer).getByRole("link", { name: "commissioning.packing_lists" }),
      ).toHaveAttribute("href", "/commissioning/packing-list-boxes");
      expect(
        within(drawer).getByRole("link", {
          name: "commissioning.commissioning_list_packing",
        }),
      ).toBeInTheDocument();
    },
  );

  it("hides the packing lists when the farm packs in bulk", async () => {
    packingMode = "BULK";
    const drawer = await openDrawer();
    expect(
      within(drawer).queryByRole("link", { name: "commissioning.packing_lists" }),
    ).toBeNull();
    expect(
      within(drawer).queryByRole("link", {
        name: "commissioning.commissioning_list_packing",
      }),
    ).toBeNull();
    expect(
      within(drawer).getByRole("link", {
        name: "commissioning.commissioning_list_resellers_short",
      }),
    ).toBeInTheDocument();
  });

  it("translates its title and renders no empty group header", async () => {
    const drawer = await openDrawer();
    expect(within(drawer).getByText("nav.navigation")).toBeInTheDocument();
    expect(within(drawer).getByText("nav.commissioning")).toBeInTheDocument();
    expect(within(drawer).queryByText("nav.cultivation")).toBeNull();
    expect(screen.queryByText("Navigation")).toBeNull();
  });
});
