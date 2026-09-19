// Configuration > App: a tenant that uploads its weekly share amounts runs no
// subscriptions and keeps no member records, so that switch leads the page and
// the MEMBERS / ABOS module toggles are locked with the reason beside them, and
// shown OFF because the modules are hidden. The lock is cosmetic: the stored
// preference stays in form state and in the save payload, so it comes back the
// moment the flag is cleared. Every other module toggle, and the whole page for
// a tenant without the flag, stays exactly as it was.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";

const stable = vi.hoisted(() => ({
  // Mutated per test. ``undefined`` models the key being ABSENT from the
  // tenant's settings, which is what every tenant in production looks like
  // today — the mocked getSetting below then falls through to the caller's
  // default instead of answering with a hardcoded boolean.
  weeklyUpload: undefined as boolean | undefined,
  // The page's autosave callback, captured at render so a test can fire the
  // save the office's next edit would fire and inspect what goes on the wire.
  save: null as null | (() => Promise<void>),
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
    // ``navigation`` carries the tenant's STORED module preference — both
    // modules on. The weekly-upload lock must never overwrite it.
    tenant: { id: "tenant-1", navigation: { show_members: true, show_abos: true } },
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
    useAutoSave: (options: { save: () => Promise<void> }) => {
      stable.save = options.save;
      return stable.autoSave;
    },
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

import { tenantsTenantsPartialUpdate } from "@shared/api/generated/tenants/tenants";
import { SettingsRenderer } from "../../components/SettingsRenderer";
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

/** The ``navigation`` blob of the Tenant PATCH the page just sent. The backend
 *  replaces the whole JSON field, so whatever is missing here is lost. */
function savedNavigation(): Record<string, unknown> {
  const calls = vi.mocked(tenantsTenantsPartialUpdate).mock.calls;
  expect(calls).toHaveLength(1);
  const body = calls[0][1] as { navigation?: Record<string, unknown> };
  return body.navigation ?? {};
}

describe("ConfigurationApp weekly-upload tenants", () => {
  beforeEach(() => {
    stable.weeklyUpload = undefined;
    stable.save = null;
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("leads the page with the weekly-upload switch", () => {
    render(<ConfigurationApp />);

    expect(cardTitles()[0]).toBe("settings.operating_mode.title");

    const firstCard = document.querySelector(".ant-card") as HTMLElement;
    expect(
      within(firstCard).getByRole("checkbox", { name: WEEKLY_UPLOAD }),
    ).toBeInTheDocument();
  });

  it("leaves the module toggles usable and on when the flag is off", () => {
    stable.weeklyUpload = false;
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeEnabled();
    expect(moduleToggle(ABOS)).toBeEnabled();
    expect(moduleToggle(MEMBERS)).toBeChecked();
    expect(moduleToggle(ABOS)).toBeChecked();
    expect(lockIcons()).toHaveLength(0);
  });

  it("reads identically when the flag is absent entirely", () => {
    // ``weeklyUpload`` stays undefined: getSetting answers with the default the
    // page passes, which is how every tenant in production reads today.
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeEnabled();
    expect(moduleToggle(ABOS)).toBeEnabled();
    expect(moduleToggle(MEMBERS)).toBeChecked();
    expect(moduleToggle(ABOS)).toBeChecked();
    expect(lockIcons()).toHaveLength(0);
  });

  it("shows the members and abos toggles off and locked when the flag is on", () => {
    stable.weeklyUpload = true;
    render(<ConfigurationApp />);

    expect(moduleToggle(MEMBERS)).toBeDisabled();
    expect(moduleToggle(ABOS)).toBeDisabled();
    expect(moduleToggle(MEMBERS)).not.toBeChecked();
    expect(moduleToggle(ABOS)).not.toBeChecked();
    expect(lockIcons()).toHaveLength(2);
  });

  it("locks only those two — the other modules stay switchable", () => {
    stable.weeklyUpload = true;
    render(<ConfigurationApp />);

    expect(moduleToggle(COMMISSIONING)).toBeEnabled();
    expect(moduleToggle(STAFF)).toBeEnabled();
    expect(moduleToggle(COMMISSIONING)).toBeChecked();
    expect(moduleToggle(STAFF)).toBeChecked();
  });

  it("keeps the stored preference in the saved payload while locked", async () => {
    stable.weeklyUpload = true;
    render(<ConfigurationApp />);

    // The unchecked boxes above must be cosmetic: saving from this page — which
    // is what any unrelated edit does, since the PATCH carries the whole form
    // state — has to send the tenant's stored ``true``. A ``false`` here would
    // be permanent: the backend replaces the navigation blob wholesale, so the
    // modules would stay hidden even after the flag is cleared.
    await act(async () => {
      await stable.save?.();
    });

    expect(savedNavigation()).toMatchObject({
      show_members: true,
      show_abos: true,
    });
  });
});

describe("SettingsRenderer disabled settings", () => {
  it("keeps showing the real value when a setting is locked for another reason", () => {
    // Server-locked / admin-only settings (SettingsPage's locked_settings) set
    // ``disabled`` without ``disabledDisplayValue``: the office still sees what
    // the value actually is, it just can't change it.
    render(
      <>
        {SettingsRenderer.renderInput(
          {
            key: "navigation.show_staff",
            label: STAFF,
            type: "checkbox",
            disabled: true,
            disabledTooltip: "tooltip.locked_setting_tooltip",
          },
          true,
          () => {},
        )}
      </>,
    );

    expect(moduleToggle(STAFF)).toBeDisabled();
    expect(moduleToggle(STAFF)).toBeChecked();
  });
});
