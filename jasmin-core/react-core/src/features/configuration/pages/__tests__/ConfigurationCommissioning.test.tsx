/**
 * ConfigurationCommissioning: which commissioning settings the office gets.
 * The settings page that renders and saves them is a stub that keeps the
 * settings it was handed.
 */
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SettingsCategory } from "@features/configuration/components/SettingsRenderer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// What the deployment offers, per test; a name left out is offered.
const capabilities = vi.hoisted(() => ({}) as Record<string, boolean>);
// The farm's packing mode and its running and upcoming sizes, per test.
const farm = vi.hoisted(() => ({
  packingMode: "BOXES",
  sizes: [] as { share_type_name: string; size: string; is_packed_bulk: boolean }[],
}));
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, fallback?: unknown) =>
      key === "packing_mode" ? farm.packingMode : fallback,
  });
  return {
    useCapability: (name: string) => capabilities[name] ?? true,
    useTenant: () => tenant,
    useShareTypeVariationSizeOptions: () => ({
      getShareTypeVariationSizeLabel: (size: string) => size,
    }),
  };
});
vi.mock("@features/commissioning/hooks", () => ({
  useShareTypeVariations: () => ({ shareTypeVariations: farm.sizes }),
}));

const shown = vi.hoisted(() => ({ settings: [] as SettingsCategory[] }));
vi.mock("@features/configuration/components/SettingsPage", () => ({
  default: ({ settingsConfig }: { settingsConfig: SettingsCategory[] }) => {
    shown.settings = settingsConfig;
    return null;
  },
}));

import ConfigurationCommissioning from "../ConfigurationCommissioning";

const layoutKeys = () =>
  shown.settings
    .find((category) => category.category === "layout")
    ?.settings.map((setting) => setting.key);

const SELLER_NAME = "show_seller_name_of_share_article_in_share_for_member_on_page";

beforeEach(() => {
  for (const name of Object.keys(capabilities)) delete capabilities[name];
  shown.settings = [];
  farm.packingMode = "BOXES";
  farm.sizes = [];
});

/** The packing mode's options that can't be picked, with their reasons. */
const lockedPackingModes = () =>
  Object.fromEntries(
    (
      shown.settings
        .find((category) => category.category === "logistics")
        ?.settings.find((setting) => setting.key === "packing_mode")?.options ?? []
    )
      .filter((option) => option.disabled)
      .map((option) => [option.value, option.disabledReason]),
  );

describe("ConfigurationCommissioning packing mode", () => {
  it("keeps every option open without running sizes", () => {
    render(<ConfigurationCommissioning />);

    expect(lockedPackingModes()).toEqual({});
  });

  it("locks the switch from boxes to bulk while sizes run, whatever flag they kept", () => {
    farm.sizes = [{ share_type_name: "Gemüse", size: "M", is_packed_bulk: true }];
    render(<ConfigurationCommissioning />);

    expect(lockedPackingModes()).toEqual({
      BULK: "settings.commissioning.packing_mode_locked",
    });
  });

  it("locks boxes in mixed mode while a size is packed loose, never mixed", () => {
    farm.packingMode = "MIXED";
    farm.sizes = [
      { share_type_name: "Gemüse", size: "M", is_packed_bulk: true },
      { share_type_name: "Gemüse", size: "L", is_packed_bulk: true },
    ];
    render(<ConfigurationCommissioning />);

    expect(lockedPackingModes()).toEqual({
      BOXES: "settings.commissioning.packing_mode_locked",
    });
  });
});

describe("ConfigurationCommissioning layout", () => {
  it("lets the office show or hide washing and cleaning", () => {
    render(<ConfigurationCommissioning />);

    expect(layoutKeys()).toEqual(expect.arrayContaining(["show_washing", "show_cleaning"]));
  });

  it("offers the seller's name in the members' boxes where members use jasmin's logins", () => {
    render(<ConfigurationCommissioning />);

    expect(layoutKeys()).toContain(SELLER_NAME);
  });

  it("leaves it out where a host handles the logins and members never see jasmin", () => {
    capabilities.user_accounts = false;
    render(<ConfigurationCommissioning />);

    expect(layoutKeys()).not.toContain(SELLER_NAME);
    expect(layoutKeys()).toContain("show_size_column");
  });
});

describe("ConfigurationCommissioning sales", () => {
  it("lets the office turn the markets on", () => {
    render(<ConfigurationCommissioning />);

    const markets = shown.settings
      .find((category) => category.category === "sales")
      ?.settings.find((setting) => setting.key === "has_markets");
    expect(markets).toBeDefined();
    expect(markets?.disabled).toBeFalsy();
  });
});
