/**
 * PriceEditorModal: the shell every price modal (crate, share article, extra
 * article, share type variation) is built on. It fetches the price rows of
 * one record through the list hook it is handed, edits them in the real
 * EditableTable, stamps the record onto every save and reloads the list after
 * each change. The list hook here is a real TanStack query around a spy that
 * answers from an in-memory server; the columns come from the real money and
 * VAT column builders.
 */

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TFunction } from "i18next";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

import { buildCurrencyPriceColumn, buildTaxRateColumn } from "../priceColumns";
import PriceEditorModal, { type PriceModalApi } from "../PriceEditorModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

interface ArticlePrice {
  id: string;
  article: string;
  note: string;
  price: string | null;
  tax_rate: string | number;
  can_be_deleted?: boolean;
}

const WINTER = {
  id: "price-winter",
  article: "art-carrot",
  note: "Winter",
  price: "2.40",
  tax_rate: "7.00",
  can_be_deleted: true,
};
// Already used on delivery notes, so the backend refuses to delete it.
const SUMMER = {
  id: "price-summer",
  article: "art-carrot",
  note: "Summer",
  price: "1.80",
  tax_rate: "7.00",
  can_be_deleted: false,
};

const LEEK_PRICE = {
  id: "price-leek",
  article: "art-leek",
  note: "Leek price",
  price: "0.95",
  tax_rate: "7.00",
  can_be_deleted: true,
};

const asT = ((key: string) => key) as unknown as TFunction;

const COLUMNS: EditableColumnConfig[] = [
  { title: "Note", dataIndex: "note", key: "note", inputType: "text" },
  buildCurrencyPriceColumn({
    title: "Price",
    dataIndex: "price",
    currencySymbol: "€",
    locale: "de-DE",
  }),
  buildTaxRateColumn(asT, { title: "VAT", locale: "de-DE" }),
];

// What the server currently holds; the list request answers from it.
let serverPrices: ArticlePrice[] = [];

const api = {
  list: vi.fn(),
  create: vi.fn(),
  partialUpdate: vi.fn(),
  destroy: vi.fn(),
};

const listQueryKey = (params: Record<string, string>) => [
  "/api/test/article_prices/",
  params,
];

function useArticlePriceList(
  params: Record<string, string>,
  options: { query: { enabled: boolean } },
) {
  return useQuery({
    queryKey: listQueryKey(params),
    queryFn: (): Promise<ArticlePrice[]> => api.list(params),
    enabled: options.query.enabled,
  });
}

const priceApi: PriceModalApi<ArticlePrice> = {
  create: (price) => api.create(price),
  partialUpdate: (id, price) => api.partialUpdate(id, price),
  destroy: (id) => api.destroy(id),
};

// ── Helpers ─────────────────────────────────────────────────────────────────

interface ModalProps {
  visible?: boolean;
  fkValue?: string | null;
  defaultTaxRate?: number;
  intro?: React.ReactNode;
  pagination?: boolean;
}

function renderModal(props: ModalProps = {}) {
  const onClose = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  const profiler = profileRenders();
  const ui = ({
    visible = true,
    fkValue = "art-carrot",
    defaultTaxRate,
    intro,
    pagination,
  }: ModalProps) => (
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(
        <PriceEditorModal<ArticlePrice>
          visible={visible}
          onClose={onClose}
          title="Prices for carrots"
          fkField="article"
          fkValue={fkValue}
          defaultTaxRate={defaultTaxRate}
          intro={intro}
          pagination={pagination}
          columns={COLUMNS}
          listHook={useArticlePriceList}
          getListQueryKey={listQueryKey}
          api={priceApi}
        />,
      )}
    </QueryClientProvider>
  );
  const view = render(ui(props));
  return {
    onClose,
    profiler,
    rerender: (next: ModalProps) => view.rerender(ui(next)),
  };
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

const addButton = () =>
  screen.queryByRole("button", { name: /table\.add_record/ });

