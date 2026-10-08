/**
 * ShareArticlePriceModal: the net price history of one share article — the
 * prices used for members' shares per unit (kg / pieces / bunch) and the
 * reseller prices per unit and offer tier. Rendered through the real
 * PriceEditorModal, EditableTable, column builders and hooks; the generated
 * share-article-price client is the mocking boundary, with the list hook a
 * real TanStack query around a spy that answers from an in-memory server.
 *
 * The clock is frozen on Monday 5 October 2026.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticleNetPrice } from "@shared/api/generated/models/shareArticleNetPrice";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// The canonical mock, except that interpolation values are appended to the
// key, so a column title shows the tier threshold and currency it is for.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string"
        ? fallback
        : fallback && typeof fallback === "object"
          ? `${key}(${Object.entries(fallback)
              .map(([name, value]) => `${name}=${String(value)}`)
              .join(",")})`
          : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const tenantSettings = vi.hoisted(() => ({
  values: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const listKey = (params?: unknown) => [
    "/api/commissioning/share_article_net_prices/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningShareArticleNetPricesListQueryKey: listKey,
    useCommissioningShareArticleNetPricesList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: listKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningShareArticleNetPricesCreate: (price: unknown) =>
      api.create(price),
    commissioningShareArticleNetPricesPartialUpdate: (
      id: string,
      price: unknown,
    ) => api.update(id, price),
    commissioningShareArticleNetPricesDestroy: (id: string) => api.destroy(id),
  };
});

import ShareArticlePriceModal from "../ShareArticlePriceModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);

const NO_PRICES = {
  net_price_for_boxes_kg: null,
  net_price_for_boxes_pieces: null,
  net_price_for_boxes_bunch: null,
  net_price_for_orders_kg_1: null,
  net_price_for_orders_kg_2: null,
  net_price_for_orders_kg_3: null,
  net_price_for_orders_pieces_1: null,
  net_price_for_orders_pieces_2: null,
  net_price_for_orders_pieces_3: null,
  net_price_for_orders_bunch_1: null,
  net_price_for_orders_bunch_2: null,
  net_price_for_orders_bunch_3: null,
};

// Carrots are sold by the kilo: a share price and three reseller tiers.
const ACTIVE_PRICE: ShareArticleNetPrice = {
  ...NO_PRICES,
  id: "snp-2026",
  share_article: "art-carrot",
  share_article_name: "Carrots",
  valid_from: "2026-01-05",
  valid_until: null,
  tax_rate: "7.00",
  net_price_for_boxes_kg: "2.40",
  net_price_for_orders_kg_1: "2.10",
  net_price_for_orders_kg_2: "1.95",
  net_price_for_orders_kg_3: "1.80",
  can_be_deleted: true,
};
const PAST_PRICE: ShareArticleNetPrice = {
  ...NO_PRICES,
  id: "snp-2025",
  share_article: "art-carrot",
  share_article_name: "Carrots",
  valid_from: "2025-01-06",
  valid_until: "2026-01-04",
  tax_rate: "7.00",
  net_price_for_boxes_kg: "2.20",
  net_price_for_orders_kg_1: "1.90",
  can_be_deleted: true,
};

const PRICE_FIELDS = Object.keys(NO_PRICES);

// The serializer stores an emptied price cell as no price.
const asStored = (price: ShareArticleNetPrice): ShareArticleNetPrice => {
  const stored: Record<string, unknown> = { ...price };
  for (const field of PRICE_FIELDS) {
    if (stored[field] === "" || stored[field] === undefined) stored[field] = null;
  }
  return stored as unknown as ShareArticleNetPrice;
};

let serverPrices: ShareArticleNetPrice[] = [];

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderModal() {
  const profiler = profileRenders();
  const onSave = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(
        <ShareArticlePriceModal
          visible
          onClose={vi.fn()}
          onSave={onSave}
          share_article="art-carrot"
          share_article_name="Carrots"
        />,
      )}
    </QueryClientProvider>,
  );
  return { onSave, profiler };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const headerTexts = () =>
  screen
    .getAllByRole("columnheader")
    .map((header) => header.textContent?.trim() ?? "");

const resellerHeaders = () =>
  headerTexts().filter((text) => text.startsWith("commissioning.reseller_"));

/** The money amounts a row shows, in column order. */
const amountsIn = (row: HTMLElement) =>
  within(row)
    .getAllByText(/ (€|CHF)$/)
    .map((cell) => cell.textContent);

