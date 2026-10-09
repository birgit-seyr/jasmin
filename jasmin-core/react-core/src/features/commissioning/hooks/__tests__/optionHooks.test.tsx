/**
 * The option hooks behind the commissioning selects and grids hand out the
 * same option array for as long as their query holds the same rows, so a
 * consumer that puts the options in a memo or effect dependency list doesn't
 * recompute on every render. The generated commissioning client is the
 * mocking boundary: each list hook answers with whatever rows the test holds.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Crate, Offer, Plot, ShareTypeVariation, Storage } from "@shared/api/generated/models";

const i18nMock = vi.hoisted(() => ({ t: (key: string) => key }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const rows = vi.hoisted(() => ({
  storages: undefined as unknown[] | undefined,
  plots: undefined as unknown[] | undefined,
  variations: undefined as unknown[] | undefined,
  offers: undefined as unknown[] | undefined,
  crates: undefined as unknown[] | undefined,
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => {
  const answer = (data: unknown[] | undefined) => ({
    data,
    isLoading: false,
    error: null,
    refetch: () => {},
  });
  return {
    useCommissioningStoragesList: () => answer(rows.storages),
    useCommissioningPlotsList: () => answer(rows.plots),
    useCommissioningShareTypeVariationsList: () => answer(rows.variations),
    useCommissioningOffersList: () => answer(rows.offers),
    useCommissioningCratesList: () => answer(rows.crates),
  };
});

import { useCrates } from "../useCrates";
import { useOfferOptions } from "../useOfferOptions";
import { usePlots } from "../usePlots";
import { useShareTypeVariations } from "../useShareTypeVariations";
import { useStorages } from "../useStorages";

const COLD_ROOM: Storage = { id: "st-cold", name: "Cold room" };
const NORTH_FIELD: Plot = { id: "plot-north", name: "North field" };
const SMALL: ShareTypeVariation = { id: "stv-s", size: "S" } as ShareTypeVariation;
const CARROT_OFFER: Offer = {
  id: "offer-carrots",
  share_article_name: "Carrots",
  unit: "KG",
  amount_per_pu: "10",
} as Offer;
const GREEN_CRATE: Crate = { id: "crate-green", name: "Green crate", short_name: "GC" } as Crate;

// The params objects are built once, as a page that memoises its params does.
const OFFER_PARAMS = { reseller: "res-1", year: 2026, delivery_week: 41 };
const VARIATION_PARAMS = {};

interface OptionHookCase {
  name: string;
  key: keyof typeof rows;
  row: { id?: string | null };
  useOptions: () => ReadonlyArray<{ value: string | null }>;
}

const hooks: OptionHookCase[] = [
  {
    name: "useStorages",
    key: "storages",
    row: COLD_ROOM,
    useOptions: () => useStorages().storages,
  },
  {
    name: "usePlots",
    key: "plots",
    row: NORTH_FIELD,
    useOptions: () => usePlots().plots,
  },
  {
    name: "useShareTypeVariations",
    key: "variations",
    row: SMALL,
    useOptions: () => useShareTypeVariations(VARIATION_PARAMS).shareTypeVariations,
  },
  {
    name: "useOfferOptions",
    key: "offers",
    row: CARROT_OFFER,
    useOptions: () => useOfferOptions(OFFER_PARAMS).offers,
  },
  {
    name: "useCrates",
    key: "crates",
    row: GREEN_CRATE,
    useOptions: () => useCrates().crates,
  },
];

beforeEach(() => {
  rows.storages = undefined;
  rows.plots = undefined;
  rows.variations = undefined;
  rows.offers = undefined;
  rows.crates = undefined;
});

describe.each(hooks)("$name options", ({ key, row, useOptions }) => {
  it("stay the same array across renders while the rows don't change", () => {
    rows[key] = [row];
    const { result, rerender } = renderHook(useOptions);
    const first = result.current;

    rerender();
    rerender();

    expect(result.current).toBe(first);
  });

  it("stay the same array across renders while nothing has loaded", () => {
    const { result, rerender } = renderHook(useOptions);
    const first = result.current;

    rerender();

    expect(result.current).toBe(first);
  });

  it("are rebuilt when the rows change", () => {
    rows[key] = [row];
    const { result, rerender } = renderHook(useOptions);
    const first = result.current;

    rows[key] = [row, { ...row, id: `${row.id}-2` }];
    rerender();

    expect(result.current).not.toBe(first);
    expect(result.current.map((option) => option.value)).toContain(`${row.id}-2`);
  });
});

describe("option labels", () => {
  it("label offers by article, unit and amount per packaging unit", () => {
    rows.offers = [CARROT_OFFER];
    const { result } = renderHook(() => useOfferOptions(OFFER_PARAMS));

    expect(result.current.offers.map((offer) => offer.label)).toEqual([
      "Carrots [commissioning.units.kg] - (10 commissioning.units.kg/VPE)",
    ]);
    expect(result.current.offersCount).toBe(1);
  });

  it("put a 'no plot' entry first and count only the plots", () => {
    rows.plots = [NORTH_FIELD];
    const { result } = renderHook(() => usePlots());

    expect(result.current.plots.map((plot) => plot.value)).toEqual([null, NORTH_FIELD.id]);
    expect(result.current.countPlots).toBe(1);
  });
});
