// Configuration > App: a tenant that uploads its weekly share amounts runs no
// subscriptions and keeps no member records, so that switch leads the page and
// the MEMBERS / ABOS module toggles are locked with the reason beside them, and
// shown OFF because the modules are hidden. The lock is cosmetic: the stored
// preference stays in form state and in the save payload, so it comes back the
// moment the flag is cleared. Every other module toggle, and the whole page for
// a tenant without the flag, stays exactly as it was. A host that fixes the
// modules leaves their card out and keeps the stored choice in the save.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const stable = vi.hoisted(() => ({
  // Mutated per test. ``undefined`` models the key being ABSENT from the
  // tenant's settings, which is what every tenant in production looks like
  // today — the mocked getSetting below then falls through to the caller's
  // default instead of answering with a hardcoded boolean.
  weeklyUpload: undefined as boolean | undefined,
  // What the deployment offers; a name left out is offered.
  capabilities: {} as Record<string, boolean>,
  // The modules in effect, as the merged settings report them; a module left
  // out falls through to the caller's default.
  modulesInEffect: {} as Record<string, boolean>,
  // The tenant row the page reads. ``navigation`` carries the tenant's STORED
  // module preference — both modules on. The weekly-upload lock must never
  // overwrite it.
  tenantRow: {
    id: "tenant-1",
    navigation: { show_members: true, show_abos: true },
  } as Record<string, unknown>,
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
    tenant: stable.tenantRow,
    // Mirrors the real getSetting (TenantContext): a tenant with no settings
    // object, or a missing path segment, yields the CALLER-SUPPLIED default.
    // Flipping the page's ``false`` default to ``true`` therefore changes what
    // these tests see, which is the point.
    getSetting: (key: string, defaultValue?: unknown) => {
      if (key === "uploads_weekly_share_amount" && stable.weeklyUpload !== undefined) {
        return stable.weeklyUpload;
      }
      const module = key.replace("navigation.", "");
      return key.startsWith("navigation.") && module in stable.modulesInEffect
        ? stable.modulesInEffect[module]
        : defaultValue;
    },
  });
  return {
    useTenant: () => tenant,
    useCapability: (name: string) => stable.capabilities[name] ?? true,
    useAutoSave: (options: { save: () => Promise<void> }) => {
      stable.save = options.save;
      return stable.autoSave;
    },
  };
});

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsTenantsPartialUpdate: vi.fn(),
  tenantsSettingsUpdateCurrentSettingsUpdate: vi.fn(),
  // The HR-system card's own save; its tests live with the card.
  useTenantsTenantsPartialUpdate: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@shared/ui", () => ({
  AutoSaveIndicator: () => null,
}));

vi.mock("@shared/utils", () => ({
  notify: { success: vi.fn(), error: vi.fn() },
  // SettingsRenderer imports this for its date inputs; the App page has none.
  toApiDate: () => null,
}));

