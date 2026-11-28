/**
 * TopNavigation — the members and abos sections are gated on the tenant
 * setting ``uploads_weekly_share_amount``.
 *
 * A tenant that uploads aggregate weekly share amounts holds no member or
 * subscription records, so both sections drop out of the section bar whatever
 * their ``navigation.show_*`` settings say. Two distinct tenant states resolve
 * to flag-off and both are regression guards: the setting explicitly ``false``,
 * and a tenant carrying no such key at all — ``getSetting`` hands back the
 * caller's default for a missing key exactly as it does for a tenant payload
 * with no settings, so the default passed at the call site is what those
 * tenants get. The mock below therefore falls through to that default instead
 * of answering a hardcoded boolean.
 *
 * ``t`` is stubbed to return the key, so the assertions read as i18n keys, and
 * every section is asserted by its route as well: a label going missing only
 * proves something once the same href is proven to exist on the other side of
 * the flag.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROLES } from "@shared/auth/roles";
import type { RoleFlags } from "@shared/auth/useRoles";
import {
  NavigationProvider,
  useNavigation,
} from "@shared/contexts/NavigationContext";

import DoubleTopNavigation from "../TopNavigation";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The settings are read lazily inside ``getSetting``, so one reference-stable
// tenant object still answers differently per test. ``undefined`` stands for a
// tenant whose settings hold no such key: the mock then falls through to the
// caller's default, which is what the real ``getSetting`` does both for a
// missing key and for a tenant with no settings object at all.
const settings = vi.hoisted(() => ({
  weeklyUpload: undefined as boolean | undefined,
  showMembers: undefined as boolean | undefined,
  showAbos: undefined as boolean | undefined,
  showConfiguration: undefined as boolean | undefined,
}));

// What the deployment offers; a name left out is offered, as with a payload
// that carries no capabilities.
const capabilities = vi.hoisted(() => ({}) as Record<string, boolean>);

beforeEach(() => {
  for (const name of Object.keys(capabilities)) delete capabilities[name];
  window.history.replaceState(null, "", "/");
});

// The navigation context reads the capabilities through this module directly.
vi.mock("@shared/hooks/configuration/useCapability", () => ({
  useCapability: (name: string) => capabilities[name] ?? true,
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) => {
      if (key === "uploads_weekly_share_amount")
        return settings.weeklyUpload ?? defaultValue;
      if (key === "navigation.show_members")
        return settings.showMembers ?? defaultValue;
      if (key === "navigation.show_abos")
        return settings.showAbos ?? defaultValue;
      if (key === "navigation.show_configuration")
        return settings.showConfiguration ?? defaultValue;
      return defaultValue;
    },
  });
  return {
    useTenant: () => tenant,
    useIsMobile: () => false,
    useCapability: (name: string) => capabilities[name] ?? true,
  };
});

// The section bar is hidden on mobile, so every role gate has to pass for the
// desktop bar under test to render all nine entries.
const allRoleFlags: RoleFlags = {
  gardener: true,
  office: true,
  staff: true,
  management: true,
  admin: true,
  hasMemberRole: false,
  hasCustomerRole: false,
  canEdit: true,
  isOffice: true,
  canEditCultivation: true,
  isManagement: true,
  isAdmin: true,
  isStaff: true,
  isMemberOnly: false,
  roles: [ROLES.ADMIN],
};

// Per-test role overrides, mirroring ``settings`` above: the mock reads this
// lazily, so one reference-stable holder answers differently per test. Without
// it every test sees all-flags-true and no section's gate VALUE is observable —
// a section gated on the wrong flag would render identically.
const roleOverrides = vi.hoisted(() => ({
  value: {} as Partial<Record<string, unknown>>,
}));

vi.mock("@shared/auth", () => ({
  useRoles: () => ({ ...allRoleFlags, ...roleOverrides.value }),
}));

// The top bar's own controls pull in auth, modal and locale contexts plus the
// member API; they have nothing to do with the section gating.
vi.mock("../HelpButton", () => ({ default: () => <div data-testid="help" /> }));
vi.mock("../ModalToggle", () => ({
  default: () => <div data-testid="modal-toggle" />,
}));
vi.mock("../SidebarToggle", () => ({
  default: () => <div data-testid="sidebar-toggle" />,
}));
vi.mock("../UserMenu", () => ({
  default: () => <div data-testid="user-menu" />,
}));

const MEMBERS_ROUTE = "/members/dashboard";
const ABOS_ROUTE = "/abos/dashboard";

/** The seven sections the flag must never touch, label and route. */
const untouchedSections = [
  ["nav.commissioning", "/commissioning/dashboard"],
  ["nav.staff", "/staff/dashboard"],
  ["nav.warehouse", "/warehouse/dashboard"],
  ["nav.economics", "/economics/dashboard"],
  ["nav.cultivation", "/cultivation/dashboard"],
  ["nav.configuration", "/configuration/dashboard"],
];

