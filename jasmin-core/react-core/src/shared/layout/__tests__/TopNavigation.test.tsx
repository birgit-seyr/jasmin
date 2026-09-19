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
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROLES } from "@shared/auth/roles";
import type { RoleFlags } from "@shared/auth/useRoles";
import { NavigationProvider } from "@shared/contexts/NavigationContext";

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
      return defaultValue;
    },
  });
  return { useTenant: () => tenant, useIsMobile: () => false };
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

vi.mock("@shared/auth", () => ({ useRoles: () => allRoleFlags }));

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