const boxField = (unit: string, symbol = "€") =>
  `commissioning.box_price_${unit}(currencySymbol=${symbol})`;
const resellerField = (unit: string, tier: 1 | 2 | 3, threshold: number) =>
  `commissioning.reseller_${unit}_tier${tier}(tier=${threshold},currencySymbol=€)`;

async function pickValidFrom(isoDate: string) {
  await userEvent.click(
    within(editingRow()).getByLabelText("configuration.valid_from"),
  );
  const cell = document.querySelector<HTMLElement>(`td[title="${isoDate}"]`);
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  await userEvent.click(cell);
}

async function typeInto(label: string, value: string) {
  const input = within(editingRow()).getByLabelText(label);
  await userEvent.clear(input);
  if (value) await userEvent.type(input, value);
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  auth.roles = ["office"];
  serverPrices = [ACTIVE_PRICE, PAST_PRICE];
  api.list.mockReset().mockImplementation(async () => [...serverPrices]);
  api.create
    .mockReset()
    .mockImplementation(async (price: ShareArticleNetPrice) => {
      const saved = asStored({ ...price, id: "snp-new", can_be_deleted: true });
      serverPrices = [saved, ...serverPrices];
      return saved;
    });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, price: ShareArticleNetPrice) => {
      const saved = asStored({ ...price, id });
      serverPrices = serverPrices.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Columns ─────────────────────────────────────────────────────────────────

describe("ShareArticlePriceModal columns", () => {
  it("loads the prices of the article it was opened for", async () => {
    renderModal();

    expect(await screen.findByText("2,40 €")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ share_article: "art-carrot" });
    expect(
      within(screen.getByRole("dialog")).getByText(
        "commissioning.prices_for_articleCarrots",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("commissioning.prices_are_netto")).toBeInTheDocument();
  });

  it("groups share prices per unit and one reseller price per unit when the tenant has no tiers", async () => {
    renderModal();
    await screen.findByText("2,40 €");

    const headers = headerTexts();
    expect(headers).toContain("commissioning.for_shares");
    expect(headers).toContain("commissioning.for_resellers");
    expect(headers).toEqual(
      expect.arrayContaining([
        boxField("kg"),
        boxField("pieces"),
        boxField("bunch"),
      ]),
    );
    expect(resellerHeaders()).toEqual([
      resellerField("kg", 1, 1),
      resellerField("pieces", 1, 1),
      resellerField("bunch", 1, 1),
    ]);
  });

  it("offers a reseller price per unit for every tier, titled with the tier's threshold", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 5, 10] };
    renderModal();
    await screen.findByText("2,40 €");

    expect(resellerHeaders()).toEqual([
      resellerField("kg", 1, 1),
      resellerField("kg", 2, 5),
      resellerField("kg", 3, 10),
      resellerField("pieces", 1, 1),
      resellerField("pieces", 2, 5),
      resellerField("pieces", 3, 10),
      resellerField("bunch", 1, 1),
      resellerField("bunch", 2, 5),
      resellerField("bunch", 3, 10),
    ]);
  });

  it("shows each set price as money and leaves unset prices empty", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 5, 10] };
    renderModal();
    await screen.findByText("2,40 €");

    const active = rowOf("2,40 €");
    expect(amountsIn(active)).toEqual(["2,40 €", "2,10 €", "1,95 €", "1,80 €"]);
    expect(within(active).getByText("7,00 %")).toBeInTheDocument();
    expect(amountsIn(rowOf("2,20 €"))).toEqual(["2,20 €", "1,90 €"]);
  });

  it("titles and formats the prices in the tenant's currency", async () => {
    tenantSettings.values = { currency: "CHF" };
    renderModal();

    expect(await screen.findByText("2,40 CHF")).toBeInTheDocument();
    expect(headerTexts()).toContain(boxField("kg", "CHF"));
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();
    await screen.findByText("2,40 €");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("ShareArticlePriceModal saving", () => {
  it("prefills a new price with the tenant's article VAT rate", async () => {
    tenantSettings.values = { default_tax_rate_articles: "10.00" };
    renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      screen.getByRole("button", { name: /table\.add_plus_icon/ }),
    );

    expect(
      within(editingRow()).getByLabelText("commissioning.tax_rate"),
    ).toHaveValue("10,00");
  });

  it("falls back to 7 % VAT for a new article price", async () => {
    renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      screen.getByRole("button", { name: /table\.add_plus_icon/ }),
    );

    expect(
      within(editingRow()).getByLabelText("commissioning.tax_rate"),
    ).toHaveValue("7");
  });

  it("adds a price with a share price and a reseller price per tier", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 5, 10] };
    const { onSave } = renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      screen.getByRole("button", { name: /table\.add_plus_icon/ }),
    );
    await pickValidFrom("2026-10-12");
    await typeInto(boxField("kg"), "2,60");
    await typeInto(resellerField("kg", 1, 1), "2,30");
    await typeInto(resellerField("kg", 2, 5), "2,15");
    await typeInto(resellerField("kg", 3, 10), "1,99");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const payload = api.create.mock.calls[0][0];
    expect(payload).toEqual(
      expect.objectContaining({
        share_article: "art-carrot",
        valid_from: "2026-10-12",
        tax_rate: 7,
        net_price_for_boxes_kg: "2.60",
        net_price_for_orders_kg_1: "2.30",
        net_price_for_orders_kg_2: "2.15",
        net_price_for_orders_kg_3: "1.99",
      }),
    );
    expect(payload.net_price_for_boxes_pieces).toBeUndefined();
    await screen.findByText("2,60 €");
    expect(amountsIn(rowOf("2,60 €"))).toEqual([
      "2,60 €",
      "2,30 €",
      "2,15 €",
      "1,99 €",
    ]);
    // The article list hears of the saved price.
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("corrects one tier price of a saved price and keeps the others", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 5, 10] };
    const { onSave } = renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      within(rowOf("2,40 €")).getByRole("button", { name: "table.edit" }),
    );
    expect(
      within(editingRow()).getByLabelText(resellerField("kg", 2, 5)),
    ).toHaveValue("1,95");
    await typeInto(resellerField("kg", 2, 5), "1,89");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "snp-2026",
      expect.objectContaining({
        share_article: "art-carrot",
        valid_from: "2026-01-05",
        tax_rate: "7.00",
        net_price_for_boxes_kg: "2.40",
        net_price_for_orders_kg_1: "2.10",
        net_price_for_orders_kg_2: "1.89",
        net_price_for_orders_kg_3: "1.80",
      }),
    );
    await waitFor(() =>
      expect(amountsIn(rowOf("2,40 €"))).toEqual([
        "2,40 €",
        "2,10 €",
        "1,89 €",
        "1,80 €",
      ]),
    );
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("keeps the reseller prices of tiers the tenant no longer uses when a price is edited", async () => {
    renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      within(rowOf("2,40 €")).getByRole("button", { name: "table.edit" }),
    );
    await typeInto(boxField("kg"), "2,45");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        net_price_for_boxes_kg: "2.45",
        net_price_for_orders_kg_1: "2.10",
        net_price_for_orders_kg_2: "1.95",
        net_price_for_orders_kg_3: "1.80",
      }),
    );
  });

  it("removes a price when its cell is emptied", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 5, 10] };
    renderModal();
    await screen.findByText("2,40 €");

    await userEvent.click(
      within(rowOf("2,40 €")).getByRole("button", { name: "table.edit" }),
    );
    await typeInto(resellerField("kg", 3, 10), "");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1].net_price_for_orders_kg_3).toBe("");
    await waitFor(() =>
      expect(amountsIn(rowOf("2,40 €"))).toEqual(["2,40 €", "2,10 €", "1,95 €"]),
    );
  });

  it("shows the prices read-only to staff without the office role", async () => {
    auth.roles = ["staff"];
    renderModal();
    await screen.findByText("2,40 €");

    expect(
      screen.queryByRole("button", { name: /table\.add_plus_icon/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.edit" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("2,10 €"));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