function renderNavigation() {
  return render(
    <MemoryRouter initialEntries={["/commissioning/dashboard"]}>
      <NavigationProvider>
        <DoubleTopNavigation />
      </NavigationProvider>
    </MemoryRouter>,
  );
}

function linkTo(route: string) {
  return document.querySelector(`a[href="${route}"]`);
}

function expectMemberSectionsRendered() {
  expect(screen.getByText("nav.members")).toBeInTheDocument();
  expect(screen.getByText("nav.abos")).toBeInTheDocument();
  expect(linkTo(MEMBERS_ROUTE), "members must be linked").not.toBeNull();
  expect(linkTo(ABOS_ROUTE), "abos must be linked").not.toBeNull();
}

function expectMemberSectionsGone() {
  expect(screen.queryByText("nav.members")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.abos")).not.toBeInTheDocument();
  expect(linkTo(MEMBERS_ROUTE), "members must not be linked").toBeNull();
  expect(linkTo(ABOS_ROUTE), "abos must not be linked").toBeNull();
}

describe("TopNavigation section bar", () => {
  beforeEach(() => {
    settings.weeklyUpload = undefined;
    settings.showMembers = undefined;
    settings.showAbos = undefined;
    roleOverrides.value = {};
  });

  // The Staff section is gated on isStaff, matching the /staff/* routes and the
  // backend (every apps/staff viewset reads IsStaff). The crew tier could
  // already reach these pages by URL, so the menu entry stops hiding a live
  // surface. Both directions are asserted: the positive alone cannot tell
  // "gated on isStaff" apart from "not gated at all".
  it("offers the staff section to a crew-tier user", () => {
    roleOverrides.value = {
      office: false,
      admin: false,
      management: false,
      isOffice: false,
      isAdmin: false,
      isManagement: false,
    };
    renderNavigation();

    expect(screen.getByText("nav.staff")).toBeInTheDocument();
    expect(linkTo("/staff/dashboard"), "staff must be linked").not.toBeNull();
  });

  it("withholds the staff section from a member-only user", () => {
    roleOverrides.value = {
      gardener: false,
      office: false,
      staff: false,
      management: false,
      admin: false,
      hasMemberRole: true,
      isOffice: false,
      isAdmin: false,
      isManagement: false,
      isStaff: false,
      isMemberOnly: true,
    };
    renderNavigation();

    expect(screen.queryByText("nav.staff")).not.toBeInTheDocument();
    expect(linkTo("/staff/dashboard"), "staff must not be linked").toBeNull();
  });

  it("shows members and abos when uploads_weekly_share_amount is off", () => {
    settings.weeklyUpload = false;
    renderNavigation();

    expectMemberSectionsRendered();
  });

  it("shows members and abos when the tenant has no such setting", () => {
    // No key in the tenant payload — the call site's default decides.
    renderNavigation();

    expectMemberSectionsRendered();
  });

  it("hides members and abos when the flag is on", () => {
    settings.weeklyUpload = true;
    renderNavigation();

    expectMemberSectionsGone();
  });

  it("hides them even when navigation.show_members/_abos are explicitly on", () => {
    settings.weeklyUpload = true;
    settings.showMembers = true;
    settings.showAbos = true;
    renderNavigation();

    expectMemberSectionsGone();
  });

  it("keeps hiding a section its own navigation setting switched off", () => {
    // The override removes; it never adds a section back.
    settings.weeklyUpload = false;
    settings.showMembers = false;
    renderNavigation();

    expect(screen.queryByText("nav.members")).not.toBeInTheDocument();
    expect(linkTo(MEMBERS_ROUTE)).toBeNull();
    expect(screen.getByText("nav.abos")).toBeInTheDocument();
  });

  it("leaves every other section alone when the flag is on", () => {
    settings.weeklyUpload = true;
    renderNavigation();

    for (const [label, route] of untouchedSections) {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(linkTo(route), `${route} must be linked`).not.toBeNull();
    }
  });

  it("renders the same other sections when the flag is off", () => {
    settings.weeklyUpload = false;
    renderNavigation();

    for (const [label, route] of untouchedSections) {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(linkTo(route), `${route} must be linked`).not.toBeNull();
    }
  });
});

const DATA_ROUTE = "/commissioning/list-harvest-share-articles";

/** Where the app is, which section is active, and a way to follow a link
 *  that isn't in the section bar. */
function Probe() {
  const navigate = useNavigate();
  return (
    <>
      <div data-testid="location">{useLocation().pathname}</div>
      <div data-testid="section">{useNavigation().activeSection}</div>
      <button type="button" onClick={() => navigate("/commissioning/forecast")}>
        go to the forecast
      </button>
      <button type="button" onClick={() => navigate("/configuration/app")}>
        go to the app settings
      </button>
      <button type="button" onClick={() => navigate("/commissioning/list-plots")}>
        go to the plots
      </button>
    </>
  );
}

/** The provider takes its first section from the browser's address, so the
 *  window goes to the same path as the router. */
function renderNavigationAt(path: string) {
  window.history.replaceState(null, "", path);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NavigationProvider>
        <DoubleTopNavigation />
        <Probe />
      </NavigationProvider>
    </MemoryRouter>,
  );
}