beforeEach(() => {
  auth.roles = ["office"];
  serverPrices = [WINTER, SUMMER];
  api.list.mockReset().mockImplementation(async (params: { article: string }) =>
    serverPrices.filter((price) => price.article === params.article),
  );
  api.create.mockReset().mockImplementation(async (price: ArticlePrice) => {
    const saved = { ...price, id: "price-new", can_be_deleted: true };
    serverPrices = [saved, ...serverPrices];
    return saved;
  });
  api.partialUpdate
    .mockReset()
    .mockImplementation(async (id: string, price: ArticlePrice) => {
      const saved = { ...price, id };
      serverPrices = serverPrices.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverPrices = serverPrices.filter((row) => row.id !== id);
  });
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("PriceEditorModal loading", () => {
  it("loads nothing while closed", () => {
    renderModal({ visible: false });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
  });

  it("loads nothing while it has no record to price", async () => {
    renderModal({ fkValue: null });

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
  });

  it("loads the prices of the record it prices, formatted as money and VAT", async () => {
    renderModal();

    expect(await screen.findByText("2,40 €")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ article: "art-carrot" });
    expect(within(rowOf("Winter")).getByText("7,00 %")).toBeInTheDocument();
    expect(within(rowOf("Summer")).getByText("1,80 €")).toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog")).getByText("Prices for carrots"),
    ).toBeInTheDocument();
  });

  it("announces the first load instead of showing an empty table", async () => {
    let deliver: (rows: ArticlePrice[]) => void = () => {};
    api.list.mockImplementation(
      () =>
        new Promise<ArticlePrice[]>((resolve) => {
          deliver = resolve;
        }),
    );
    renderModal();

    expect(screen.getByRole("status")).toHaveTextContent("common.loading");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    deliver([WINTER]);

    expect(await screen.findByText("Winter")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();

    await screen.findByText("Winter");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Shell ───────────────────────────────────────────────────────────────────

describe("PriceEditorModal shell", () => {
  it("states that the prices are net, above the table and the status legend", async () => {
    renderModal();
    await screen.findByText("Winter");

    expect(
      screen.getByText("commissioning.prices_are_netto"),
    ).toBeInTheDocument();
  });

  it("shows the caller's own intro in place of the net-price note", async () => {
    renderModal({ intro: <p>Gross prices per delivery</p> });
    await screen.findByText("Winter");

    expect(screen.getByText("Gross prices per delivery")).toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.prices_are_netto"),
    ).not.toBeInTheDocument();
  });

  it("shows no intro when the caller passes an empty one", async () => {
    renderModal({ intro: <></> });
    await screen.findByText("Winter");

    expect(
      screen.queryByText("commissioning.prices_are_netto"),
    ).not.toBeInTheDocument();
  });

  it("pages the prices unless the caller turns the pager off", async () => {
    const { rerender } = renderModal();
    await screen.findByText("Winter");
    expect(document.querySelector(".ant-pagination")).toBeInTheDocument();

    rerender({ pagination: false });

    expect(document.querySelector(".ant-pagination")).not.toBeInTheDocument();
  });

  it("stacks above the configuration modal it is opened from", async () => {
    renderModal();
    await screen.findByText("Winter");

    const wrap = screen.getByRole("dialog").closest(".ant-modal-wrap");
    expect(wrap).toHaveStyle({ zIndex: "1100" });
  });

  it("closes from the footer button", async () => {
    const { onClose } = renderModal();
    await screen.findByText("Winter");

    await userEvent.click(screen.getByRole("button", { name: "common.close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts fresh when it is reopened for another record", async () => {
    const { rerender } = renderModal();
    await screen.findByText("Winter");
    await userEvent.click(addButton()!);
    expect(editingRow()).toBeInTheDocument();

    rerender({ visible: false });
    serverPrices = [WINTER, SUMMER, LEEK_PRICE];
    rerender({ visible: true, fkValue: "art-leek" });

    expect(await screen.findByText("Leek price")).toBeInTheDocument();
    expect(api.list).toHaveBeenLastCalledWith({ article: "art-leek" });
    expect(screen.queryByText("Winter")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.save" }),
    ).not.toBeInTheDocument();
  });
});

// ── Permissions ─────────────────────────────────────────────────────────────

describe("PriceEditorModal permissions", () => {
  it.each([{ roles: ["office"] }, { roles: ["admin"] }])(
    "lets $roles add, edit and delete prices",
    async ({ roles }) => {
      auth.roles = roles;
      renderModal();
      await screen.findByText("Winter");

      expect(addButton()).toBeEnabled();
      expect(
        within(rowOf("Winter")).getByRole("button", { name: "table.edit" }),
      ).toBeEnabled();
      expect(
        within(rowOf("Winter")).getByRole("button", { name: "table.delete" }),
      ).toBeEnabled();
    },
  );

  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }, { roles: ["management"] }])(
    "shows the prices read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      renderModal();
      await screen.findByText("Winter");

      expect(addButton()).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "table.edit" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "table.delete" }),
      ).not.toBeInTheDocument();

      await userEvent.click(screen.getByText("2,40 €"));

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    },
  );

  it("offers no delete for a price the backend marks as in use", async () => {
    renderModal();
    await screen.findByText("Summer");

    expect(
      within(rowOf("Summer")).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Summer")).getByRole("button", { name: "table.edit" }),
    ).toBeEnabled();
  });

  it("locks the price and VAT of a price the backend marks as in use", async () => {
    renderModal();
    await screen.findByText("Summer");

    await userEvent.click(
      within(rowOf("Summer")).getByRole("button", { name: "table.edit" }),
    );

    const row = editingRow();
    expect(within(row).queryByLabelText("Price")).not.toBeInTheDocument();
    expect(within(row).queryByLabelText("VAT")).not.toBeInTheDocument();
    expect(within(row).getByText("1,80 €")).toBeInTheDocument();
    expect(within(row).getByLabelText("Note")).toHaveValue("Summer");
  });
});

// ── Saving ──────────────────────────────────────────────────────────────────

describe("PriceEditorModal saving", () => {
  it("prefills a new price with the default VAT rate it is given", async () => {
    renderModal({ defaultTaxRate: 19 });
    await screen.findByText("Winter");

    await userEvent.click(addButton()!);

    expect(within(editingRow()).getByLabelText("VAT")).toHaveValue("19");
    expect(within(editingRow()).getByLabelText("Price")).toHaveValue("");
  });

  it("leaves the VAT of a new price empty without a default rate", async () => {
    renderModal();
    await screen.findByText("Winter");

    await userEvent.click(addButton()!);

    expect(within(editingRow()).getByLabelText("VAT")).toHaveValue("");
  });

  it("creates a price for the record, with a typed decimal comma sent as a point", async () => {
    renderModal({ defaultTaxRate: 7 });
    await screen.findByText("Winter");

    await userEvent.click(addButton()!);
    await userEvent.type(within(editingRow()).getByLabelText("Note"), "Spring");
    await userEvent.type(within(editingRow()).getByLabelText("Price"), "2,15");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        article: "art-carrot",
        note: "Spring",
        price: "2.15",
        tax_rate: 7,
      }),
    );
    expect(await screen.findByText("2,15 €")).toBeInTheDocument();
  });

  it("reloads the list after a new price, so the server's changes to the other prices show", async () => {
    api.create.mockImplementation(async (price: ArticlePrice) => {
      const saved = { ...price, id: "price-new", can_be_deleted: true };
      // The backend re-prices its neighbour when a new price starts.
      serverPrices = [
        saved,
        { ...WINTER, note: "Winter (closed)" },
        SUMMER,
      ];
      return saved;
    });
    renderModal({ defaultTaxRate: 7 });
    await screen.findByText("Winter");

    await userEvent.click(addButton()!);
    await userEvent.type(within(editingRow()).getByLabelText("Price"), "2.15");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    expect(await screen.findByText("Winter (closed)")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledTimes(2);
    expect(screen.getByText("2,15 €")).toBeInTheDocument();
  });

  it("saves an edited price under its id, with the record attached, and reloads the list", async () => {
    renderModal();
    await screen.findByText("Winter");

    await userEvent.click(
      within(rowOf("Winter")).getByRole("button", { name: "table.edit" }),
    );
    const priceInput = within(editingRow()).getByLabelText("Price");
    expect(priceInput).toHaveValue("2,40");
    await userEvent.clear(priceInput);
    await userEvent.type(priceInput, "2,55");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    await waitFor(() => expect(api.partialUpdate).toHaveBeenCalledTimes(1));
    expect(api.partialUpdate).toHaveBeenCalledWith(
      "price-winter",
      expect.objectContaining({
        article: "art-carrot",
        price: "2.55",
        tax_rate: "7.00",
      }),
    );
    expect(await screen.findByText("2,55 €")).toBeInTheDocument();
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  });

  it("deletes a price after confirmation and reloads the list", async () => {
    renderModal();
    await screen.findByText("Winter");

    await userEvent.click(
      within(rowOf("Winter")).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("price-winter"));
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Winter")).not.toBeInTheDocument();
    expect(screen.getByText("Summer")).toBeInTheDocument();
  });

  it("keeps the new price open and shows the server's reason when the save is refused", async () => {
    api.create.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          code: "validation_error",
          message: "Ensure that there are no more than 3 digits before the decimal point.",
          details: {
            price: [
              "Ensure that there are no more than 3 digits before the decimal point.",
            ],
          },
        },
      },
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderModal({ defaultTaxRate: 7 });
    await screen.findByText("Winter");

    await userEvent.click(addButton()!);
    await userEvent.type(within(editingRow()).getByLabelText("Price"), "1250");
    await userEvent.click(screen.getByRole("button", { name: "table.save" }));

    expect(
      await screen.findByText(
        "Price: Ensure that there are no more than 3 digits before the decimal point. — table.save_failed_hint",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("table.save_failed_title")).toBeInTheDocument();
    expect(within(editingRow()).getByLabelText("Price")).toHaveValue("1250");
    expect(within(editingRow()).getByLabelText("Price")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(api.list).toHaveBeenCalledTimes(1);
  });

  it("keeps a price the server refuses to delete and shows why", async () => {
    api.destroy.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          code: "validation_error",
          message: "This price is already used on a delivery note.",
        },
      },
    });
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderModal();
    await screen.findByText("Winter");

    await userEvent.click(
      within(rowOf("Winter")).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    expect(
      await screen.findByText("This price is already used on a delivery note."),
    ).toBeInTheDocument();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Winter")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledTimes(1);
  });
});
