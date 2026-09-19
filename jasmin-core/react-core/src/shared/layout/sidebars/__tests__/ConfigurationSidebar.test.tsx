/**
 * ConfigurationSidebar — the members group is gated on the tenant setting
 * ``uploads_weekly_share_amount``.
 *
 * A tenant that uploads aggregate weekly share amounts keeps no member records,
 * so the whole members group (data protection and consents included) is
 * dropped. Two distinct tenant states resolve to flag-off and both are
 * regression guards: the setting explicitly ``false``, and a tenant carrying no
 * such key at all — ``getSetting`` returns the caller's default for a missing
 * key just as it does for a tenant payload with no settings, so the default
 * passed at the call site is what those tenants get.
 *
 * ``t`` is stubbed to return the key, so the assertions read as i18n keys. Only
 * keys unique to one group are asserted by text — the general and reseller
 * groups render ``configuration.email_templates`` too, which is why that one is
 * counted rather than matched. The member routes are asserted on BOTH sides of
 * the flag: "no link with this href" only proves something once the same href
 * is proven to exist while the flag is off.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ROLES } from "@shared/auth/roles";
import type { RoleFlags } from "@shared/auth/useRoles";
import { NavigationProvider } from "@shared/contexts/NavigationContext";

import ConfigurationSidebar from "../ConfigurationSidebar";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The flag is read lazily inside ``getSetting``, so one reference-stable tenant
// object still answers differently per test. ``undefined`` stands for a tenant
// whose settings hold no such key: the mock then falls through to the caller's
// default, which is what the real ``getSetting`` does for a missing key.
const settings = vi.hoisted(() => ({
  weeklyUpload: false as boolean | undefined,
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "uploads_weekly_share_amount" &&
      settings.weeklyUpload !== undefined
        ? settings.weeklyUpload
        : defaultValue,
  });
  return { useTenant: () => tenant };
});

// Every entry in this sidebar is ``requireRole: "isAdmin"``; the real
// ``filterByRole`` runs so the test exercises the production drop path.
const adminFlags: RoleFlags = {
  gardener: false,
  office: false,
  staff: false,
  management: false,
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

vi.mock("@shared/auth", async () => {
  const { filterByRole } = await import("@shared/auth/filterByRole");
  return { filterByRole, useRoles: () => adminFlags };
});

/** The members group heading plus every child unique to it. */
const membersGroupEntries = [
  "configuration.group.members",
  "configuration.members",
  "configuration.subscriptions",
  "configuration.payments",
  "configuration.data_protection",
  "consent.admin.title",
];

/** Every route the members group links to, the e-mail templates included. */
const memberRoutes = [
  "/configuration/members",
  "/configuration/subscriptions",
  "/configuration/payments",
  "/configuration/gdpr",
  "/configuration/consents",
  "/configuration/email-templates/members",
];

/** Headings and children of the two groups the flag must never touch. */
const untouchedGroupEntries = [
  "configuration.group.general",
  "configuration.app",
  "configuration.general",
  "configuration.email",
  "users.title",
  "configuration.group.commissioning",
  "configuration.commissioning",
  "configuration.share_type_variations",
  "configuration.delivery_days",
  "commissioning.delivery_exceptions",
  "configuration.reseller_documents",
];

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/configuration/app"]}>
      <NavigationProvider>
        <ConfigurationSidebar />
      </NavigationProvider>
    </MemoryRouter>,
  );
}

/** The full flag-off expectation: all three groups, every member entry, every
 *  member route, one e-mail-template link per group. */
function expectEveryGroupRendered() {
  for (const entry of [...untouchedGroupEntries, ...membersGroupEntries]) {
    expect(screen.getByText(entry)).toBeInTheDocument();
  }
  for (const route of memberRoutes) {
    expect(
      document.querySelector(`a[href="${route}"]`),
      `${route} must be linked`,
    ).not.toBeNull();
  }
  expect(screen.getAllByText("configuration.email_templates")).toHaveLength(3);
}

describe("ConfigurationSidebar", () => {
  beforeEach(() => {
    settings.weeklyUpload = false;
  });

  it("renders all three groups when uploads_weekly_share_amount is off", () => {
    renderSidebar();

    expectEveryGroupRendered();
  });

  it("renders all three groups when the tenant has no such setting", () => {
    // No key in the tenant payload — the call site's default decides.
    settings.weeklyUpload = undefined;
    renderSidebar();

    expectEveryGroupRendered();
  });

  it("drops the members group and each of its children when the flag is on", () => {
    settings.weeklyUpload = true;
    renderSidebar();

    for (const entry of membersGroupEntries) {
      expect(screen.queryByText(entry)).not.toBeInTheDocument();
    }
    // The heading alone going missing would not be enough: assert the links are
    // gone by route too.
    for (const route of memberRoutes) {
      expect(
        document.querySelector(`a[href="${route}"]`),
        `${route} must not be linked`,
      ).toBeNull();
    }
    expect(screen.getAllByText("configuration.email_templates")).toHaveLength(
      2,
    );
  });

  it("leaves the general and commissioning groups alone when the flag is on", () => {
    settings.weeklyUpload = true;
    renderSidebar();

    for (const entry of untouchedGroupEntries) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
  });
});
