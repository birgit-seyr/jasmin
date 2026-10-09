/**
 * OfferGroupSelector: lists the offer groups, keeps one picked while there is
 * one, and lets the pick go once the list loads empty. Rendered inside a small
 * page that holds the pick in state, as Offers does. The generated
 * commissioning client is the mocking boundary: its offer-groups hook is a
 * real TanStack query around a spy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OfferGroup } from "@shared/api/generated/models";
import { flushMicrotasks } from "@/test/profileRenders";

const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
}));
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

const api = vi.hoisted(() => ({ offerGroups: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningOfferGroupsList: function useOfferGroupsQuery() {
      return useQuery({
        queryKey: ["/api/commissioning/offer_groups/"],
        queryFn: async () => api.offerGroups(),
      });
    },
  };
});

import OfferGroupSelector from "../OfferGroupSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const offerGroup = (id: string, name: string): OfferGroup => ({ id, name }) as OfferGroup;

const RESTAURANTS = offerGroup("og-restaurants", "Restaurants");
const SHOPS = offerGroup("og-shops", "Shops");

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;
const onOfferGroupChange = vi.fn();

type PageProps = { initialGroup?: string | null; preserveSelection?: boolean };

function Page({ initialGroup = null, preserveSelection }: PageProps) {
  const [selected, setSelected] = useState<string | null>(initialGroup);
  picked = selected;
  return (
    <OfferGroupSelector
      selectedOfferGroup={selected}
      setSelectedOfferGroup={setSelected}
      onOfferGroupChange={onOfferGroupChange}
      preserveSelection={preserveSelection}
    />
  );
}

function renderPage(props: PageProps = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <Page {...props} />
    </QueryClientProvider>,
  );
  return {
    /** The offer groups are asked for again and answer with what's there now. */
    reload: () => act(() => queryClient.invalidateQueries()),
  };
}

const PLACEHOLDER = "placeholder.offer_group_selector";

const groupSelect = () => screen.getByRole("combobox", { name: PLACEHOLDER });
const selectRoot = () => groupSelect().closest(".ant-select") as HTMLElement;
const shownGroup = () => selectRoot().querySelector(".ant-select-selection-item")?.textContent ?? "";
const placeholderShown = () =>
  selectRoot().querySelector(".ant-select-selection-placeholder")?.textContent ?? "";

async function chooseGroup(label: string) {
  await userEvent.click(groupSelect());
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  const option = Array.from(
    open[open.length - 1].querySelectorAll(".ant-select-item-option-content"),
  ).find((content) => content.textContent === label);
  if (!option) throw new Error(`No offer group ${label}`);
  await userEvent.click(option);
}

const settle = () => act(() => flushMicrotasks());

beforeEach(() => {
  picked = null;
  onOfferGroupChange.mockReset();
  api.offerGroups.mockReset().mockResolvedValue([RESTAURANTS, SHOPS]);
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("OfferGroupSelector picks", () => {
  it("picks the first offer group without telling the change callback", async () => {
    renderPage();

    await waitFor(() => expect(picked).toBe(RESTAURANTS.id));
    expect(shownGroup()).toBe("Restaurants");
    await settle();
    expect(onOfferGroupChange).not.toHaveBeenCalled();
  });

  it("sends the chosen offer group to the page and to the change callback", async () => {
    renderPage();
    await waitFor(() => expect(picked).toBe(RESTAURANTS.id));

    await chooseGroup("Shops");

    expect(picked).toBe(SHOPS.id);
    expect(onOfferGroupChange).toHaveBeenCalledWith(SHOPS.id);
  });

  it("drops the picked offer group once every group is gone", async () => {
    const page = renderPage();
    await waitFor(() => expect(picked).toBe(RESTAURANTS.id));
    await chooseGroup("Shops");

    api.offerGroups.mockResolvedValue([]);
    await page.reload();

    await waitFor(() => expect(picked).toBeNull());
    expect(placeholderShown()).toBe(PLACEHOLDER);
    expect(onOfferGroupChange).toHaveBeenCalledTimes(1);
  });

  it("picks nothing while no offer group exists", async () => {
    api.offerGroups.mockResolvedValue([]);
    renderPage();
    await waitFor(() => expect(api.offerGroups).toHaveBeenCalled());
    await settle();

    expect(picked).toBeNull();
    expect(placeholderShown()).toBe(PLACEHOLDER);
  });

  it("without preserving, keeps the picked group when every group is gone", async () => {
    const page = renderPage({ initialGroup: SHOPS.id, preserveSelection: false });
    await waitFor(() => expect(shownGroup()).toBe("Shops"));

    api.offerGroups.mockResolvedValue([]);
    await page.reload();
    await settle();

    expect(picked).toBe(SHOPS.id);
  });
});
