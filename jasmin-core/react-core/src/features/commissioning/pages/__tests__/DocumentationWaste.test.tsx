/**
 * DocumentationWaste: what went to waste on one day from one storage — the
 * article, its unit and size, the amount and a note — recorded, corrected and
 * deleted inline. Rendered through the real week, day and storage selectors,
 * EditableTable, column hooks and phone cards. The generated commissioning
 * client is the mocking boundary: its hooks are real TanStack queries around
 * spies that answer from an in-memory farm, and its mutations change that farm
 * the way the backend does, echoing the saved row. The article form behind
 * "add article" is a stub.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41, day number 1).
 * The clock is set before the imports run as well as before every test; the
 * page reads "today" when it mounts, so a test can move it before rendering.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle, Storage, Waste } from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

// One ``t`` for every call, as the real hook keeps it stable across renders.
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

// Phone or desktop viewport, per test.
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@hooks/configuration/useIsMobile", () => ({
  useIsMobile: () => viewport.mobile,
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({
  useModal: () => ({ isModalMode: false }),
}));

// ``useRoles`` is real; it reads the roles of the signed-in user from here.
const auth = vi.hoisted(() => ({ roles: ["gardener"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: auth.roles } }),
}));

const api = vi.hoisted(() => ({
  list: vi.fn(), storages: vi.fn(), shareArticles: vi.fn(),
  create: vi.fn(), update: vi.fn(), destroy: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) => [
    `/api/commissioning/${path}/`,
    ...(params ? [params] : []),
  ];
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown, options?: { query?: { enabled?: boolean } }) {
      const enabled = options?.query?.enabled;
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params), enabled });
    };
  return {
    useCommissioningWasteList: queryHook("waste", api.list),
    getCommissioningWasteListQueryKey: (params?: unknown) => queryKey("waste", params),
    useCommissioningStoragesList: queryHook("storages", api.storages),
    useCommissioningShareArticlesList: queryHook("share_articles", api.shareArticles),
    commissioningWasteCreate: (waste: unknown) => api.create(waste),
    commissioningWastePartialUpdate: (id: string, waste: unknown) => api.update(id, waste),
    commissioningWasteDestroy: (id: string) => api.destroy(id),
  };
});

// The page needs only the article form behind "add article"; the barrel would
// also load every other modal of the app. The form is a stub whose "create"
// adds an article to the farm, as saving the real one does.
vi.mock("@features/commissioning/modals", () => ({
  ShareArticleModal: function ShareArticleModal(props: {
    isOpen: boolean;
    onSuccess?: (saved: Record<string, unknown>) => void;
  }) {
    const create = () => {
      farm.articles = [...farm.articles, CHARD];
      props.onSuccess?.({ ...CHARD });
    };
    return props.isOpen ? (
      <div role="dialog" aria-label="commissioning.add_share_article">
        <button type="button" onClick={create}>create share article</button>
      </div>
    ) : null;
  },
}));

import DocumentationWaste from "../DocumentationWaste";
import {
  COLD_STORE,
  TUESDAY_IN_COLD_STORE,
  STORAGES,
  CARROTS,
  LETTUCE,
  RADISHES,
  POTATOES,
  LEEKS,
  BEETROOT,
  CHARD,
  TUESDAY,
  waste,
  CARROTS_WASTE,
  LETTUCE_WASTE,
  POTATOES_WASTE,
  RADISHES_WASTE,
  LEEKS_WASTE,
  decimal,
  type WasteRow,
  type Payload,
} from "./documentationWaste.fixtures";

// ── Fixtures ────────────────────────────────────────────────────────────────

/** What the in-memory farm holds; the request spies answer from it. */
let farm: { storages: Storage[]; articles: ShareArticle[]; wastes: WasteRow[] };
let createdCount = 0;

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<DocumentationWaste />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const STORAGE = "placeholder.storage_selector";
const DAY = "common.delivery_day";
const WEEK = "common.week";
const ARTICLE = "commissioning.vegetables_and_fruits";
const UNIT = "commissioning.unit";
const SIZE = "commissioning.size";
const AMOUNT = "commissioning.amount";
const NOTE = "commissioning.note";
const ADD_ROW = /table\.add_plus_icon/;
const ADD_ARTICLE = /commissioning\.add_share_article/;
const EDIT_OR_DELETE = /table\.(edit|delete)/;

