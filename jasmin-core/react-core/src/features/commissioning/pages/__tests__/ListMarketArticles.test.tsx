// The PLU list renders through the real CrudListPage and EditableTable; only
// the generated commissioning client is replaced (the list hook by a real
// TanStack query around a spy).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarketArticle } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The signed-in user's roles; `useRoles` derives the office gate from them.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock(
  "@shared/api/generated/commissioning/commissioning",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@shared/api/generated/commissioning/commissioning")
      >();
    const { useQuery } = await import("@tanstack/react-query");
    return {
      ...actual,
      useCommissioningMarketArticlesList: (params?: unknown) =>
        useQuery({
          queryKey: ["/api/commissioning/market_articles/", params],
          queryFn: (): Promise<MarketArticle[]> => api.list(params),
        }),
      useCommissioningShareArticlesList: () => ({
        data: [{ id: "art-apple", name: "Apple", default_movement_unit: "KG" }],
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
      useCommissioningMarketProductGroupsList: () => ({
        data: [{ id: "pg-apples", is_active: true, number: 4, name: "Apples", can_be_deleted: false }],
        isLoading: false,
      }),
      useCommissioningScaleTaxCodesList: () => ({
        data: [{ id: "tc-7", tax_rate: "7.00", code: 1, can_be_deleted: false }],
        isLoading: false,
      }),
      commissioningMarketArticlesCreate: (plu: MarketArticle) => api.create(plu),
      commissioningMarketArticlesPartialUpdate: (id: string, plu: MarketArticle) =>
        api.update(id, plu),
      commissioningMarketArticlesDestroy: (id: string) => api.destroy(id),
    };
  },
);

import ListMarketArticles from "../ListMarketArticles";

const plu = (fields: Partial<MarketArticle> & { id: string; plu_number: number; name: string }): MarketArticle => ({
  is_active: true, share_article: "art-apple", share_article_name: "Apple", unit: "KG",
  size: "M", sort: null, allows_price_override: true, allows_discount_price: true,
  product_group: null, product_group_name: null, scale_tax_code: "tc-7",
  can_be_deleted: true, ...fields,
});
// Priced, so it can't go.
const ELSTAR = plu({
  id: "plu-101", plu_number: 101, name: "Elstar apple", sort: "Elstar",
  product_group: "pg-apples", product_group_name: "Apples", can_be_deleted: false,
});
const TOPAZ = plu({ id: "plu-102", plu_number: 102, name: "Topaz apple", sort: "Topaz" });
// Bought in, so it names no article.
const HONEY = plu({
  id: "plu-3501", plu_number: 3501, name: "Lime blossom honey 500g", unit: "PCS",
  share_article: null, share_article_name: null,
});

function renderList() {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ListMarketArticles />
    </QueryClientProvider>,
  );
  return { user };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** The text inputs of the row being edited inline, in column order. */
function editedInputs(): HTMLElement[] {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return within(row).getAllByRole("textbox");
}

beforeEach(() => {
  auth.roles = ["office"];
  api.list.mockReset().mockResolvedValue([ELSTAR, TOPAZ, HONEY]);
  api.create.mockReset().mockImplementation(async (payload: MarketArticle) => ({
    ...plu({ id: "plu-new", plu_number: 0, name: "" }), ...payload, id: "plu-new",
  }));
  api.update.mockReset().mockImplementation(async (id: string, payload: MarketArticle) => ({
    ...TOPAZ, ...payload, id,
  }));
  api.destroy.mockReset();
});

describe("ListMarketArticles", () => {
  it("lists each PLU with its article, sort, label and product group", async () => {
    renderList();

    await screen.findByText("Elstar apple");
    const elstar = rowOf("Elstar apple");
    expect(within(elstar).getByText("101")).toBeInTheDocument();
    expect(within(elstar).getByText("Apple")).toBeInTheDocument();
    expect(within(elstar).getByText("Elstar")).toBeInTheDocument();
    expect(within(elstar).getByText("4 Apples")).toBeInTheDocument();
    expect(within(rowOf("Topaz apple")).queryByText("4 Apples")).not.toBeInTheDocument();
    expect(within(elstar).getByText("7,00 % (1)")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_market_articles")).toBeInTheDocument();
  });

  it("lists a PLU of bought-in goods without an article", async () => {
    renderList();

    await screen.findByText("Lime blossom honey 500g");
    const honey = rowOf("Lime blossom honey 500g");
    expect(within(honey).queryByText("Apple")).not.toBeInTheDocument();
    expect(within(honey).getByText("7,00 % (1)")).toBeInTheDocument();
  });

  it("adds a PLU without article and leaves its scale code to the server", async () => {
    const { user } = renderList();
    await screen.findByText("Topaz apple");

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    const row = screen.getByRole("button", { name: "table.save" }).closest("tr")!;
    const [pluNumber, , name] = within(row).getAllByRole("textbox");
    await user.type(pluNumber, "3502");
    await user.type(name, "Acacia honey 500g");
    await user.click(within(row).getByRole("combobox", { name: "commissioning.unit" }));
    await user.click(
      await waitFor(() => {
        const option = document.querySelector<HTMLElement>(
          ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
        );
        if (!option) throw new Error("No unit is offered");
        return option;
      }),
    );
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const [payload] = api.create.mock.calls[0];
    expect(Number(payload.plu_number)).toBe(3502);
    expect(payload.name).toBe("Acacia honey 500g");
    expect(payload.share_article ?? null).toBeNull();
    expect(payload).not.toHaveProperty("scale_tax_code");
  });

  it("files a PLU under a product group", async () => {
    const { user } = renderList();
    await screen.findByText("Topaz apple");

    await user.click(within(rowOf("Topaz apple")).getByRole("button", { name: "table.edit" }));
    const row = screen.getByRole("button", { name: "table.save" }).closest("tr")!;
    await user.click(
      within(row).getByRole("combobox", { name: "commissioning.market_product_group" }),
    );
    const option = await waitFor(() => {
      const found = Array.from(
        document.querySelectorAll<HTMLElement>(
          ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
        ),
      ).find((item) => item.textContent === "4 Apples");
      if (!found) throw new Error("No 4 Apples is offered");
      return found;
    });
    await user.click(option);
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1]).toMatchObject({ product_group: "pg-apples" });
  });

  it("saves a relabelled PLU under its id", async () => {
    const { user } = renderList();
    await screen.findByText("Topaz apple");

    await user.click(within(rowOf("Topaz apple")).getByRole("button", { name: "table.edit" }));
    const name = editedInputs().at(-1)!;
    await user.clear(name);
    await user.type(name, "Topaz apple, organic");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][0]).toBe("plu-102");
    expect(api.update.mock.calls[0][1]).toMatchObject({
      name: "Topaz apple, organic",
      share_article: "art-apple",
      unit: "KG",
    });
  });

  it("offers no delete for a PLU with prices", async () => {
    renderList();
    await screen.findByText("Elstar apple");

    expect(
      within(rowOf("Elstar apple")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Topaz apple")).getByRole("button", { name: "table.delete" }),
    ).toBeInTheDocument();
  });

  it("shows the PLUs read-only to staff", async () => {
    auth.roles = ["staff"];
    renderList();
    await screen.findByText("Elstar apple");

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
  });
});
