/**
 * ShareArticleExtraPriceModal: the net price history of an extra article
 * (sold per piece only, e.g. a bottle of juice), with one reseller price per
 * offer tier. Rendered through the real PriceEditorModal, EditableTable,
 * column builders and hooks; the generated share-article-price client is the
 * mocking boundary, with the list hook a real TanStack query around a spy
 * that answers from an in-memory server.
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

import ShareArticleExtraPriceModal from "../ShareArticleExtraPriceModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);

// Apple juice by the bottle: cheaper from 6 and from 12 bottles.
const ACTIVE_PRICE: ShareArticleNetPrice = {
  id: "snp-juice-2026",
  share_article: "art-juice",
  share_article_name: "Apple juice",
  valid_from: "2026-01-05",
  valid_until: null,
  tax_rate: "19.00",
  net_price_for_boxes_kg: null,
  net_price_for_boxes_pieces: null,
  net_price_for_boxes_bunch: null,
  net_price_for_orders_kg_1: null,
  net_price_for_orders_kg_2: null,
  net_price_for_orders_kg_3: null,
  net_price_for_orders_pieces_1: "3.20",
  net_price_for_orders_pieces_2: "2.95",
  net_price_for_orders_pieces_3: null,
  net_price_for_orders_bunch_1: null,
  net_price_for_orders_bunch_2: null,
  net_price_for_orders_bunch_3: null,
  can_be_deleted: true,
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
        <ShareArticleExtraPriceModal
          visible
          onClose={vi.fn()}
          onSave={onSave}
          share_article="art-juice"
          share_article_name="Apple juice"
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

/** The titled column headers, in order. */
const headerTexts = () =>
  screen
    .getAllByRole("columnheader")
    .map((header) => header.textContent?.trim() ?? "")
    .filter(Boolean);

const amountsIn = (row: HTMLElement) =>
  within(row)
    .getAllByText(/ €$/)
    .map((cell) => cell.textContent);

const piecesField = (tier: 1 | 2 | 3, threshold: number) =>
  `commissioning.reseller_pieces_tier${tier}(tier=${threshold},currencySymbol=€)`;
const VAT = "commissioning.tax_rate";

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
  serverPrices = [ACTIVE_PRICE];
  api.list.mockReset().mockImplementation(async () => [...serverPrices]);
  api.create
    .mockReset()
    .mockImplementation(async (price: ShareArticleNetPrice) => {
      const saved = { ...price, id: "snp-juice-new", can_be_deleted: true };
      serverPrices = [saved, ...serverPrices];
      return saved;
    });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, price: ShareArticleNetPrice) => {
      const saved = { ...price, id };
      serverPrices = serverPrices.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Columns ─────────────────────────────────────────────────────────────────

describe("ShareArticleExtraPriceModal columns", () => {
  it("loads the prices of the extra article it was opened for", async () => {
    renderModal();

    expect(await screen.findByText("3,20 €")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ share_article: "art-juice" });
    expect(
      within(screen.getByRole("dialog")).getByText(
        "commissioning.prices_for_articleApple juice",
      ),
    ).toBeInTheDocument();
  });

  it("offers a single reseller piece price, then the VAT, when the tenant has no tiers", async () => {
    renderModal();
    await screen.findByText("3,20 €");

    expect(headerTexts()).toEqual([
      "table.actions",
      "configuration.valid_from",
      "configuration.valid_until",
      piecesField(1, 1),
      VAT,
    ]);
  });

  it("offers a piece price for every tier, titled with the tier's threshold", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 6, 12] };
    renderModal();
    await screen.findByText("3,20 €");

    expect(headerTexts()).toEqual([
      "table.actions",
      "configuration.valid_from",
      "configuration.valid_until",
      piecesField(1, 1),
      piecesField(2, 6),
      piecesField(3, 12),
      VAT,
    ]);
  });

  it("shows each set price as money and leaves an unset tier empty", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 6, 12] };
    renderModal();
    await screen.findByText("3,20 €");

    const row = rowOf("3,20 €");
    expect(amountsIn(row)).toEqual(["3,20 €", "2,95 €"]);
    expect(within(row).getByText("19,00 %")).toBeInTheDocument();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();
    await screen.findByText("3,20 €");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("ShareArticleExtraPriceModal saving", () => {
  it("prefills a new price with the tenant's article VAT rate", async () => {
    tenantSettings.values = { default_tax_rate_articles: "7.00" };
    renderModal();
    await screen.findByText("3,20 €");

    await userEvent.click(
      screen.getByRole("button", { name: /table\.add_plus_icon/ }),
    );

    expect(within(editingRow()).getByLabelText(VAT)).toHaveValue("7,00");
  });

  it("adds a price with a piece price per tier and its own VAT rate", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 6, 12] };
    const { onSave } = renderModal();
    await screen.findByText("3,20 €");

    await userEvent.click(
      screen.getByRole("button", { name: /table\.add_plus_icon/ }),
    );
    await userEvent.click(
      within(editingRow()).getByLabelText("configuration.valid_from"),
    );
    const monday = document.querySelector<HTMLElement>(
      'td[title="2026-10-12"]',
    );
    if (!monday) throw new Error("No calendar cell for 2026-10-12");
    await userEvent.click(monday);
    await typeInto(piecesField(1, 1), "3,40");
    await typeInto(piecesField(2, 6), "3,10");
    await typeInto(piecesField(3, 12), "2,90");
    await typeInto(VAT, "19");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        share_article: "art-juice",
        valid_from: "2026-10-12",
        tax_rate: "19",
        net_price_for_orders_pieces_1: "3.40",
        net_price_for_orders_pieces_2: "3.10",
        net_price_for_orders_pieces_3: "2.90",
      }),
    );
    await screen.findByText("3,40 €");
    expect(amountsIn(rowOf("3,40 €"))).toEqual(["3,40 €", "3,10 €", "2,90 €"]);
    // The extra-article list hears of the saved price.
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("corrects one tier price of a saved price and keeps the other", async () => {
    tenantSettings.values = { used_tiers_for_offers: [1, 6] };
    const { onSave } = renderModal();
    await screen.findByText("3,20 €");

    await userEvent.click(
      within(rowOf("3,20 €")).getByRole("button", { name: "table.edit" }),
    );
    await typeInto(piecesField(2, 6), "2,89");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "snp-juice-2026",
      expect.objectContaining({
        share_article: "art-juice",
        tax_rate: "19.00",
        net_price_for_orders_pieces_1: "3.20",
        net_price_for_orders_pieces_2: "2.89",
      }),
    );
    expect(await screen.findByText("2,89 €")).toBeInTheDocument();
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("shows the prices read-only to staff without the office role", async () => {
    auth.roles = ["staff"];
    renderModal();
    await screen.findByText("3,20 €");

    expect(
      screen.queryByRole("button", { name: /table\.add_plus_icon/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.edit" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("3,20 €"));

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