/**
 * The same number in either decimal notation, with or without trailing zeros:
 * amountText(4) matches "4", "4,0", "4.00" and "4,00".
 */
function amountText(value: number): RegExp {
  const [whole, fraction = ""] = String(value).split(".");
  return new RegExp(fraction ? `^${whole}[.,]${fraction}0*$` : `^${whole}(?:[.,]0+)?$`);
}

/** The label a select shows for its current value. */
const selectionOf = (combobox: HTMLElement) =>
  combobox.closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ?? "";
const selectedIn = (name: string) => selectionOf(screen.getByRole("combobox", { name }));

function openDropdown(): HTMLElement {
  const open = document.querySelectorAll<HTMLElement>(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
  if (open.length === 0) throw new Error("No select dropdown is open");
  return open[open.length - 1];
}

async function choose(combobox: HTMLElement, option: string) {
  await userEvent.click(combobox);
  await userEvent.click(within(openDropdown()).getByText(option));
}

const chooseIn = (name: string, option: string) => choose(screen.getByRole("combobox", { name }), option);

/** The previous / next arrow beside a stepped selector. */
function arrow(name: string, direction: "common.previous" | "common.next") {
  const stepper = screen.getByRole("combobox", { name }).closest<HTMLElement>(".ant-space");
  if (!stepper) throw new Error(`No stepper around ${name}`);
  return within(stepper).getByRole("button", { name: direction });
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const headerTexts = () => screen.getAllByRole("columnheader").map((header) => header.textContent ?? "");

/** The cell of ``row`` under the column whose header reads ``header``. */
function cellIn(row: HTMLElement, header: string): HTMLElement {
  const column = headerTexts().indexOf(header);
  if (column < 0) throw new Error(`No column ${header}`);
  return within(row).getAllByRole("cell")[column];
}

const cellOf = (name: string, header: string) => cellIn(rowOf(name), header);

/** The row being edited: the one whose amount is an input. */
function editingRow(): HTMLElement {
  const row = screen.getByRole("textbox", { name: AMOUNT }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

const save = () => userEvent.click(screen.getByRole("button", { name: "table.save" }));
const startNewRow = () => userEvent.click(screen.getByRole("button", { name: ADD_ROW }));
const chooseArticle = (name: string) =>
  choose(within(editingRow()).getByRole("combobox", { name: ARTICLE }), name);
const editingDone = () =>
  waitFor(() => expect(screen.queryByRole("textbox", { name: AMOUNT })).not.toBeInTheDocument());

/** The phone card of an article. */
function cardOf(name: string): HTMLElement {
  const cards = Array.from(document.querySelectorAll<HTMLElement>(".mobile-card-item"));
  const card = cards.find((item) => item.querySelector(".mobile-card-title")?.textContent === name);
  if (!card) throw new Error(`No card shows ${name}`);
  return card;
}

const findCard = (name: string) => waitFor(() => cardOf(name));

/** What a phone card lists below its title: each field's label and value. */
const detailsOf = (card: HTMLElement) =>
  Object.fromEntries(
    Array.from(card.querySelectorAll(".mobile-card-detail"), (detail) => {
      const label = detail.querySelector(".mobile-card-detail-label")?.textContent ?? "";
      return [label.replace(/:$/, ""), (detail.textContent ?? "").slice(label.length).trim()];
    }),
  );

const tableIsBusy = () => document.querySelector('.ant-table-wrapper [aria-busy="true"]') !== null;

/** A request that answers only when the test says so. */
function pending<T>() {
  let answer!: (value: T) => void;
  const promise = new Promise<T>((resolve) => (answer = resolve));
  return { promise, answer };
}

/** An API refusal in the canonical error shape. */
const refusal = (message: string, details: Record<string, unknown> = {}) => ({
  isAxiosError: true,
  message: "Request failed with status code 400",
  response: { status: 400, data: { code: "validation_error", message, details } },
});

const lastListRequest = () => api.list.mock.lastCall?.[0];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  viewport.mobile = false;
  auth.roles = ["gardener"];
  createdCount = 0;
  farm = {
    storages: [...STORAGES],
    articles: [CARROTS, LETTUCE, RADISHES, POTATOES, LEEKS, BEETROOT],
    wastes: [CARROTS_WASTE, LETTUCE_WASTE, POTATOES_WASTE, RADISHES_WASTE, LEEKS_WASTE],
  };
  api.storages.mockReset().mockImplementation(async () => [...farm.storages]);
  api.shareArticles.mockReset().mockImplementation(async () => [...farm.articles]);
  api.list.mockReset().mockImplementation(async (params: Payload) =>
    farm.wastes.filter(
      (row) =>
        row.year === params.year &&
        row.delivery_week === params.delivery_week &&
        row.day_number === params.day_number,
    ),
  );
  // Create and update answer with the saved row, as the API does.
  api.create.mockReset().mockImplementation(async (payload: Payload) => {
    const ofArticle = farm.articles.find((each) => each.id === payload.share_article);
    const storage = farm.storages.find((each) => each.id === payload.storage);
    if (!ofArticle || !storage) throw refusal("Unknown article or storage");
    createdCount += 1;
    const when = { week: payload.delivery_week as number, day: payload.day_number as number };
    const row = waste(`waste-new-${createdCount}`, ofArticle, storage, when, {
      year: payload.year as number,
      unit: payload.unit as Waste["unit"],
      size: payload.size as Waste["size"],
      amount: decimal(payload.amount),
      note: (payload.note as string | undefined) ?? "",
    });
    farm.wastes = [...farm.wastes, row];
    return row;
  });
  api.update.mockReset().mockImplementation(async (id: string, payload: Payload) => {
    const change = { amount: decimal(payload.amount), note: (payload.note as string | undefined) ?? "" };
    farm.wastes = farm.wastes.map((row) => (row.id === id ? { ...row, ...change } : row));
    return farm.wastes.find((row) => row.id === id);
  });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    farm.wastes = farm.wastes.filter((row) => row.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("DocumentationWaste loading", () => {
  it("opens on today in the first storage and lists the waste thrown away from there", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "commissioning.documentation_waste" })).toBeInTheDocument();
    expect(selectedIn(STORAGE)).toBe("Cold store");
    expect(selectedIn(DAY)).toBe("Tuesday, 06.10.2026");
    expect(api.storages).toHaveBeenCalledWith({ is_active: true });
    expect(api.shareArticles).toHaveBeenCalledWith({ is_active: true });
    expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 41, day_number: 1, is_past: false });
    // The potatoes were thrown away from the root cellar.
    expect(bodyRows()).toHaveLength(2);
    expect(screen.getByText("Lettuce")).toBeInTheDocument();
    expect(screen.queryByText("Potatoes")).not.toBeInTheDocument();
    expect(screen.queryByText("table.past_week_readonly")).not.toBeInTheDocument();
    expect(screen.getByText("explainers.waste")).toBeInTheDocument();
  });

  // The module loaded in week 41 of 2026; the page reads the date when it opens.
  it("opens on today's week and day when it opens after New Year", async () => {
    vi.setSystemTime(new Date(2027, 0, 7, 12, 0));
    renderPage();

    await waitFor(() => expect(api.list).toHaveBeenCalled());
    expect(lastListRequest()).toEqual({ year: 2027, delivery_week: 1, day_number: 3, is_past: false });
  });

  it("loads no waste until the storages are known", async () => {
    const storages = pending<Storage[]>();
    api.storages.mockImplementation(() => storages.promise);
    renderPage();

    await waitFor(() => expect(api.storages).toHaveBeenCalled());
    expect(api.list).not.toHaveBeenCalled();
    expect(bodyRows()).toHaveLength(0);

    storages.answer([...farm.storages]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledTimes(1);
  });

  it("shows a spinner over the table while the day's waste loads", async () => {
    const rows = pending<WasteRow[]>();
    api.list.mockImplementation(() => rows.promise);
    renderPage();

    await waitFor(() => expect(tableIsBusy()).toBe(true));
    expect(bodyRows()).toHaveLength(0);

    rows.answer([CARROTS_WASTE]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(tableIsBusy()).toBe(false));
  });
});