import {
  tenantsSettingsUpdateCurrentSettingsUpdate,
  tenantsTenantsPartialUpdate,
} from "@shared/api/generated/tenants/tenants";
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
    stable.capabilities = {};
    stable.modulesInEffect = {};
    delete stable.tenantRow.settings;
    delete stable.tenantRow.current_settings;
    vi.mocked(tenantsSettingsUpdateCurrentSettingsUpdate).mockClear();
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("puts the weekly-upload switch in its own card after the modules and the sales channels", () => {
    render(<ConfigurationApp />);

    expect(cardTitles()[2]).toBe("settings.operating_mode.title");

    const card = document.querySelectorAll(".ant-card")[2] as HTMLElement;
    expect(
      within(card).getByRole("checkbox", { name: WEEKLY_UPLOAD }),
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

  it("leaves out the operating-mode switch where the host fixes the mode", () => {
    // Inside such a host the payload already reports the import mode.
    stable.weeklyUpload = true;
    stable.capabilities = { operating_mode_choice: false };
    render(<ConfigurationApp />);

    expect(cardTitles()).not.toContain("settings.operating_mode.title");
    expect(
      screen.queryByRole("checkbox", { name: WEEKLY_UPLOAD }),
    ).not.toBeInTheDocument();
    expect(moduleToggle(MEMBERS)).toBeDisabled();
    expect(moduleToggle(COMMISSIONING)).toBeEnabled();
  });

  it("saves the stored operating mode back, not the one the host fixes", async () => {
    // The merged settings report the mode in effect (on, fixed by the host);
    // the row underneath still stores off, and a save must leave it so.
    stable.weeklyUpload = true;
    stable.capabilities = { operating_mode_choice: false };
    stable.tenantRow.settings = { uploads_weekly_share_amount: true };
    stable.tenantRow.current_settings = { uploads_weekly_share_amount: false };
    render(<ConfigurationApp />);

    await act(async () => {
      await stable.save?.();
    });

    expect(tenantsSettingsUpdateCurrentSettingsUpdate).toHaveBeenCalledWith({
      settings: { uploads_weekly_share_amount: false },
    });
  });
});

describe("ConfigurationApp sales channels", () => {
  const SELLS_TO_RESELLERS = "settings.commissioning.sells_to_resellers";
  const MARKETS = "settings.commissioning.has_markets";

  beforeEach(() => {
    stable.weeklyUpload = undefined;
    stable.save = null;
    stable.capabilities = {};
    stable.modulesInEffect = {};
    delete stable.tenantRow.settings;
    stable.tenantRow.current_settings = {
      sells_to_resellers: true,
      has_markets: false,
    };
    vi.mocked(tenantsSettingsUpdateCurrentSettingsUpdate).mockClear();
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("follows the modules with the stored channels", () => {
    render(<ConfigurationApp />);

    expect(cardTitles().slice(0, 2)).toEqual([
      "settings.navigation.title",
      "settings.commissioning.sales.title",
    ]);
    expect(moduleToggle(SELLS_TO_RESELLERS)).toBeChecked();
    expect(moduleToggle(MARKETS)).not.toBeChecked();
  });

  it("saves a changed channel with the versioned settings, not on the tenant row", async () => {
    render(<ConfigurationApp />);

    fireEvent.click(moduleToggle(SELLS_TO_RESELLERS));
    await act(async () => {
      await stable.save?.();
    });

    expect(tenantsSettingsUpdateCurrentSettingsUpdate).toHaveBeenCalledWith({
      settings: expect.objectContaining({
        sells_to_resellers: false,
        has_markets: false,
      }),
    });
    const tenantBody = vi.mocked(tenantsTenantsPartialUpdate).mock.calls[0][1];
    expect(tenantBody).not.toHaveProperty("sells_to_resellers");
    expect(tenantBody).not.toHaveProperty("has_markets");
  });

  it("shows the model's defaults to a tenant without stored settings and saves only the channel changed", async () => {
    delete stable.tenantRow.current_settings;
    render(<ConfigurationApp />);

    expect(moduleToggle(SELLS_TO_RESELLERS)).toBeChecked();
    expect(moduleToggle(MARKETS)).not.toBeChecked();

    fireEvent.click(moduleToggle(MARKETS));
    await act(async () => {
      await stable.save?.();
    });

    expect(tenantsSettingsUpdateCurrentSettingsUpdate).toHaveBeenCalledWith({
      settings: { has_markets: true },
    });
  });

  it("buys in by default and saves the switched-off purchases with the versioned settings", async () => {
    const PURCHASES = "settings.commissioning.has_purchases";
    delete stable.tenantRow.current_settings;
    render(<ConfigurationApp />);

    expect(moduleToggle(PURCHASES)).toBeChecked();

    fireEvent.click(moduleToggle(PURCHASES));
    await act(async () => {
      await stable.save?.();
    });

    expect(tenantsSettingsUpdateCurrentSettingsUpdate).toHaveBeenCalledWith({
      settings: { has_purchases: false },
    });
    const tenantBody = vi.mocked(tenantsTenantsPartialUpdate).mock.calls[0][1];
    expect(tenantBody).not.toHaveProperty("has_purchases");
  });
});

describe("ConfigurationApp organic documentation", () => {
  const ORGANIC = "settings.commissioning.uses_organic_documentation";

  beforeEach(() => {
    stable.weeklyUpload = undefined;
    stable.save = null;
    stable.capabilities = {};
    stable.modulesInEffect = {};
    delete stable.tenantRow.settings;
    delete stable.tenantRow.current_settings;
    vi.mocked(tenantsSettingsUpdateCurrentSettingsUpdate).mockClear();
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("sits with the sales channels, on by default", () => {
    render(<ConfigurationApp />);

    const salesCard = screen
      .getByText("settings.commissioning.sales.title")
      .closest(".ant-card") as HTMLElement;
    expect(
      within(salesCard).getByRole("checkbox", { name: ORGANIC }),
    ).toBeChecked();
  });

  it("shows a stored off as off", () => {
    stable.tenantRow.current_settings = { uses_organic_documentation: false };
    render(<ConfigurationApp />);

    expect(moduleToggle(ORGANIC)).not.toBeChecked();
  });

  it("explains each sales switch in a line below it", () => {
    render(<ConfigurationApp />);

    for (const description of [
      "settings.commissioning.sells_to_resellers_desc",
      "settings.commissioning.has_markets_desc",
      "settings.commissioning.has_purchases_desc",
      "settings.commissioning.uses_organic_documentation_desc",
    ]) {
      expect(screen.getByText(description)).toBeInTheDocument();
    }
  });

  it("shows the stored choice and saves a switched-off one with the versioned settings", async () => {
    stable.tenantRow.current_settings = { uses_organic_documentation: true };
    render(<ConfigurationApp />);

    fireEvent.click(moduleToggle(ORGANIC));
    await act(async () => {
      await stable.save?.();
    });

    expect(tenantsSettingsUpdateCurrentSettingsUpdate).toHaveBeenCalledWith({
      settings: { uses_organic_documentation: false },
    });
    const tenantBody = vi.mocked(tenantsTenantsPartialUpdate).mock.calls[0][1];
    expect(tenantBody).not.toHaveProperty("uses_organic_documentation");
  });
});

describe("ConfigurationApp modules fixed by the host", () => {
  beforeEach(() => {
    stable.weeklyUpload = true;
    stable.save = null;
    stable.capabilities = { operating_mode_choice: false, module_choice: false };
    stable.modulesInEffect = {};
    delete stable.tenantRow.current_settings;
    stable.tenantRow.navigation = { show_staff: true, show_economics: true };
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("leaves out the modules card, so the page opens with the sales channels", () => {
    render(<ConfigurationApp />);

    expect(cardTitles()[0]).toBe("settings.commissioning.sales.title");
    expect(cardTitles()).not.toContain("settings.navigation.title");
    expect(screen.queryByRole("checkbox", { name: COMMISSIONING })).not.toBeInTheDocument();
  });

  it("saves the stored module choice back untouched", async () => {
    render(<ConfigurationApp />);

    await act(async () => {
      await stable.save?.();
    });

    expect(savedNavigation()).toEqual({ show_staff: true, show_economics: true });
  });
});

describe("ConfigurationApp HR-system card", () => {
  beforeEach(() => {
    stable.weeklyUpload = undefined;
    stable.save = null;
    stable.capabilities = {};
    stable.modulesInEffect = {};
    delete stable.tenantRow.current_settings;
    stable.tenantRow.navigation = { show_members: true, show_abos: true };
    delete stable.tenantRow.uses_hr_system;
    delete stable.tenantRow.hr_system_employees_url;
    delete stable.tenantRow.has_hr_system_api_token;
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("comes last, after the interfaces, with the modules on top of the page", () => {
    render(<ConfigurationApp />);

    expect(cardTitles()).toEqual([
      "settings.navigation.title",
      "settings.commissioning.sales.title",
      "settings.operating_mode.title",
      "settings.general.title",
      "settings.commissioning.planning.title",
      "settings.hr_system.title",
    ]);
  });

  it("is left out while the staff module is off", () => {
    stable.tenantRow.navigation = {
      show_members: true,
      show_abos: true,
      show_staff: false,
    };
    render(<ConfigurationApp />);

    expect(cardTitles()).not.toContain("settings.hr_system.title");
  });

  it("comes and goes with the staff module's toggle", () => {
    render(<ConfigurationApp />);

    fireEvent.click(moduleToggle(STAFF));
    expect(cardTitles()).not.toContain("settings.hr_system.title");

    fireEvent.click(moduleToggle(STAFF));
    expect(cardTitles()).toContain("settings.hr_system.title");
  });

  it("follows the staff module in effect where the host fixes the modules", () => {
    // The row still stores the staff module on; the host has it off.
    stable.capabilities = { module_choice: false };
    stable.tenantRow.navigation = { show_staff: true };
    stable.modulesInEffect = { show_staff: false };
    render(<ConfigurationApp />);

    expect(cardTitles()).not.toContain("settings.hr_system.title");
  });

  it("leaves the card's fields out of the page's own save", async () => {
    stable.tenantRow.uses_hr_system = true;
    stable.tenantRow.hr_system_employees_url = "https://hr.example.com/staff";
    stable.tenantRow.has_hr_system_api_token = true;
    render(<ConfigurationApp />);

    await act(async () => {
      await stable.save?.();
    });

    const body = vi.mocked(tenantsTenantsPartialUpdate).mock.calls[0][1];
    for (const field of [
      "uses_hr_system",
      "hr_system_employees_url",
      "hr_system_absences_url",
      "has_hr_system_api_token",
      "hr_system_api_token",
    ]) {
      expect(body).not.toHaveProperty(field);
    }
  });
});

// The serializer constrains the column to ``LanguageChoices`` (en/de), so an
// option beyond those is one the office can pick and the save then rejects.
describe("ConfigurationApp tenant language", () => {
  const LANGUAGE = "tenant.organization.tenant_language";

  /** The renderer puts the label and the Select in one wrapper div. The label
   *  text sits in a <strong> inside AntD's <Text> span, so reach the wrapper by
   *  the nearest enclosing div rather than a single parentElement hop. */
  function languageSelect(): HTMLElement {
    const label = screen.getByText(LANGUAGE);
    return within(label.closest("div") as HTMLElement).getByRole("combobox");
  }

  /** The labels of the open dropdown's options, as the office reads them. */
  async function openOptions(): Promise<HTMLElement[]> {
    const dropdown = await screen.findByRole("listbox");
    return Array.from(
      (dropdown.closest(".ant-select-dropdown") ?? dropdown).querySelectorAll(
        ".ant-select-item-option-content",
      ),
    );
  }

  beforeEach(() => {
    stable.weeklyUpload = undefined;
    stable.save = null;
    stable.capabilities = {};
    stable.modulesInEffect = {};
    delete stable.tenantRow.current_settings;
    stable.tenantRow.tenant_language = "en";
    vi.mocked(tenantsTenantsPartialUpdate).mockClear();
  });

  it("sits with the date format in the general settings, showing the stored language", () => {
    render(<ConfigurationApp />);

    const generalCard = screen
      .getByText("settings.general.title")
      .closest(".ant-card") as HTMLElement;
    expect(within(generalCard).getByText(LANGUAGE)).toBeInTheDocument();
    expect(
      within(generalCard).getByText("settings.general.dateFormat"),
    ).toBeInTheDocument();
    expect(within(generalCard).getByText("English (EN)")).toBeInTheDocument();
  });

  it("offers only the languages the backend accepts", async () => {
    const user = userEvent.setup();
    render(<ConfigurationApp />);

    // The options only exist in the DOM once the dropdown is open, so this
    // click is what lets the assertion see an extra option at all.
    await user.click(languageSelect());

    const options = (await openOptions()).map((option) => option.textContent);
    expect(options).toEqual(["Deutsch (DE)", "English (EN)"]);
  });

  it("saves a changed language on the tenant row", async () => {
    const user = userEvent.setup();
    render(<ConfigurationApp />);

    await user.click(languageSelect());
    const german = (await openOptions()).find(
      (option) => option.textContent === "Deutsch (DE)",
    );
    await user.click(german as HTMLElement);
    await act(async () => {
      await stable.save?.();
    });

    const body = vi.mocked(tenantsTenantsPartialUpdate).mock.calls[0][1];
    expect(body).toMatchObject({ tenant_language: "de" });
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