const sectionOf = (route: string) => linkTo(route)?.closest("li");
/** The gear among the top bar's icon buttons. */
const configurationIcon = () =>
  screen.queryByRole("button", { name: "nav.configuration" });

describe("TopNavigation configuration and data sections", () => {
  beforeEach(() => {
    settings.showConfiguration = undefined;
    roleOverrides.value = {};
  });

  it("keeps the configuration a section where the deployment has it", () => {
    renderNavigation();

    expect(screen.getByText("nav.configuration")).toBeInTheDocument();
    expect(configurationIcon()).toBeNull();
    expect(linkTo(DATA_ROUTE), "the data stay in commissioning").toBeNull();
  });

  it("keeps the data lists in commissioning where the deployment has the section", () => {
    renderNavigationAt("/commissioning/list-resellers");

    expect(screen.getByTestId("section")).toHaveTextContent(/^commissioning$/);
  });

  it("turns the configuration into an icon and the data into a section elsewhere", () => {
    capabilities.configuration_section = false;
    renderNavigation();

    expect(screen.queryByText("nav.configuration")).not.toBeInTheDocument();
    expect(configurationIcon()).toHaveClass("ant-btn", "configuration-button");
    expect(screen.getByText("commissioning.data")).toBeInTheDocument();
    expect(linkTo(DATA_ROUTE)).not.toBeNull();
  });

  it("opens the configuration with its sidebar from the icon", async () => {
    capabilities.configuration_section = false;
    renderNavigationAt("/commissioning/dashboard");

    await userEvent.click(configurationIcon() as HTMLElement);

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/configuration/dashboard",
    );
    expect(screen.getByTestId("section")).toHaveTextContent("configuration");
  });

  it("offers the icon to admins only, as the section was", () => {
    capabilities.configuration_section = false;
    roleOverrides.value = { admin: false, isAdmin: false };
    renderNavigation();

    expect(configurationIcon()).toBeNull();
  });

  it("leaves the icon out where the tenant's navigation hides the configuration", () => {
    capabilities.configuration_section = false;
    settings.showConfiguration = false;
    renderNavigation();

    expect(configurationIcon()).toBeNull();
  });

  it("selects the data section on a data list, though it lives under commissioning", () => {
    capabilities.configuration_section = false;
    renderNavigationAt("/commissioning/list-resellers");

    expect(screen.getByTestId("section")).toHaveTextContent("commissioning-data");
    expect(sectionOf(DATA_ROUTE)).toHaveClass("ant-menu-item-selected");
    expect(sectionOf("/commissioning/dashboard")).not.toHaveClass(
      "ant-menu-item-selected",
    );
  });

  it("goes back to commissioning when a link leaves the data lists", async () => {
    capabilities.configuration_section = false;
    renderNavigationAt("/commissioning/list-resellers");

    await userEvent.click(screen.getByRole("button", { name: "go to the forecast" }));

    expect(screen.getByTestId("section")).toHaveTextContent(/^commissioning$/);
    expect(sectionOf("/commissioning/dashboard")).toHaveClass(
      "ant-menu-item-selected",
    );
  });

  const cratesStoragesAndPlots = [
    "/commissioning/list-crates",
    "/commissioning/list-storages",
    "/commissioning/list-plots",
  ];

  it("keeps the crates, storages and plots in commissioning where the deployment has the configuration section", () => {
    for (const path of cratesStoragesAndPlots) {
      const { unmount } = renderNavigationAt(path);
      expect(screen.getByTestId("section"), path).toHaveTextContent(
        /^commissioning$/,
      );
      unmount();
    }
  });

  it("selects the data section on the crates, storages and plots elsewhere", () => {
    capabilities.configuration_section = false;

    for (const path of cratesStoragesAndPlots) {
      const { unmount } = renderNavigationAt(path);
      expect(screen.getByTestId("section"), path).toHaveTextContent(
        "commissioning-data",
      );
      expect(sectionOf(DATA_ROUTE), path).toHaveClass("ant-menu-item-selected");
      unmount();
    }
  });

  it.each([
    ["where the deployment has the configuration section", true, /^commissioning$/],
    ["in the data section elsewhere", false, /^commissioning-data$/],
  ])("lands an old configuration address of the plots %s", async (_, isSection, section) => {
    capabilities.configuration_section = isSection;
    renderNavigationAt("/configuration/plots");
    expect(screen.getByTestId("section")).toHaveTextContent(/^configuration$/);

    // The route forwards to the list's own address.
    await userEvent.click(screen.getByRole("button", { name: "go to the plots" }));

    expect(screen.getByTestId("section")).toHaveTextContent(section);
  });

  it("returns to commissioning when a link leaves the configuration for it, as the configuration has no tab", async () => {
    capabilities.configuration_section = false;
    renderNavigationAt("/configuration/app");
    expect(screen.getByTestId("section")).toHaveTextContent(/^configuration$/);

    await userEvent.click(screen.getByRole("button", { name: "go to the forecast" }));

    expect(screen.getByTestId("section")).toHaveTextContent(/^commissioning$/);
    expect(sectionOf("/commissioning/dashboard")).toHaveClass(
      "ant-menu-item-selected",
    );
  });

  it("returns to commissioning on such a link where the configuration is a section too", async () => {
    renderNavigationAt("/configuration/app");

    await userEvent.click(screen.getByRole("button", { name: "go to the forecast" }));

    expect(screen.getByTestId("section")).toHaveTextContent(/^commissioning$/);
  });

  it.each([
    ["where the configuration is a section", true],
    ["where it is the gear icon", false],
  ])("goes to the configuration when a link leaves commissioning for it, %s", async (_, isSection) => {
    capabilities.configuration_section = isSection;
    renderNavigationAt("/commissioning/dashboard");

    await userEvent.click(
      screen.getByRole("button", { name: "go to the app settings" }),
    );

    expect(screen.getByTestId("section")).toHaveTextContent(/^configuration$/);
  });

  it.each([
    "/configuration/members",
    "/configuration/email-templates/members",
  ])("opens %s in the configuration on a reload, though its address names the members", (path) => {
    renderNavigationAt(path);

    expect(screen.getByTestId("section")).toHaveTextContent(/^configuration$/);
  });

  it("goes back to the configuration when a link leaves the data lists for it", async () => {
    capabilities.configuration_section = false;
    renderNavigationAt("/commissioning/list-plots");

    await userEvent.click(
      screen.getByRole("button", { name: "go to the app settings" }),
    );

    expect(screen.getByTestId("section")).toHaveTextContent(/^configuration$/);
  });
});

describe("TopNavigation help button", () => {
  beforeEach(() => {
    delete capabilities.support_tickets;
  });

  it("offers the support tickets where the deployment has them", () => {
    renderNavigation();

    expect(screen.getByTestId("help")).toBeInTheDocument();
    expect(screen.getByTestId("user-menu")).toBeInTheDocument();
  });

  it("drops the help button where the deployment has no support tickets", () => {
    capabilities.support_tickets = false;
    renderNavigation();

    expect(screen.queryByTestId("help")).not.toBeInTheDocument();
    expect(screen.getByTestId("user-menu")).toBeInTheDocument();
  });
});