// ── Waste rows ──────────────────────────────────────────────────────────────

describe("DocumentationWaste waste rows", () => {
  it("shows each waste's unit, amount and note", async () => {
    renderPage();
    await screen.findByText("Carrots");

    expect(headerTexts()).toEqual(expect.arrayContaining([ARTICLE, UNIT, AMOUNT, NOTE]));
    expect(headerTexts()).not.toContain(SIZE);
    expect(cellOf("Carrots", UNIT)).toHaveTextContent("commissioning.units.kg");
    expect(cellOf("Carrots", AMOUNT)).toHaveTextContent(amountText(4));
    expect(cellOf("Carrots", NOTE)).toHaveTextContent("Rotten at the bottom");
    expect(cellOf("Lettuce", UNIT)).toHaveTextContent("commissioning.units.pcs");
    expect(cellOf("Lettuce", AMOUNT)).toHaveTextContent(amountText(12));
    expect(cellOf("Lettuce", NOTE).textContent).toBe("");
  });

  it.each([
    ["de-DE", /^1\.250(?:,0+)?$/],
    ["en-US", /^1,250(?:\.0+)?$/],
  ])("writes the amounts in the farm's number format (%s)", async (locale, shown) => {
    tenantSettings.values = { number_locale: locale };
    farm.wastes = [waste("waste-potatoes", POTATOES, COLD_STORE, TUESDAY, { amount: "1250.00" })];
    renderPage();
    await screen.findByText("Potatoes");

    expect(cellOf("Potatoes", AMOUNT)).toHaveTextContent(shown);
  });

  it("adds the size column when the farm shows sizes, and dates the day in the farm's format", async () => {
    tenantSettings.values = { show_size_column: true, date_format: "MM/DD/YYYY" };
    renderPage();
    await screen.findByText("Lettuce");

    expect(cellOf("Lettuce", SIZE)).toHaveTextContent("commissioning.large");
    expect(cellOf("Carrots", SIZE)).toHaveTextContent("commissioning.medium");
    expect(selectedIn(DAY)).toBe("Tuesday, 10/06/2026");
  });

  it("says there is no waste in a storage nothing was thrown away from", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await chooseIn(STORAGE, "Farm shop");

    await waitFor(() => expect(bodyRows()).toHaveLength(0));
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
  });
});

