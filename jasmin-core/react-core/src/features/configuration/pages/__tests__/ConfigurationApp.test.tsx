// Configuration > App: a tenant that uploads its weekly share amounts runs no
// subscriptions and keeps no member records, so that switch leads the page and
// the MEMBERS / ABOS module toggles are locked with the reason beside them.
// Every other module toggle, and the whole page for a tenant without the flag,
// stays exactly as it was.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

const stable = vi.hoisted(() => ({
  // Mutated per test. ``undefined`` models the key being ABSENT from the
  // tenant's settings, which is what every tenant in production looks like
  // today — the mocked getSetting below then falls through to the caller's
  // default instead of answering with a hardcoded boolean.
  weeklyUpload: undefined as boolean | undefined,
  // Stable references: the page re-seeds its form state from a useEffect keyed
  // on the tenant object, so a fresh literal per render would spin.
  translation: {
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  },
  autoSave: { hasChanges: false, saving: false, markChanged: () => {} },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => stable.translation,
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("../../../../test/tenantMock");
  // Built once, outside the useTenant arrow, so the identity is reference-stable.
  const tenant = makeUseTenantMock({
    tenant: { id: "tenant-1" },
    // Mirrors the real getSetting (TenantContext): a tenant with no settings
    // object, or a missing path segment, yields the CALLER-SUPPLIED default.
    // Flipping the page's ``false`` default to ``true`` therefore changes what
    // these tests see, which is the point.
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "uploads_weekly_share_amount" && stable.weeklyUpload !== undefined
        ? stable.weeklyUpload
        : defaultValue,
  });
  return {
    useTenant: () => tenant,
    useAutoSave: () => stable.autoSave,
  };
});

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsTenantsPartialUpdate: vi.fn(),
  tenantsSettingsUpdateCurrentSettingsUpdate: vi.fn(),
}));

vi.mock("@shared/ui", () => ({
  AutoSaveIndicator: () => null,
}));

vi.mock("@shared/utils", () => ({
  notify: { success: vi.fn(), error: vi.fn() },
  // SettingsRenderer imports this for its date inputs; the App page has none.
  toApiDate: () => null,
}));

import ConfigurationApp from "../ConfigurationApp";

const WEEKLY_UPLOAD = "settings.commissioning.uploads_weekly_amount";
const MEMBERS = "settings.navigation.show_members";
const ABOS = "settings.navigation.show_abos";
const COMMISSIONING = "settings.navigation.show_commissioning";
const STAFF = "settings.navigation.show_staff";
const LOCK_REASON = "settings.navigation.locked_by_weekly_upload";

/** AntD wraps the input in its <label>, so the label text is the a11y name. */
function moduleToggle(label: string): HTMLElement {
  return screen.getByRole("checkbox", { name: label });
}

/** Card titles in DOM order — the order the office reads down the page. */
function cardTitles(): string[] {
  return Array.from(document.querySelectorAll(".ant-card-head-title")).map(
    (title) => title.textContent ?? "",
  );
}

/** ToolTipIcon names itself with its title, so the reason is reachable
 *  without hovering. */
function lockIcons(): HTMLElement[] {
  return screen.queryAllByLabelText(LOCK_REASON);
}

describe("ConfigurationApp weekly-upload tenants", () => {
  beforeEach(() => {
    stable.weeklyUpload = undefined;
  });

  it("leads the page with the weekly-upload switch", () => {
    render(<ConfigurationApp />);

    expect(cardTitles()[0]).toBe("settings.operating_mode.title");

    const firstCard = document.querySelector(".ant-card") as HTMLElement;
    expect(
      within(firstCard).getByRole("checkbox", { name: WEEKLY_UPLOAD }),
    ).toBeInTheDocument();
  });

  it("leaves the module toggles usable when the flag is off", () => {
    stable.weeklyUpload = false;
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeEnabled();
    expect(moduleToggle(ABOS)).toBeEnabled();
    expect(lockIcons()).toHaveLength(0);
  });

  it("leaves the module toggles usable when the flag is absent", () => {
    // ``weeklyUpload`` stays undefined: getSetting answers with the default the
    // page passes, which is how every tenant in production reads today.
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeEnabled();
    expect(moduleToggle(ABOS)).toBeEnabled();
    expect(lockIcons()).toHaveLength(0);
  });

  it("locks the members and abos toggles when the flag is on", () => {
    stable.weeklyUpload = true;
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeDisabled();
    expect(moduleToggle(ABOS)).toBeDisabled();
    expect(lockIcons()).toHaveLength(2);
  });

  it("locks only those two — the other modules stay switchable", () => {
    stable.weeklyUpload = true;
    render(<ConfigurationApp />);

    expect(moduleToggle(COMMISSIONING)).toBeEnabled();
    expect(moduleToggle(STAFF)).toBeEnabled();
  });
});
