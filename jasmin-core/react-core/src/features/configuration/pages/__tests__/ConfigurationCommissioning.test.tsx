/**
 * ConfigurationCommissioning: which commissioning settings the office gets,
 * in which card. The settings page that renders and saves them is a stub that
 * keeps the settings it was handed and shows what each one carries under its
 * control; the window of the stations' surcharges is a stub that says whether
 * it is open.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
// How the farm packs its share sizes, whether it imports its share amounts,
// buys produce in, sells to resellers and at markets, per test.
const farm = vi.hoisted(() => ({
  packingMode: "BOXES",
  importsShareAmounts: false,
  hasPurchases: true,
  sellsToResellers: true,
  hasMarkets: true,
}));
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, fallback?: unknown) => {
      if (key === "packing_mode") return farm.packingMode;
      if (key === "uploads_weekly_share_amount") return farm.importsShareAmounts;
      if (key === "has_purchases") return farm.hasPurchases;
      if (key === "sells_to_resellers") return farm.sellsToResellers;
      if (key === "has_markets") return farm.hasMarkets;
      return fallback;
    },
  });
  return {
    useCapability: (name: string) => capabilities[name] ?? true,
    useTenant: () => tenant,
  };
});

const shown = vi.hoisted(() => ({ settings: [] as SettingsCategory[] }));
vi.mock("@features/configuration/components/SettingsPage", () => ({
  default: ({ settingsConfig }: { settingsConfig: SettingsCategory[] }) => {
    shown.settings = settingsConfig;
    return (
      <>
        {settingsConfig.flatMap((category) =>
          category.settings.map((setting) => (
            <div key={setting.key}>{setting.extra}</div>
          )),
        )}
      </>
    );
  },
}));

vi.mock("@features/configuration/modals", () => ({
  StationBulkPercentagesModal: ({ open }: { open: boolean }) =>
    open ? <div>station percentages window</div> : null,
}));

import ConfigurationCommissioning from "../ConfigurationCommissioning";

const categories = () => shown.settings.map((category) => category.category);
const keysOf = (name: string) =>
  shown.settings
    .find((category) => category.category === name)
    ?.settings.map((setting) => setting.key);

const SELLER_NAME = "show_seller_name_of_share_article_in_share_for_member_on_page";
const BULK_PERCENTAGE = "percentage_added_to_bulk_packing_list";
const PACKING_STATIONS = "number_packing_stations";
const STATION_PERCENTAGES = "settings.commissioning.station_bulk_percentages.button";

beforeEach(() => {
  for (const name of Object.keys(capabilities)) delete capabilities[name];
  shown.settings = [];
  farm.packingMode = "BOXES";
  farm.importsShareAmounts = false;
  farm.hasPurchases = true;
  farm.sellsToResellers = true;
  farm.hasMarkets = true;
});

describe("ConfigurationCommissioning cards", () => {
  it("groups the settings by task", () => {
    render(<ConfigurationCommissioning />);

    expect(categories()).toEqual([
      "share_planning",
      "packing",
      "work_steps",
      "lists",
      "member_pages",
      "tax_rates",
    ]);
    expect(keysOf("work_steps")).toEqual(["show_washing", "show_cleaning"]);
    expect(keysOf("share_planning")).toEqual([
      "default_planning_granularity",
      "distribute_forecast_by_weight",
      "show_summary_in_harvest_share_planning_on_top",
    ]);
    expect(keysOf("lists")).toEqual(["show_size_column"]);
  });
});

describe("ConfigurationCommissioning packing", () => {
  it("offers the packing stations, and no packing mode, where every size goes out pre-packed", () => {
    render(<ConfigurationCommissioning />);

    expect(keysOf("packing")).toEqual([PACKING_STATIONS]);
    expect(screen.queryByRole("button", { name: STATION_PERCENTAGES })).not.toBeInTheDocument();
  });

  it("offers the loose lists' surcharges where every size goes out loose", () => {
    farm.packingMode = "BULK";
    render(<ConfigurationCommissioning />);

    expect(keysOf("packing")).toEqual([BULK_PERCENTAGE]);
    expect(screen.getByRole("button", { name: STATION_PERCENTAGES })).toBeInTheDocument();
  });

  it("offers both where the sizes differ, the stations' surcharges right under the loose one", () => {
    farm.packingMode = "MIXED";
    render(<ConfigurationCommissioning />);

    expect(keysOf("packing")).toEqual([BULK_PERCENTAGE, PACKING_STATIONS]);
    const [bulkPercentage, packingStations] =
      shown.settings.find((category) => category.category === "packing")?.settings ?? [];
    expect(bulkPercentage.extra).toBeTruthy();
    expect(packingStations.extra).toBeUndefined();
    expect(screen.getByRole("button", { name: STATION_PERCENTAGES })).toBeInTheDocument();
  });

  it("opens the stations' surcharges from their button", async () => {
    farm.packingMode = "BULK";
    render(<ConfigurationCommissioning />);
    expect(screen.queryByText("station percentages window")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: STATION_PERCENTAGES }));

    expect(screen.getByText("station percentages window")).toBeInTheDocument();
  });
});

describe("ConfigurationCommissioning member pages", () => {
  it("offers the seller's name in the members' boxes where members use jasmin's logins", () => {
    render(<ConfigurationCommissioning />);

    expect(keysOf("member_pages")).toEqual([SELLER_NAME]);
  });

  it("leaves it out where a host handles the logins and members never see jasmin", () => {
    capabilities.user_accounts = false;
    render(<ConfigurationCommissioning />);

    expect(categories()).not.toContain("member_pages");
  });

  it("leaves it out on a farm that buys nothing in, as there is no seller to name", () => {
    farm.hasPurchases = false;
    render(<ConfigurationCommissioning />);

    expect(categories()).not.toContain("member_pages");
  });
});

describe("ConfigurationCommissioning tax rates", () => {
  const taxRateKeys = () =>
    shown.settings
      .find((category) => category.category === "tax_rates")
      ?.settings.map((setting) => setting.key);

  it("offers a default rate for articles, crates and shares", () => {
    render(<ConfigurationCommissioning />);

    expect(taxRateKeys()).toEqual([
      "default_tax_rate_articles",
      "default_tax_rate_crates",
      "default_tax_rate_shares",
    ]);
  });

  it("leaves out the shares' rate where the share amounts are imported", () => {
    farm.importsShareAmounts = true;
    render(<ConfigurationCommissioning />);

    expect(taxRateKeys()).toEqual(["default_tax_rate_articles", "default_tax_rate_crates"]);
  });

  it("leaves out the crates' rate on a farm that sells to no reseller, keeping the articles' for its markets", () => {
    farm.sellsToResellers = false;
    render(<ConfigurationCommissioning />);

    expect(taxRateKeys()).toEqual(["default_tax_rate_articles", "default_tax_rate_shares"]);
  });

  it("keeps the articles' and crates' rates on a farm that sells to resellers but at no market", () => {
    farm.hasMarkets = false;
    render(<ConfigurationCommissioning />);

    expect(taxRateKeys()).toEqual([
      "default_tax_rate_articles",
      "default_tax_rate_crates",
      "default_tax_rate_shares",
    ]);
  });

  it("leaves out the articles' rate too on a farm that sells neither to resellers nor at markets", () => {
    farm.sellsToResellers = false;
    farm.hasMarkets = false;
    render(<ConfigurationCommissioning />);

    expect(taxRateKeys()).toEqual(["default_tax_rate_shares"]);
  });

  it("shows no tax rates at all where the farm charges tax on none of them", () => {
    farm.sellsToResellers = false;
    farm.hasMarkets = false;
    farm.importsShareAmounts = true;
    render(<ConfigurationCommissioning />);

    expect(categories()).not.toContain("tax_rates");
  });
});