// ── Storage, week and day ───────────────────────────────────────────────────

describe("DocumentationWaste choosing the storage, week and day", () => {
  it("shows another storage's waste of the same day without loading the day again", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const loads = api.list.mock.calls.length;

    await chooseIn(STORAGE, "Root cellar");

    expect(await screen.findByText("Potatoes")).toBeInTheDocument();
    expect(cellOf("Potatoes", AMOUNT)).toHaveTextContent(amountText(25));
    expect(cellOf("Potatoes", NOTE)).toHaveTextContent("Sprouted");
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(1);
    expect(api.list).toHaveBeenCalledTimes(loads);
  });

  it("lists another day's waste when the day changes", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await chooseIn(DAY, "Wednesday, 07.10.2026");

    expect(await screen.findByText("Radishes")).toBeInTheDocument();
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
    expect(selectedIn(STORAGE)).toBe("Cold store");
    expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 41, day_number: 2, is_past: false });
  });

  it("offers every day of the selected week", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(screen.getByRole("combobox", { name: DAY }));

    const options = Array.from(
      openDropdown().querySelectorAll(".ant-select-item-option-content"),
      (option) => option.textContent,
    );
    expect(options).toEqual([
      "Monday, 05.10.2026", "Tuesday, 06.10.2026", "Wednesday, 07.10.2026", "Thursday, 08.10.2026",
      "Friday, 09.10.2026", "Saturday, 10.10.2026", "Sunday, 11.10.2026",
    ]);
  });

  it("loads the same weekday of the next week from the week arrow", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.next"));

    await waitFor(() => expect(selectedIn(DAY)).toBe("Tuesday, 13.10.2026"));
    expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 42, day_number: 1, is_past: false });
    await waitFor(() => expect(bodyRows()).toHaveLength(0));
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("shows a week more than a week back read-only", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await waitFor(() => expect(lastListRequest()).toMatchObject({ delivery_week: 40, is_past: false }));
    expect(screen.queryByText("table.past_week_readonly")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();

    await userEvent.click(arrow(WEEK, "common.previous"));

    expect(await screen.findByText("Leeks")).toBeInTheDocument();
    expect(lastListRequest()).toEqual({ year: 2026, delivery_week: 39, day_number: 1, is_past: true });
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EDIT_OR_DELETE })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: ADD_ARTICLE })).toBeDisabled();

    await userEvent.click(within(rowOf("Leeks")).getByText(amountText(7)));
    await userEvent.keyboard("+");

    expect(screen.queryByRole("textbox", { name: AMOUNT })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(1);
  });
});

