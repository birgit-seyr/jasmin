// The PLU list renders through the real useCrudListPage and EditableTable; only
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
        data: [
          { id: "pg-apples", is_active: true, number: 4, name: "Apples", can_be_deleted: false },
          { id: "pg-pears", is_active: true, number: 5, name: "Pears", can_be_deleted: true },
        ],
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

/** Picks `label` in the select that is open. */
async function pickOpenOption(user: ReturnType<typeof userEvent.setup>, label: string) {
  const option = await waitFor(() => {
    const found = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.textContent === label);
    if (!found) throw new Error(`No ${label} is offered`);
    return found;
  });
  await user.click(option);
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
  it("lists each PLU with its label, sort, article and product group", async () => {
    renderList();

    await screen.findByText("Elstar apple");
    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent ?? "");
    const columnOf = (title: string) =>
      headers.findIndex((header) => header.includes(title));
    expect(columnOf("commissioning.market_label")).toBe(
      columnOf("commissioning.plu_number") + 1,
    );
    expect(columnOf("commissioning.market_linked_share_article")).toBe(
      columnOf("commissioning.sort") + 1,
    );
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
    const [pluNumber, name] = within(row).getAllByRole("textbox");
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
    await pickOpenOption(user, "4 Apples");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1]).toMatchObject({ product_group: "pg-apples" });
  });

  it("shows only the PLUs of the picked product group, and all of them again", async () => {
    const { user } = renderList();
    await screen.findByText("Topaz apple");
    const groupFilter = screen.getByRole("combobox", {
      name: "commissioning.filter_by_market_product_group",
    });

    await user.click(groupFilter);
    await pickOpenOption(user, "4 Apples");

    await waitFor(() => expect(screen.queryByText("Topaz apple")).not.toBeInTheDocument());
    expect(screen.getByText("Elstar apple")).toBeInTheDocument();
    expect(screen.queryByText("Lime blossom honey 500g")).not.toBeInTheDocument();

    await user.click(groupFilter);
    await pickOpenOption(user, "commissioning.all_market_product_groups");

    expect(await screen.findByText("Topaz apple")).toBeInTheDocument();
    expect(screen.getByText("Lime blossom honey 500g")).toBeInTheDocument();
  });

  it("moves a PLU filed under another group out of the picked group's list", async () => {
    api.update.mockImplementation(async (id: string, payload: MarketArticle) => ({
      ...ELSTAR, ...payload, id, product_group_name: "Pears",
    }));
    const { user } = renderList();
    await screen.findByText("Elstar apple");
    const groupFilter = screen.getByRole("combobox", {
      name: "commissioning.filter_by_market_product_group",
    });
    await user.click(groupFilter);
    await pickOpenOption(user, "4 Apples");
    await waitFor(() => expect(screen.queryByText("Topaz apple")).not.toBeInTheDocument());

    await user.click(within(rowOf("Elstar apple")).getByRole("button", { name: "table.edit" }));
    const row = screen.getByRole("button", { name: "table.save" }).closest("tr")!;
    await user.click(
      within(row).getByRole("combobox", { name: "commissioning.market_product_group" }),
    );
    await pickOpenOption(user, "5 Pears");
    await user.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("Elstar apple")).not.toBeInTheDocument());

    await user.click(groupFilter);
    await pickOpenOption(user, "5 Pears");
    expect(await screen.findByText("Elstar apple")).toBeInTheDocument();
  });

  it("files a new PLU under the picked product group, and shows it there only", async () => {
    // The server lists what was saved.
    const saved: MarketArticle[] = [];
    api.list.mockImplementation(async () => [ELSTAR, TOPAZ, HONEY, ...saved]);
    api.create.mockImplementation(async (payload: MarketArticle) => {
      const created = {
        ...plu({ id: "plu-new", plu_number: 103, name: "" }),
        ...payload,
        id: "plu-new",
        product_group_name: "Apples",
      };
      saved.push(created);
      return created;
    });
    const { user } = renderList();
    await screen.findByText("Topaz apple");
    const groupFilter = screen.getByRole("combobox", {
      name: "commissioning.filter_by_market_product_group",
    });
    await user.click(groupFilter);
    await pickOpenOption(user, "4 Apples");
    await waitFor(() => expect(screen.queryByText("Topaz apple")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /table\.add_record/ }));
    const row = screen.getByRole("button", { name: "table.save" }).closest("tr")!;
    const [pluNumber, name] = within(row).getAllByRole("textbox");
    await user.type(pluNumber, "103");
    await user.type(name, "Boskoop apple");
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
    expect(api.create.mock.calls[0][0]).toMatchObject({ product_group: "pg-apples" });
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));

    await user.click(groupFilter);
    await pickOpenOption(user, "5 Pears");
    await waitFor(() => expect(screen.queryByText("Boskoop apple")).not.toBeInTheDocument());

    await user.click(groupFilter);
    await pickOpenOption(user, "4 Apples");
    expect(await screen.findByText("Boskoop apple")).toBeInTheDocument();
  });

  it("pages through a long list", async () => {
    api.list.mockResolvedValue(
      Array.from({ length: 12 }, (_, index) =>
        plu({ id: `plu-${index}`, plu_number: 500 + index, name: `Pear ${index}` }),
      ),
    );
    renderList();

    await screen.findByText("Pear 0");
    expect(screen.getAllByText(/^Pear \d+$/)).toHaveLength(10);
  });

  it("saves a relabelled PLU under its id", async () => {
    const { user } = renderList();
    await screen.findByText("Topaz apple");

    await user.click(within(rowOf("Topaz apple")).getByRole("button", { name: "table.edit" }));
    const [, name] = editedInputs();
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
