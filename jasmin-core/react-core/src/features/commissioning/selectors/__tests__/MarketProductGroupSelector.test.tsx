/**
 * MarketProductGroupSelector: all product groups or one active group, and back
 * to all once the picked group is switched off. Rendered inside a small page
 * that holds the pick in state, as the PLU list does. The generated
 * commissioning client is the mocking boundary: its product-groups hook is a
 * real TanStack query around a spy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketProductGroup } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
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

const api = vi.hoisted(() => ({ productGroups: vi.fn() }));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  return {
    useCommissioningMarketProductGroupsList: function useProductGroupsQuery(params: unknown) {
      return useQuery({
        queryKey: ["/api/commissioning/market_product_groups/", params],
        queryFn: async () => api.productGroups(params),
      });
    },
  };
});

import MarketProductGroupSelector from "../MarketProductGroupSelector";

// ── Fixtures ────────────────────────────────────────────────────────────────

const productGroup = (id: string, number: number, name: string) =>
  ({ id, number, name, is_active: true }) as MarketProductGroup;

const APPLES = productGroup("pg-apples", 4, "Apples");
const ROOTS = productGroup("pg-roots", 5, "Roots");

// ── Helpers ─────────────────────────────────────────────────────────────────

let picked: string | null = null;

function Page() {
  const [selected, setSelected] = useState<string | null>(null);
  picked = selected;
  return (
    <MarketProductGroupSelector
      selectedProductGroup={selected}
      setSelectedProductGroup={setSelected}
    />
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <Page />
    </QueryClientProvider>,
  );
  return {
    /** The groups are asked for again and answer with what's there now. */
    reload: () => act(() => queryClient.invalidateQueries()),
  };
}

const ALL = "commissioning.all_market_product_groups";

const groupSelect = () =>
  screen.getByRole("combobox", { name: "commissioning.filter_by_market_product_group" });
const shownGroup = () =>
  groupSelect().closest(".ant-select")?.querySelector(".ant-select-selection-item")
    ?.textContent ?? "";

/** The options of the open list. */
function shownOptions() {
  const open = document.querySelectorAll<HTMLElement>(
    ".ant-select-dropdown:not(.ant-select-dropdown-hidden)",
  );
  return Array.from(
    open[open.length - 1]?.querySelectorAll<HTMLElement>(".ant-select-item-option-content") ?? [],
  );
}

async function chooseGroup(label: string) {
  await userEvent.click(groupSelect());
  const option = await waitFor(() => {
    const found = shownOptions().find((content) => content.textContent === label);
    if (!found) throw new Error(`No product group ${label}`);
    return found;
  });
  await userEvent.click(option);
}

beforeEach(() => {
  picked = null;
  api.productGroups.mockReset().mockResolvedValue([APPLES, ROOTS]);
});

// ── The pick ────────────────────────────────────────────────────────────────

describe("MarketProductGroupSelector", () => {
  it("starts on all groups and offers the active ones by number and name", async () => {
    renderPage();
    await waitFor(() => expect(api.productGroups).toHaveBeenCalledWith({ is_active: true }));

    expect(shownGroup()).toBe(ALL);
    await userEvent.click(groupSelect());
    await waitFor(() =>
      expect(shownOptions().map((option) => option.textContent)).toEqual([
        ALL,
        "4 Apples",
        "5 Roots",
      ]),
    );
  });

  it("sends the chosen group to the page, and all of them as none", async () => {
    renderPage();
    await waitFor(() => expect(api.productGroups).toHaveBeenCalled());

    await chooseGroup("5 Roots");
    expect(picked).toBe(ROOTS.id);

    await chooseGroup(ALL);
    expect(picked).toBeNull();
  });

  it("goes back to all groups once the picked one is switched off", async () => {
    const page = renderPage();
    await waitFor(() => expect(api.productGroups).toHaveBeenCalled());
    await chooseGroup("5 Roots");
    expect(picked).toBe(ROOTS.id);

    api.productGroups.mockResolvedValue([APPLES]);
    await page.reload();

    await waitFor(() => expect(picked).toBeNull());
    expect(shownGroup()).toBe(ALL);
  });
});