// ── Recording ───────────────────────────────────────────────────────────────

describe("DocumentationWaste recording waste", () => {
  it("records a new waste with the article's unit, a medium size, the amount and a note", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Beetroot");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.kg"));
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "3");
    await userEvent.type(screen.getByRole("textbox", { name: NOTE }), "Frost damage");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        ...TUESDAY_IN_COLD_STORE,
        share_article: BEETROOT.id, unit: "KG", size: "M", amount: "3", note: "Frost damage",
      }),
    );
    await editingDone();
    expect(cellOf("Beetroot", AMOUNT)).toHaveTextContent(amountText(3));
    expect(cellOf("Beetroot", NOTE)).toHaveTextContent("Frost damage");
    expect(bodyRows()).toHaveLength(3);
  });

  it("records the size picked for a new waste when the farm shows sizes", async () => {
    tenantSettings.values = { show_size_column: true };
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    expect(selectedIn(SIZE)).toBe("commissioning.medium");
    await chooseArticle("Beetroot");
    await chooseIn(SIZE, "commissioning.large");
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "2");
    await save();

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        expect.objectContaining({ share_article: BEETROOT.id, unit: "KG", size: "L", amount: "2" }),
      ),
    );
    await editingDone();
    expect(cellOf("Beetroot", SIZE)).toHaveTextContent("commissioning.large");
  });

  it("starts a new entry from the + key", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.keyboard("+");

    expect(await screen.findByRole("combobox", { name: ARTICLE })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);
  });

  it("asks for the article, unit and amount before saving", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await save();

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeInTheDocument();
    for (const title of [ARTICLE, UNIT, AMOUNT]) {
      expect(within(cellIn(editingRow(), title)).getByText("table.required")).toBeInTheDocument();
    }
    expect(within(cellIn(editingRow(), NOTE)).queryByText("table.required")).not.toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("takes no minus sign in the amount", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "-5");

    expect(screen.getByRole("textbox", { name: AMOUNT })).toHaveValue("5");
  });

  it("keeps the row open with the server's reason when a save is refused", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reason = "Ensure that there are no more than 8 digits before the decimal point.";
    api.create.mockRejectedValueOnce(refusal(reason, { amount: [reason] }));
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Beetroot");
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "123456789");
    await save();

    expect(await screen.findByText(`${AMOUNT}: ${reason} — table.save_failed_hint`)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: AMOUNT })).toHaveValue("123456789");
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(bodyRows()).toHaveLength(3);

    await userEvent.clear(screen.getByRole("textbox", { name: AMOUNT }));
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "9");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
    await editingDone();
    expect(cellOf("Beetroot", AMOUNT)).toHaveTextContent(amountText(9));
    expect(screen.queryByText("table.save_failed_title")).not.toBeInTheDocument();
  });

  it("refuses an article, unit and size already thrown away that day from the storage", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Carrots");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.kg"));
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "2");
    await save();

    const unique = "validation.unique.share_article_unit_size_must_be_unique";
    expect(await screen.findByText(`${unique} — table.save_failed_hint`)).toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
  });

  it("records an article thrown away the same day from another storage", async () => {
    renderPage();
    await screen.findByText("Carrots");

    // The potatoes of that day went to waste from the root cellar.
    await startNewRow();
    await chooseArticle("Potatoes");
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "5");
    await save();

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        expect.objectContaining({ ...TUESDAY_IN_COLD_STORE, share_article: POTATOES.id, amount: "5" }),
      ),
    );
    await editingDone();
  });

  it("shows the server's refusal of the whole row without a field name before it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const reason = "The fields year, delivery_week, day_number, share_article, unit, size, storage must make a unique set.";
    api.create.mockRejectedValueOnce(refusal(reason, { non_field_errors: [reason] }));
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Beetroot");
    await userEvent.type(screen.getByRole("textbox", { name: AMOUNT }), "1");
    await save();

    expect(await screen.findByText(`${reason} — table.save_failed_hint`)).toBeInTheDocument();
    expect(screen.queryByText(/non_field_errors/)).not.toBeInTheDocument();
  });

  it("offers an article created from the page in the article picker", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const loads = api.shareArticles.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: ADD_ARTICLE }));
    const dialog = await screen.findByRole("dialog", { name: "commissioning.add_share_article" });
    await userEvent.click(within(dialog).getByRole("button", { name: "create share article" }));

    expect(dialog).not.toBeInTheDocument();
    await waitFor(() => expect(api.shareArticles.mock.calls.length).toBeGreaterThan(loads));
    await startNewRow();
    await chooseArticle("Chard");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.bunch"));
  });
});

