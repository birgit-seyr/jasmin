/**
 * ConfigurationSidebar — the members group and the delivery exceptions entry
 * are gated on the tenant setting ``uploads_weekly_share_amount``, the
 * reseller documents on ``sells_to_resellers``.
 *
 * A tenant that uploads aggregate weekly share amounts keeps no member records
 * and runs no subscriptions, so the whole members group (data protection and
 * consents included) is dropped, and so is the delivery exceptions page, which
 * pauses subscriptions' deliveries. Two distinct tenant states resolve to flag-off and both are
 * regression guards: the setting explicitly ``false``, and a tenant carrying no
 * such key at all — ``getSetting`` returns the caller's default for a missing
 * key just as it does for a tenant payload with no settings, so the default
 * passed at the call site is what those tenants get.
 *
 * ``t`` is stubbed to return the key, so the assertions read as i18n keys. Only
 * keys unique to one group are asserted by text — the general and reseller
 * groups render ``configuration.email_templates`` too, which is why that one is
 * counted rather than matched. The member routes and the delivery exceptions
 * route are asserted on BOTH sides of the flag: "no link with this href" only
 * proves something once the same href is proven to exist while the flag is off.
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
  sellsToResellers: undefined as boolean | undefined,
}));

// What the deployment offers; a name left out is offered, as with a payload
// that carries no capabilities.
const capabilities = vi.hoisted(() => ({}) as Record<string, boolean>);

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) => {
      const value = {
        uploads_weekly_share_amount: settings.weeklyUpload,
        sells_to_resellers: settings.sellsToResellers,
      }[key];
      return value !== undefined ? value : defaultValue;
    },
  });
  return {
    useTenant: () => tenant,
    useCapability: (name: string) => capabilities[name] ?? true,
  };
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

/** Headings and children of the two groups the flag leaves standing. */
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
  "configuration.reseller_documents",
];

/** The one commissioning entry the flag drops. */
const deliveryExceptionsEntry = "commissioning.delivery_exceptions";
const deliveryExceptionsRoute = "/configuration/delivery-exceptions";

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
  for (const entry of [
    ...untouchedGroupEntries,
    ...membersGroupEntries,
    deliveryExceptionsEntry,
  ]) {
    expect(screen.getByText(entry)).toBeInTheDocument();
  }
  for (const route of [...memberRoutes, deliveryExceptionsRoute]) {
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
    settings.sellsToResellers = undefined;
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

  it("drops the delivery exceptions entry when the flag is on", () => {
    settings.weeklyUpload = true;
    renderSidebar();

    expect(screen.queryByText(deliveryExceptionsEntry)).not.toBeInTheDocument();
    expect(
      document.querySelector(`a[href="${deliveryExceptionsRoute}"]`),
    ).toBeNull();
  });

  it("leaves the rest of the general and commissioning groups alone when the flag is on", () => {
    settings.weeklyUpload = true;
    renderSidebar();

    for (const entry of untouchedGroupEntries) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
  });
});

describe("ConfigurationSidebar reseller documents", () => {
  beforeEach(() => {
    settings.weeklyUpload = false;
    settings.sellsToResellers = undefined;
  });

  it("links the documents and their email templates where the farm sells to resellers", () => {
    settings.sellsToResellers = true;
    renderSidebar();

    expect(
      document.querySelector('a[href="/configuration/reseller-documents"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('a[href="/configuration/email-templates/resellers"]'),
    ).not.toBeNull();
  });

  it("drops both where the farm sells to no reseller", () => {
    settings.sellsToResellers = false;
    renderSidebar();

    expect(
      screen.queryByText("configuration.reseller_documents"),
    ).not.toBeInTheDocument();
    expect(
      document.querySelector('a[href="/configuration/reseller-documents"]'),
    ).toBeNull();
    expect(
      document.querySelector('a[href="/configuration/email-templates/resellers"]'),
    ).toBeNull();
    expect(screen.getAllByText("configuration.email_templates")).toHaveLength(2);
    expect(screen.getByText("configuration.delivery_days")).toBeInTheDocument();
  });
});

describe("ConfigurationSidebar email server", () => {
  const emailLink = () => document.querySelector('a[href="/configuration/email"]');

  beforeEach(() => {
    settings.weeklyUpload = true;
    settings.sellsToResellers = false;
    delete capabilities.user_accounts;
  });

  it("is dropped where the shares are imported, the host keeps the logins and no reseller buys", () => {
    capabilities.user_accounts = false;
    renderSidebar();

    expect(emailLink()).toBeNull();
    expect(screen.getByText("configuration.general")).toBeInTheDocument();
  });

  it("stays while the farm sells to resellers", () => {
    capabilities.user_accounts = false;
    settings.sellsToResellers = true;
    renderSidebar();

    expect(emailLink()).not.toBeNull();
  });

  it("stays where the farm invites its own logins", () => {
    renderSidebar();

    expect(emailLink()).not.toBeNull();
  });

  it("stays where the farm keeps its members' shares itself", () => {
    capabilities.user_accounts = false;
    settings.weeklyUpload = false;
    renderSidebar();

    expect(emailLink()).not.toBeNull();
  });
});

describe("ConfigurationSidebar crates, storages and plots", () => {
  beforeEach(() => {
    settings.weeklyUpload = false;
    settings.sellsToResellers = undefined;
    delete capabilities.configuration_section;
  });

  it.each([
    ["where the configuration is a section", true],
    ["where it isn't one", false],
  ])("leaves them to commissioning's data lists %s", (_, isSection) => {
    capabilities.configuration_section = isSection;
    renderSidebar();

    for (const label of [
      "commissioning.list_crates",
      "commissioning.list_storages",
      "commissioning.list_plots",
    ]) {
      expect(screen.queryByText(label), label).not.toBeInTheDocument();
    }
    expect(screen.getByText("configuration.delivery_days")).toBeInTheDocument();
  });
});

describe("ConfigurationSidebar users page", () => {
  beforeEach(() => {
    settings.weeklyUpload = false;
    settings.sellsToResellers = undefined;
    delete capabilities.user_accounts;
  });

  it("links the users page where the deployment has its own logins", () => {
    renderSidebar();

    expect(screen.getByText("users.title")).toBeInTheDocument();
    expect(
      document.querySelector('a[href="/configuration/users"]'),
    ).not.toBeNull();
  });

  it("drops the users page where the host application owns the logins", () => {
    capabilities.user_accounts = false;
    renderSidebar();

    expect(screen.queryByText("users.title")).not.toBeInTheDocument();
    expect(document.querySelector('a[href="/configuration/users"]')).toBeNull();
    expect(screen.getByText("configuration.general")).toBeInTheDocument();
  });

  it("drops the logins' email templates there too, and keeps the others", () => {
    capabilities.user_accounts = false;
    renderSidebar();

    expect(
      document.querySelector('a[href="/configuration/email-templates/general"]'),
    ).toBeNull();
    expect(
      document.querySelector('a[href="/configuration/email-templates/members"]'),
    ).not.toBeNull();
    expect(
      document.querySelector('a[href="/configuration/email-templates/resellers"]'),
    ).not.toBeNull();
  });
});
