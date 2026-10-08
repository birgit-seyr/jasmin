/**
 * CratePriceModal: the net price history of one crate (the reusable-box
 * deposit), edited inline. Rendered through the real PriceEditorModal,
 * EditableTable, money / VAT column builders and time-bound column hooks; the
 * generated crate-price client is the mocking boundary, with the list hook a
 * real TanStack query around a spy that answers from an in-memory server.
 *
 * The clock is frozen on Monday 5 October 2026, which decides which price is
 * past, active or upcoming and which month the date pickers open on.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CrateNetPrice } from "@shared/api/generated/models/crateNetPrice";
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

// Per-test tenant settings; anything unset falls back to the caller's default.
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

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
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
    "/api/commissioning/crate_net_prices/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningCrateNetPricesListQueryKey: listKey,
    useCommissioningCrateNetPricesList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: listKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningCrateNetPricesCreate: (price: unknown) => api.create(price),
    commissioningCrateNetPricesPartialUpdate: (id: string, price: unknown) =>
      api.update(id, price),
    commissioningCrateNetPricesDestroy: (id: string) => api.destroy(id),
  };
});

import CratePriceModal from "../CratePriceModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);

function crateNetPrice(
  overrides: Partial<CrateNetPrice> & { id: string },
): CrateNetPrice {
  return {
    crate: "crate-euro",
    name: "Euro crate",
    short_name: "Euro",
    valid_from: "2025-01-06",
    valid_until: null,
    price: "1.50",
    tax_rate: "19.00",
    can_be_deleted: true,
    ...overrides,
  };
}

// Last year's price, closed.
const PAST_PRICE = crateNetPrice({
  id: "price-2025",
  valid_from: "2025-01-06",
  valid_until: "2025-12-28",
  price: "1.20",
});
// Today's price. The crate is in use, so the backend locks it.
const ACTIVE_PRICE = crateNetPrice({
  id: "price-2026",
  valid_from: "2025-12-29",
  valid_until: null,
  price: "1.50",
  can_be_deleted: false,
});

// What the server currently holds; the list request answers from it.
let serverPrices: CrateNetPrice[] = [];

const dayBefore = (isoDate: string) => {
  const date = new Date(`${isoDate}T12:00:00`);
  date.setDate(date.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderModal() {
  const onClose = vi.fn();
  const onSave = vi.fn();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(
        <CratePriceModal
          visible
          onClose={onClose}
          crate="crate-euro"
          crate_name="Euro crate"
          onSave={onSave}
        />,
      )}
    </QueryClientProvider>,
  );
  return { onClose, onSave, profiler };
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

function bodyRows(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"),
  );
}

/** The date picker dropdown open right now; a closed one stays in the DOM. */
function openCalendar(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-picker-dropdown"),
  ).filter((dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"));
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

function calendarCell(isoDate: string): HTMLElement {
  const cell = openCalendar().querySelector<HTMLElement>(`td[title="${isoDate}"]`);
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  return cell;
}

/** The validity status a row's status dot announces. */
const statusOf = (row: HTMLElement) =>
  within(row).getByRole("img", { name: /^members\./ }).getAttribute("aria-label");

async function openPicker(label: string) {
  await userEvent.click(within(editingRow()).getByLabelText(label));
}

async function pickDate(label: string, isoDate: string) {
  await openPicker(label);
  await userEvent.click(calendarCell(isoDate));
}

const VALID_FROM = "configuration.valid_from";
const VALID_UNTIL = "configuration.valid_until";
const PRICE = "commissioning.price_netto";
const VAT = "commissioning.tax_rate";
const DISABLED_CELL = "ant-picker-cell-disabled";

async function startNewPrice() {
  await userEvent.click(
    screen.getByRole("button", { name: /table\.add_plus_icon/ }),
  );
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
  api.create.mockReset().mockImplementation(async (price: CrateNetPrice) => {
    const saved = { ...price, id: "price-new", can_be_deleted: true };
    // The backend closes the open predecessor the day before the new price.
    serverPrices = [
      saved,
      ...serverPrices.map((row) =>
        row.valid_until === null && row.valid_from < price.valid_from
          ? { ...row, valid_until: dayBefore(price.valid_from) }
          : row,
      ),
    ];
    return saved;
  });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, price: CrateNetPrice) => {
      const saved = { ...price, id };
      serverPrices = serverPrices.map((row) => (row.id === id ? saved : row));
      return saved;
    });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverPrices = serverPrices.filter((row) => row.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Price history ───────────────────────────────────────────────────────────

describe("CratePriceModal price history", () => {
  it("loads the price history of the crate it was opened for", async () => {
    renderModal();

    expect(await screen.findByText("1,50 €")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledTimes(1);
    expect(api.list).toHaveBeenCalledWith({ crate: "crate-euro" });
    expect(
      within(screen.getByRole("dialog")).getByText(
        "commissioning.prices_for_crateEuro crate",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("commissioning.prices_are_netto")).toBeInTheDocument();
  });

  it("names the validity, net price and VAT columns", async () => {
    renderModal();
    await screen.findByText("1,50 €");

    expect(
      screen.getByRole("columnheader", { name: /configuration\.valid_from/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /configuration\.valid_until/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: PRICE }),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: VAT })).toBeInTheDocument();
  });

  it("shows each price's validity, net price and VAT in the tenant's formats", async () => {
    renderModal();
    await screen.findByText("1,50 €");

    const active = rowOf("1,50 €");
    expect(within(active).getByText("29.12.2025")).toBeInTheDocument();
    expect(within(active).getByText("19,00 %")).toBeInTheDocument();
    const past = rowOf("1,20 €");
    expect(within(past).getByText("06.01.2025")).toBeInTheDocument();
    expect(within(past).getByText("28.12.2025")).toBeInTheDocument();
  });

  it("lists an upcoming price first, then the active one, then past ones, each marked", async () => {
    serverPrices = [
      crateNetPrice({
        id: "price-2027",
        valid_from: "2026-11-02",
        valid_until: null,
        price: "1.75",
      }),
      { ...ACTIVE_PRICE, valid_until: "2026-11-01" },
      PAST_PRICE,
    ];
    renderModal();
    await screen.findByText("1,75 €");

    const rows = bodyRows();
    expect(rows.map(statusOf)).toEqual([
      "members.future_active",
      "members.currently_active",
      "members.currently_inactive",
    ]);
    expect(rows[0]).toHaveTextContent("1,75 €");
    expect(rows[1]).toHaveTextContent("1,50 €");
    expect(rows[2]).toHaveTextContent("1,20 €");
  });

  it("formats prices, VAT and dates in the tenant's own currency and formats", async () => {
    tenantSettings.values = {
      currency: "USD",
      number_locale: "en-US",
      date_format: "MM/DD/YYYY",
    };
    renderModal();

    await screen.findByText("$1.50");
    const active = rowOf("$1.50");
    expect(within(active).getByText("12/29/2025")).toBeInTheDocument();
    expect(within(active).getByText("19.00 %")).toBeInTheDocument();
    expect(screen.getByText("$1.20")).toBeInTheDocument();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();
    await screen.findByText("1,50 €");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── New price ───────────────────────────────────────────────────────────────

describe("CratePriceModal new price", () => {
  it("prefills a new price with the tenant's crate VAT rate", async () => {
    tenantSettings.values = { default_tax_rate_crates: "7.00" };
    renderModal();
    await screen.findByText("1,50 €");

    await startNewPrice();

    expect(within(editingRow()).getByLabelText(VAT)).toHaveValue("7,00");
  });

  it("falls back to 19 % VAT for a new crate price", async () => {
    renderModal();
    await screen.findByText("1,50 €");

    await startNewPrice();

    expect(within(editingRow()).getByLabelText(VAT)).toHaveValue("19");
  });

  it("only offers Mondays as the start of a price", async () => {
    renderModal();
    await screen.findByText("1,50 €");
    await startNewPrice();

    await openPicker(VALID_FROM);

    expect(calendarCell("2026-10-12")).not.toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-13")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-18")).toHaveClass(DISABLED_CELL);
  });

  it("only offers Sundays after the start as the end of a price", async () => {
    renderModal();
    await screen.findByText("1,50 €");
    await startNewPrice();
    await pickDate(VALID_FROM, "2026-10-12");

    await openPicker(VALID_UNTIL);

    expect(calendarCell("2026-10-11")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-17")).toHaveClass(DISABLED_CELL);
    expect(calendarCell("2026-10-18")).not.toHaveClass(DISABLED_CELL);
  });

  it("adds a price for the crate and shows the previous price closed the day before", async () => {
    const { onSave } = renderModal();
    await screen.findByText("1,50 €");

    await startNewPrice();
    await pickDate(VALID_FROM, "2026-10-12");
    await userEvent.type(within(editingRow()).getByLabelText(PRICE), "1,65");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        crate: "crate-euro",
        valid_from: "2026-10-12",
        price: "1.65",
        tax_rate: 19,
      }),
    );
    await screen.findByText("1,65 €");
    const newRow = rowOf("1,65 €");
    expect(within(newRow).getByText("12.10.2026")).toBeInTheDocument();
    expect(statusOf(newRow)).toBe("members.future_active");
    await waitFor(() =>
      expect(within(rowOf("1,50 €")).getByText("11.10.2026")).toBeInTheDocument(),
    );
    expect(api.list).toHaveBeenCalledTimes(2);
    // The crate list hears of the saved price.
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("accepts a negative net price but no negative VAT rate", async () => {
    renderModal();
    await screen.findByText("1,50 €");
    await startNewPrice();

    const vat = within(editingRow()).getByLabelText(VAT);
    await userEvent.clear(vat);
    await userEvent.type(vat, "-7");
    await userEvent.type(within(editingRow()).getByLabelText(PRICE), "-0,50");

    expect(vat).toHaveValue("7");
    expect(within(editingRow()).getByLabelText(PRICE)).toHaveValue("-0,50");

    await pickDate(VALID_FROM, "2026-10-12");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({ price: "-0.50", tax_rate: "7" }),
    );
  });

  it("refuses to save a new price without a start date and a VAT rate", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderModal();
    await screen.findByText("1,50 €");
    await startNewPrice();

    await userEvent.clear(within(editingRow()).getByLabelText(VAT));
    await userEvent.type(within(editingRow()).getByLabelText(PRICE), "1,65");
    await save();

    expect(
      await screen.findByText("table.save_failed_generic — table.save_failed_hint"),
    ).toBeInTheDocument();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(2);
    expect(within(editingRow()).getByLabelText(VAT)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(api.create).not.toHaveBeenCalled();
  });

  it("drops an unsaved new price when it is cancelled", async () => {
    renderModal();
    await screen.findByText("1,50 €");
    await startNewPrice();
    await userEvent.type(within(editingRow()).getByLabelText(PRICE), "9,99");

    await userEvent.click(
      within(editingRow()).getByRole("button", { name: "table.cancel" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    expect(
      screen.queryByRole("button", { name: "table.save" }),
    ).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
    expect(api.create).not.toHaveBeenCalled();
  });
});

// ── Existing prices ─────────────────────────────────────────────────────────

describe("CratePriceModal existing prices", () => {
  it("only lets the office end the active price of a crate in use", async () => {
    renderModal();
    await screen.findByText("1,50 €");

    const active = rowOf("1,50 €");
    expect(
      within(active).queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(active).getByRole("button", { name: "table.edit" }),
    );

    const row = editingRow();
    expect(within(row).queryByLabelText(VALID_FROM)).not.toBeInTheDocument();
    expect(within(row).queryByLabelText(PRICE)).not.toBeInTheDocument();
    expect(within(row).queryByLabelText(VAT)).not.toBeInTheDocument();
    await pickDate(VALID_UNTIL, "2026-10-25");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "price-2026",
      expect.objectContaining({
        crate: "crate-euro",
        valid_from: "2025-12-29",
        valid_until: "2026-10-25",
        price: "1.50",
        tax_rate: "19.00",
      }),
    );
    await waitFor(() =>
      expect(within(rowOf("1,50 €")).getByText("25.10.2026")).toBeInTheDocument(),
    );
  });

  it("corrects a price that is not in use, keeping its validity", async () => {
    const { onSave } = renderModal();
    await screen.findByText("1,20 €");

    await userEvent.click(
      within(rowOf("1,20 €")).getByRole("button", { name: "table.edit" }),
    );
    const row = editingRow();
    expect(within(row).getByLabelText(VALID_FROM)).toHaveValue("06.01.2025");
    const price = within(row).getByLabelText(PRICE);
    expect(price).toHaveValue("1,20");
    await userEvent.clear(price);
    await userEvent.type(price, "1,25");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "price-2025",
      expect.objectContaining({
        crate: "crate-euro",
        valid_from: "2025-01-06",
        valid_until: "2025-12-28",
        price: "1.25",
        tax_rate: "19.00",
      }),
    );
    expect(await screen.findByText("1,25 €")).toBeInTheDocument();
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("deletes a price that is not in use after confirmation", async () => {
    renderModal();
    await screen.findByText("1,20 €");

    await userEvent.click(
      within(rowOf("1,20 €")).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("price-2025"));
    await waitFor(() => expect(screen.queryByText("1,20 €")).not.toBeInTheDocument());
    expect(screen.getByText("1,50 €")).toBeInTheDocument();
  });

  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }])(
    "shows the price history read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      renderModal();
      await screen.findByText("1,50 €");

      expect(
        screen.queryByRole("button", { name: /table\.add_plus_icon/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "table.edit" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "table.delete" }),
      ).not.toBeInTheDocument();

      await userEvent.click(screen.getByText("1,20 €"));

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    },
  );
});