// ── Correcting and deleting ─────────────────────────────────────────────────

describe("DocumentationWaste correcting a waste", () => {
  it("saves a corrected amount and note while the article, unit and size stay as recorded", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await userEvent.click(within(rowOf("Carrots")).getByText(amountText(4)));

    const amount = screen.getByRole("textbox", { name: AMOUNT });
    expect((amount as HTMLInputElement).value).toMatch(amountText(4));
    const row = editingRow();
    expect(within(row).getByText("Carrots")).toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: ARTICLE })).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox", { name: UNIT })).not.toBeInTheDocument();
    await userEvent.clear(amount);
    await userEvent.type(amount, "6");
    const note = screen.getByRole("textbox", { name: NOTE });
    await userEvent.clear(note);
    await userEvent.type(note, "Rotten, sorted out");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      CARROTS_WASTE.id,
      expect.objectContaining({
        ...TUESDAY_IN_COLD_STORE,
        share_article: CARROTS.id, unit: "KG", size: "M", amount: "6", note: "Rotten, sorted out",
      }),
    );
    await editingDone();
    expect(cellOf("Carrots", AMOUNT)).toHaveTextContent(amountText(6));
    expect(cellOf("Carrots", NOTE)).toHaveTextContent("Rotten, sorted out");
  });
});

describe("DocumentationWaste deleting a waste", () => {
  const deleteLettuce = async () => {
    await userEvent.click(within(rowOf("Lettuce")).getByRole("button", { name: "table.delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));
  };

  it("deletes a waste after confirmation and reloads the day", async () => {
    renderPage();
    await screen.findByText("Carrots");
    const loads = api.list.mock.calls.length;

    await deleteLettuce();

    await waitFor(() => expect(screen.queryByText("Lettuce")).not.toBeInTheDocument());
    expect(api.destroy).toHaveBeenCalledWith(LETTUCE_WASTE.id);
    await waitFor(() => expect(api.list.mock.calls.length).toBeGreaterThan(loads));
    expect(bodyRows()).toHaveLength(1);
  });

  it("keeps the waste and says why when the server refuses to delete it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.destroy.mockRejectedValueOnce(refusal("The waste is part of a stock count."));
    renderPage();
    await screen.findByText("Carrots");

    await deleteLettuce();

    expect(await screen.findByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("The waste is part of a stock count.")).toBeInTheDocument();
    expect(screen.getByText("Lettuce")).toBeInTheDocument();
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("DocumentationWaste roles", () => {
  it("shows the waste without a way to add, correct or delete it to a user without a staff role", async () => {
    auth.roles = ["member"];
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.queryByRole("button", { name: ADD_ROW })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EDIT_OR_DELETE })).not.toBeInTheDocument();
    await userEvent.click(within(rowOf("Carrots")).getByText(amountText(4)));
    await userEvent.keyboard("+");

    expect(screen.queryByRole("textbox", { name: AMOUNT })).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
  });

  it.each(["staff", "office", "management", "admin"])("lets a %s login record and correct waste", async (role) => {
    auth.roles = [role];
    renderPage();
    await screen.findByText("Carrots");

    expect(screen.getByRole("button", { name: ADD_ROW })).toBeInTheDocument();
    await userEvent.click(within(rowOf("Lettuce")).getByText(amountText(12)));

    expect((screen.getByRole("textbox", { name: AMOUNT }) as HTMLInputElement).value).toMatch(amountText(12));
  });
});

// ── Phone ───────────────────────────────────────────────────────────────────

describe("DocumentationWaste on a phone", () => {
  beforeEach(() => {
    viewport.mobile = true;
  });

  it("shows each waste as a card with its unit, amount and note instead of the table", async () => {
    renderPage();
    const carrots = await findCard("Carrots");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(selectedIn(DAY)).toBe("Tu, 06.10.");
    const details = detailsOf(carrots);
    expect(details[UNIT]).toBe("commissioning.units.kg");
    expect(details[AMOUNT]).toMatch(amountText(4));
    expect(details[NOTE]).toBe("Rotten at the bottom");
    // A waste without a note leaves the note off its card.
    expect(Object.keys(detailsOf(cardOf("Lettuce")))).toEqual([UNIT, AMOUNT]);
    expect(document.querySelectorAll(".mobile-card-item")).toHaveLength(2);
    expect(within(carrots).getByRole("button", { name: "table.edit" })).toBeEnabled();
    expect(within(carrots).getByRole("button", { name: "table.delete" })).toBeInTheDocument();
  });

  it("corrects a waste from its card", async () => {
    renderPage();
    await userEvent.click(within(await findCard("Carrots")).getByText("Carrots"));

    const dialog = await screen.findByRole("dialog", { name: "table.edit_record" });
    const amount = within(dialog).getByRole("textbox", { name: AMOUNT });
    expect((amount as HTMLInputElement).value).toMatch(amountText(4));
    expect(within(dialog).getByRole("combobox", { name: ARTICLE })).toBeDisabled();
    expect(within(dialog).getByRole("combobox", { name: UNIT })).toBeDisabled();
    await userEvent.clear(amount);
    await userEvent.type(amount, "5");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith(
        CARROTS_WASTE.id,
        expect.objectContaining({
          ...TUESDAY_IN_COLD_STORE,
          share_article: CARROTS.id, unit: "KG", size: "M", amount: "5", note: "Rotten at the bottom",
        }),
      ),
    );
    await waitFor(() => expect(detailsOf(cardOf("Carrots"))[AMOUNT]).toMatch(amountText(5)));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "table.edit_record" })).not.toBeInTheDocument());
  });

  it("records a new waste from the add button", async () => {
    renderPage();
    await findCard("Carrots");

    await userEvent.click(screen.getByRole("button", { name: /table\.add_record/ }));
    const dialog = await screen.findByRole("dialog", { name: "table.add_record" });
    await choose(within(dialog).getByRole("combobox", { name: ARTICLE }), "Beetroot");
    await waitFor(() =>
      expect(selectionOf(within(dialog).getByRole("combobox", { name: UNIT }))).toBe("commissioning.units.kg"),
    );
    await userEvent.type(within(dialog).getByRole("textbox", { name: AMOUNT }), "2");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        expect.objectContaining({
          ...TUESDAY_IN_COLD_STORE,
          share_article: BEETROOT.id, unit: "KG", size: "M", amount: "2",
        }),
      ),
    );
    expect(detailsOf(await findCard("Beetroot"))[AMOUNT]).toMatch(amountText(2));
  });

  it("offers no card a way to be changed in a week more than a week back", async () => {
    renderPage();
    await findCard("Carrots");

    await userEvent.click(arrow(WEEK, "common.previous"));
    await userEvent.click(arrow(WEEK, "common.previous"));
    const leeks = await findCard("Leeks");

    expect(screen.queryByRole("button", { name: /table\.add_record/ })).not.toBeInTheDocument();
    expect(within(leeks).getByRole("button", { name: "table.edit" })).toBeDisabled();
    expect(within(leeks).queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    await userEvent.click(within(leeks).getByText("Leeks"));
    expect(screen.queryByRole("dialog", { name: "table.edit_record" })).not.toBeInTheDocument();
  });
});

// ── Decimals ────────────────────────────────────────────────────────────────

describe("DocumentationWaste amounts with decimals", () => {
  // 2.50 kg of carrots and 0.40 kg of potatoes, as the two-decimal field returns them.
  beforeEach(() => {
    farm.wastes = [
      { ...CARROTS_WASTE, amount: "2.50" },
      waste("waste-potatoes", POTATOES, COLD_STORE, TUESDAY, { amount: "0.40" }),
    ];
  });
  const amountInput = () => screen.getByRole("textbox", { name: AMOUNT });
  const carrotsSavedWith = (fields: Payload) =>
    waitFor(() => expect(api.update).toHaveBeenCalledWith(CARROTS_WASTE.id, expect.objectContaining(fields)));

  it.each([
    ["de-DE", /^2,50$/, /^0,40$/],
    ["en-US", /^2\.50$/, /^0\.40$/],
  ])("shows them in the farm's number format (%s)", async (locale, carrots, potatoes) => {
    tenantSettings.values = { number_locale: locale };
    renderPage();
    await screen.findByText("Carrots");

    expect(cellOf("Carrots", AMOUNT)).toHaveTextContent(carrots);
    expect(cellOf("Potatoes", AMOUNT)).toHaveTextContent(potatoes);
  });

  it("takes a decimal comma and at most two decimals for a new waste, and saves the amount with a point", async () => {
    renderPage();
    await screen.findByText("Carrots");

    await startNewRow();
    await chooseArticle("Beetroot");
    await waitFor(() => expect(selectedIn(UNIT)).toBe("commissioning.units.kg"));
    await userEvent.type(amountInput(), "2,555");
    expect(amountInput()).toHaveValue("2,55");
    await userEvent.keyboard("{Backspace}");
    expect(amountInput()).toHaveValue("2,5");
    await save();

    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith(
        expect.objectContaining({ ...TUESDAY_IN_COLD_STORE, share_article: BEETROOT.id, amount: "2.5" }),
      ),
    );
    await editingDone();
    expect(cellOf("Beetroot", AMOUNT)).toHaveTextContent(/^2,50$/);
  });

  it("keeps a waste's decimals when only its note is corrected", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Rotten at the bottom"));

    expect(amountInput()).toHaveValue("2,50");
    await userEvent.clear(screen.getByRole("textbox", { name: NOTE }));
    await userEvent.type(screen.getByRole("textbox", { name: NOTE }), "Sorted out");
    await save();

    await carrotsSavedWith({ amount: "2.50", note: "Sorted out" });
    await editingDone();
    expect(cellOf("Carrots", AMOUNT)).toHaveTextContent(/^2,50$/);
  });

  it("keeps a waste's decimals when a click into another row saves it", async () => {
    renderPage();
    await userEvent.click(await screen.findByText("Rotten at the bottom"));
    await userEvent.click(cellOf("Potatoes", AMOUNT));

    await carrotsSavedWith({ amount: "2.50", note: "Rotten at the bottom" });
    await waitFor(() => expect(amountInput()).toHaveValue("0,40"));
    expect(cellOf("Carrots", AMOUNT)).toHaveTextContent(/^2,50$/);
  });

  it("shows them on a phone card and keeps them when the card's dialog corrects only the note", async () => {
    viewport.mobile = true;
    renderPage();
    const carrots = await findCard("Carrots");

    expect(detailsOf(carrots)[AMOUNT]).toBe("2,50");
    expect(detailsOf(cardOf("Potatoes"))[AMOUNT]).toBe("0,40");
    await userEvent.click(within(carrots).getByText("Carrots"));
    const dialog = await screen.findByRole("dialog", { name: "table.edit_record" });
    expect(within(dialog).getByRole("textbox", { name: AMOUNT })).toHaveValue("2,50");
    const note = within(dialog).getByRole("textbox", { name: NOTE });
    await userEvent.clear(note);
    await userEvent.type(note, "Sorted out");
    await userEvent.click(within(dialog).getByRole("button", { name: "table.save" }));

    await carrotsSavedWith({ amount: "2.50", note: "Sorted out" });
  });
});

// ── Render loop ─────────────────────────────────────────────────────────────

describe("DocumentationWaste render loop", () => {
  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Carrots");
    await flushMicrotasks();

    // About 12 commits in a healthy run; a setState-in-render loop makes
    // thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(150);
  });
});
