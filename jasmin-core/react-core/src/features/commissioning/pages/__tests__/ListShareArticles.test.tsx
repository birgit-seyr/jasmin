/**
 * ListShareArticles: the farm's share articles — vegetables, fruit and other goods — with their units,
 * share options and packing, harvest, reseller and purchase defaults, edited inline. Rendered through the
 * real useCrudListPage, EditableTable, column hooks, organic gate and CSV import dialog. The generated
 * commissioning client is the mocking boundary: its list hooks are real TanStack queries around spies that
 * answer from an in-memory farm, whose mutations echo the saved article the way the backend does. The price
 * editor and the three exports are other screens and stand in as stubs that show what they were opened
 * for; so does the import dialog's template and upload button, which talks to the import endpoint itself.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle } from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

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

// The tenant record and settings, per test; an unset setting falls back to
// the caller's default.
const tenantState = vi.hoisted(() => ({
  record: { organic_control_number: "" } as Record<string, unknown>,
  settings: {} as Record<string, unknown>,
}));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: tenantState.record,
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

const api = vi.hoisted(() => ({
  listArticles: vi.fn(), createArticle: vi.fn(), updateArticle: vi.fn(), destroyArticle: vi.fn(),
  listShareOptions: vi.fn(), activeShareOptions: vi.fn(), listCrates: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (path: string, params?: unknown) =>
    [`/api/commissioning/${path}/`, ...(params ? [params] : [])];
  const queryHook = (path: string, request: (params?: unknown) => unknown) =>
    function useGeneratedQuery(params?: unknown) {
      return useQuery({ queryKey: queryKey(path, params), queryFn: async () => request(params) });
    };
  return {
    useCommissioningShareArticlesList: queryHook("share_articles", api.listArticles),
    getCommissioningShareArticlesListQueryKey: (params?: unknown) => queryKey("share_articles", params),
    commissioningShareArticlesCreate: (article: unknown) => api.createArticle(article),
    commissioningShareArticlesPartialUpdate: (id: string, article: unknown) =>
      api.updateArticle(id, article),
    commissioningShareArticlesDestroy: (id: string) => api.destroyArticle(id),
    useCommissioningShareOptionsList: queryHook("share_options", api.listShareOptions),
    useCommissioningShareOptionsActiveRetrieve: queryHook("share_options/active", api.activeShareOptions),
    useCommissioningCratesList: queryHook("crates", api.listCrates),
  };
});

type Row = Record<string, unknown>;
type DialogStubProps = { open: boolean; onClose: () => void };
type ExportCsvStubProps = DialogStubProps & { columns: { dataIndex?: string }[]; data: Row[]; filename?: string };
type PriceModalStubProps = {
  visible: boolean; onClose: () => void; share_article: string | null; share_article_name: string;
};
type TemplateStubProps = {
  columns: { dataIndex?: string | number }[]; filename: string; modelName?: string;
  onUploadSuccess?: () => void; onImported?: () => void;
};

// The props the stubbed list export and import template got on their last render.
const stubs = vi.hoisted(() => ({
  exportCsv: null as ExportCsvStubProps | null, template: null as TemplateStubProps | null,
}));

vi.mock("@features/commissioning/modals", () => {
  const stubDialog = (name: string, close: string) =>
    function DialogStub({ open, onClose }: DialogStubProps) {
      return open ? (
        <div role="dialog" aria-label={name}>
          <button type="button" onClick={onClose}>{close}</button>
        </div>
      ) : null;
    };
  const ListExport = stubDialog("Article list export", "Close list export");
  return {
    ExportCsv: (props: ExportCsvStubProps) => {
      stubs.exportCsv = props;
      return <ListExport open={props.open} onClose={props.onClose} />;
    },
    ExportCsvPricesShareArticle: stubDialog("Price export", "Close price export"),
    ExportCsvAllArticles: stubDialog("Combined export", "Close combined export"),
    ShareArticlePriceModal: ({ visible, onClose, share_article, share_article_name }: PriceModalStubProps) =>
      visible ? (
        <div role="dialog" aria-label="Prices">
          <p>{`Prices of ${share_article_name} (${share_article})`}</p>
          <button type="button" onClick={onClose}>Close prices</button>
        </div>
      ) : null,
  };
});

// The real import button and dialog, without the rest of the shared modals.
vi.mock("@shared/modals", async () => ({
  CsvImportButton: (await import("@shared/modals/CsvImportModal")).CsvImportButton,
}));

// Its upload stands for a CSV the import endpoint took in full.
vi.mock("@shared/ui/DownloadCsvTemplateButton", () => ({
  default: (props: TemplateStubProps) => {
    stubs.template = props;
    const upload = () => [props.onUploadSuccess, props.onImported].forEach((callback) => callback?.());
    return <button type="button" onClick={upload}>Upload the filled-in template</button>;
  },
}));

import ListShareArticles from "../ListShareArticles";
import {
  ACTIVE_SHARE_OPTIONS, APPLES, article, asListed, BLANK_ARTICLE, CARROTS, CRATES, EURO_CRATE, FOREST_HONEY,
  HARVEST_BIN, httpError, LEMONS, LEMONS_NAME, optionFields, PURCHASED_SUFFIX, RADISHES, SHARE_OPTIONS,
} from "./listShareArticles.fixtures";

// ── Fixtures ────────────────────────────────────────────────────────────────

// What the server currently holds; the list requests answer from it.
let serverArticles: ShareArticle[] = [];

beforeEach(() => {
  auth.roles = ["office"];
  tenantState.record.organic_control_number = "";
  tenantState.settings = {};
  Object.assign(stubs, { exportCsv: null, template: null });
  serverArticles = [APPLES, CARROTS, FOREST_HONEY, LEMONS, RADISHES];
  let createdCount = 0;
  api.listArticles.mockReset().mockImplementation(async () => [...serverArticles]);
  api.listShareOptions.mockReset().mockImplementation(async () => SHARE_OPTIONS);
  api.activeShareOptions.mockReset().mockImplementation(async () => ACTIVE_SHARE_OPTIONS);
  api.listCrates.mockReset().mockImplementation(async () => CRATES);
  api.createArticle.mockReset().mockImplementation(async (payload: Row) => {
    createdCount += 1;
    const { key: _key, share_option_list: options = [], ...fields } = payload;
    const id = `article-new-${createdCount}`;
    const saved = asListed({ ...BLANK_ARTICLE, ...fields, ...optionFields(options as string[]), id });
    serverArticles = [...serverArticles, saved];
    return saved;
  });
  api.updateArticle.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = serverArticles.find((each) => each.id === id);
    if (!current) throw httpError(404, { code: "share_article.not_found", message: "Not found." });
    const { key: _key, share_option_list: options, ...fields } = payload;
    const saved = asListed({ ...current, ...fields, ...(options ? optionFields(options as string[]) : {}), id });
    serverArticles = serverArticles.map((each) => (each.id === id ? saved : each));
    return saved;
  });
  api.destroyArticle.mockReset().mockImplementation(async (id: string) => {
    serverArticles = serverArticles.filter((each) => each.id !== id);
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const defaultOptions = { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } };
  const queryClient = new QueryClient({ defaultOptions });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListShareArticles />)}</QueryClientProvider>);
  return { user, profiler };
}

const NAME = "commissioning.name";
const UNIT = "commissioning.default_movement_unit";
const PURCHASED = "commissioning.is_purchased";
const DESCRIPTION = "commissioning.description";
const ORGANIC = "commissioning.organic_status";
const BULK_SURCHARGE = "commissioning.percentage_added_to_bulk_packing_list";
const VEG_SHARE = "commissioning.share_option.HARVEST_SHARE";
const HONEY_SHARE = "commissioning.share_option.HONEY_SHARE";
const KG = "commissioning.units.kg";
const PIECES = "commissioning.units.pcs";
const DUPLICATE = "validation.unique.list_share_articles — table.save_failed_hint";
const EXPORTS = /commissioning\.(export_prices|share_article_list_csv_export|export_all_articles_combined)/;

/** Renders the page and waits until the articles and the share-option filter are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Carrots");
  await screen.findByRole("radio", { name: HONEY_SHARE });
  return rendered;
}

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const columnTitles = () =>
  Array.from(document.querySelectorAll(".ant-table-thead > tr > th")).map((th) => th.textContent?.trim() ?? "");

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}
const rowOf = (text: string) => rowAround(screen.getByText(text), `shows ${text}`);
/** The row being edited inline — the one offering a save button. */
const editingRow = () => rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const index = columnTitles().indexOf(columnTitle);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

/** The text of each of `titles`' cells in `row`, by column title. */
const cellTexts = (row: HTMLElement, titles: string[]) =>
  Object.fromEntries(titles.map((title) => [title, cellOf(row, title).textContent]));

const shownNames = () => bodyRows().map((row) => cellOf(row, NAME).textContent);

/** The read-only checkbox a row shows for one of its flags. */
const flag = (row: HTMLElement, columnTitle: string) =>
  within(cellOf(row, columnTitle)).getByRole("checkbox");

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const addButton = () => screen.queryByRole("button", { name: /table\.add_record/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");

type User = ReturnType<typeof userEvent.setup>;

/** Picks a share-option filter; AntD hides the radio input behind its button. */
const pickFilter = (user: User, name: string) =>
  user.click(screen.getByRole("radio", { name }).closest("label")!);

const editCheckbox = (name: string) => within(editingRow()).queryByRole("checkbox", { name });
const field = (name: string) => within(editingRow()).getByRole("combobox", { name });
const editRow = (user: User, name: string) => user.click(rowButton(name, "table.edit"));
const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, name: string) {
  await user.click(rowButton(name, "table.delete"));
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await user.clear(input);
  await user.type(input, text);
}

function openPopup(selector: string): HTMLElement {
  const popups = Array.from(document.querySelectorAll<HTMLElement>(selector));
  const popup = popups.filter((each) => !/-hidden\b/.test(each.className)).pop();
  if (!popup) throw new Error(`Nothing open matches ${selector}`);
  return popup;
}

async function choose(user: User, select: HTMLElement, option: string) {
  await user.click(select);
  await user.click(within(openPopup(".ant-select-dropdown")).getByText(option));
}

async function optionsOf(user: User, select: HTMLElement): Promise<string[]> {
  await user.click(select);
  const options = openPopup(".ant-select-dropdown").querySelectorAll(".ant-select-item-option-content");
  return Array.from(options).map((option) => option.textContent ?? "");
}

/** The label a select shows for its current value. */
const selectedIn = (select: HTMLElement) =>
  select.closest(".ant-select")?.querySelector(".ant-select-selection-item")?.textContent ?? "";

/** Starts a new article with a name and the unit it moves in. */
async function startNewArticle(user: User, name: string, unit: string) {
  await user.click(addButton()!);
  await typeInto(user, NAME, name);
  await choose(user, field(UNIT), unit);
}

const created = () => api.createArticle.mock.lastCall?.[0] as Row | undefined;
const createdOnce = () => waitFor(() => expect(api.createArticle).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updateArticle).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("ListShareArticles loading and layout", () => {
  it("loads the articles once, as the data list with share-option flags and crate names", async () => {
    renderPage();

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(1);
    expect(api.listArticles).toHaveBeenCalledWith({ is_data_list: true });
    expect(api.listCrates).toHaveBeenCalledWith({ is_active: true });
  });

  it("shows a spinner over the table while the articles load", async () => {
    let deliver: (rows: ShareArticle[]) => void = () => {};
    api.listArticles.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([CARROTS]);

    expect(await screen.findByText("Carrots")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(screen.getByRole("heading", { level: 1, name: "commissioning.share_articles" })).toBeVisible();
    expect(screen.getByText("commissioning.share_articles_description")).toBeInTheDocument();
    // The price buttons' column has no title; the titles after it, all under "commissioning.":
    const titlesAfterPrices = `${UNIT} ${PURCHASED} ${DESCRIPTION} ${VEG_SHARE} ${HONEY_SHARE} for_resellers
      for_markets kg_per_piece_S kg_per_piece_M kg_per_piece_L pieces_per_kg_S pieces_per_kg_M pieces_per_kg_L
      packing_station percentage_added_to_commissioning_list_packing default_kg_per_pu_harvest
      default_pieces_per_pu_harvest default_bunches_per_pu_harvest default_crate_harvest default_commissioning_unit
      default_kg_per_pu_reseller default_pieces_per_pu_reseller default_bunches_per_pu_reseller
      default_crate_reseller default_kg_per_pu_purchase default_pieces_per_pu_purchase default_bunches_per_pu_purchase`
      .split(/\s+/)
      .map((title) => (title.startsWith("commissioning.") ? title : `commissioning.${title}`));
    expect(columnTitles()).toEqual([
      "table.actions", "commissioning.is_active", "commissioning.article_number", NAME, "", ...titlesAfterPrices,
    ]);
    expect(screen.getByText("explainers.list_share_articles")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when the farm has no articles", async () => {
    serverArticles = [];
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the articles fail to load", async () => {
    api.listArticles.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(screen.getByRole("heading", { level: 1, name: "commissioning.share_articles" })).toBeVisible();
    expect(addButton()).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("ListShareArticles rows", () => {
  it("shows each article's values, numbers in the tenant's format and crates by name", async () => {
    await renderLoaded();
    const carrots = rowOf("Carrots");
    await within(carrots).findByText("Harvest bin");

    expect(
      cellTexts(carrots, [
        "commissioning.article_number", UNIT, DESCRIPTION, "commissioning.kg_per_piece_S",
        "commissioning.kg_per_piece_L", "commissioning.pieces_per_kg_S", "commissioning.pieces_per_kg_M",
        "commissioning.packing_station", "commissioning.percentage_added_to_commissioning_list_packing",
        "commissioning.default_kg_per_pu_harvest", "commissioning.default_crate_harvest",
        "commissioning.default_commissioning_unit", "commissioning.default_kg_per_pu_reseller",
        "commissioning.default_crate_reseller",
      ]),
    ).toEqual({
      "commissioning.article_number": "A-100", [UNIT]: KG, [DESCRIPTION]: "Washed, with greens",
      "commissioning.kg_per_piece_S": "0,080", "commissioning.kg_per_piece_L": "0,250",
      "commissioning.pieces_per_kg_S": "", "commissioning.pieces_per_kg_M": "7", "commissioning.packing_station": "2",
      "commissioning.percentage_added_to_commissioning_list_packing": "5 %",
      "commissioning.default_kg_per_pu_harvest": "12,500", "commissioning.default_crate_harvest": "E2",
      "commissioning.default_commissioning_unit": KG, "commissioning.default_kg_per_pu_reseller": "10,000",
      "commissioning.default_crate_reseller": "Harvest bin",
    });
    expect(cellOf(rowOf("Forest honey"), UNIT)).toHaveTextContent(PIECES);
  });

  it("writes the numbers the way the tenant's number locale does", async () => {
    tenantState.settings = { number_locale: "en-US" };
    await renderLoaded();

    const carrots = rowOf("Carrots");
    expect(cellOf(carrots, "commissioning.kg_per_piece_L")).toHaveTextContent("0.250");
    expect(cellOf(carrots, "commissioning.default_kg_per_pu_harvest")).toHaveTextContent("12.500");
  });

  it("ticks the flags and share options each article has", async () => {
    await renderLoaded();

    const carrots = rowOf("Carrots");
    expect(flag(carrots, "commissioning.is_active")).toBeChecked();
    expect(flag(carrots, PURCHASED)).not.toBeChecked();
    expect(flag(carrots, VEG_SHARE)).toBeChecked();
    expect(flag(carrots, HONEY_SHARE)).not.toBeChecked();
    expect(flag(carrots, "commissioning.for_resellers")).toBeChecked();
    expect(flag(carrots, "commissioning.for_markets")).toBeChecked();
    const honey = rowOf("Forest honey");
    expect(flag(honey, VEG_SHARE)).not.toBeChecked();
    expect(flag(honey, HONEY_SHARE)).toBeChecked();
    expect(flag(honey, "commissioning.for_markets")).not.toBeChecked();
    expect(flag(rowOf(LEMONS_NAME), PURCHASED)).toBeChecked();
  });

  it("leaves the harvest values of a bought-in article and the purchase values of a grown one empty", async () => {
    await renderLoaded();

    const harvest = ["commissioning.default_kg_per_pu_harvest", "commissioning.default_crate_harvest"];
    const purchase = ["commissioning.default_kg_per_pu_purchase", "commissioning.default_pieces_per_pu_purchase"];
    expect(cellTexts(rowOf(LEMONS_NAME), [...harvest, ...purchase])).toEqual({
      "commissioning.default_kg_per_pu_harvest": "", "commissioning.default_crate_harvest": "",
      "commissioning.default_kg_per_pu_purchase": "15,000", "commissioning.default_pieces_per_pu_purchase": "80",
    });
    expect(cellTexts(rowOf("Carrots"), purchase)).toEqual(Object.fromEntries(purchase.map((title) => [title, ""])));
  });
});

describe("ListShareArticles filters", () => {
  it("hides inactive articles until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(screen.queryByText("Radishes")).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(4);

    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(flag(rowOf("Radishes"), "commissioning.is_active")).not.toBeChecked();
    expect(bodyRows()).toHaveLength(5);
  });

  it("offers a filter for each share option the farm runs and narrows the list and columns to it", async () => {
    const { user } = await renderLoaded();

    const filters = screen.getAllByRole("radio").map((radio) => radio.closest("label")?.textContent);
    expect(filters).toEqual(["common.all", VEG_SHARE, HONEY_SHARE]);
    expect(screen.getByRole("radio", { name: "common.all" })).toBeChecked();

    await pickFilter(user, HONEY_SHARE);

    expect(shownNames()).toEqual(["Forest honey"]);
    expect(columnTitles()).toContain(HONEY_SHARE);
    expect(columnTitles()).not.toContain(VEG_SHARE);

    await pickFilter(user, VEG_SHARE);

    expect(shownNames()).toEqual(["Apples", "Carrots", LEMONS_NAME]);
    expect(columnTitles()).not.toContain(HONEY_SHARE);

    await pickFilter(user, "common.all");

    expect(bodyRows()).toHaveLength(4);
    expect(columnTitles()).toEqual(expect.arrayContaining([VEG_SHARE, HONEY_SHARE]));
  });

  it("finds articles by their shown details", async () => {
    const { user } = await renderLoaded();

    await user.type(screen.getByRole("searchbox", { name: "table.search_placeholder" }), "GREENS");

    expect(shownNames()).toEqual(["Carrots"]);
  });
});

describe("ListShareArticles new article", () => {
  it("adds a grown article with the farm's defaults, in the vegetable share", async () => {
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    expect(editCheckbox("commissioning.is_active")).toBeChecked();
    expect(editCheckbox(VEG_SHARE)).toBeChecked();
    expect(editCheckbox(HONEY_SHARE)).not.toBeChecked();
    expect(editCheckbox("commissioning.for_resellers")).toBeChecked();
    expect(editCheckbox(PURCHASED)).not.toBeChecked();
    expect(within(editingRow()).getByRole("button", { name: "commissioning.prices" })).toBeDisabled();
    await typeInto(user, NAME, "Kohlrabi");
    await choose(user, field(UNIT), PIECES);
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({
      name: "Kohlrabi", default_movement_unit: "PCS", is_active: true, is_purchased: false,
      is_sold_to_resellers: true, for_markets: false, share_option_list: ["HARVEST_SHARE"],
    });
    const kohlrabi = await waitFor(() => rowOf("Kohlrabi"));
    expect(cellOf(kohlrabi, UNIT)).toHaveTextContent(PIECES);
    expect(flag(kohlrabi, VEG_SHARE)).toBeChecked();
    await user.click(within(kohlrabi).getByRole("button", { name: "commissioning.prices" }));
    expect(screen.getByRole("dialog", { name: "Prices" })).toHaveTextContent("Prices of Kohlrabi (article-new-1)");
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });

  it("marks a bought-in article in its name and takes purchase values instead of harvest ones", async () => {
    const { user } = await renderLoaded();
    const harvestInput = () => within(editingRow()).queryByLabelText("commissioning.default_kg_per_pu_harvest");
    const purchaseInput = () => within(editingRow()).queryByLabelText("commissioning.default_kg_per_pu_purchase");

    await startNewArticle(user, "Oranges", KG);
    expect(harvestInput()).toBeInTheDocument();
    expect(purchaseInput()).not.toBeInTheDocument();
    await user.click(editCheckbox(PURCHASED)!);

    expect(harvestInput()).not.toBeInTheDocument();
    await typeInto(user, "commissioning.default_kg_per_pu_purchase", "12,5");
    await saveRow(user);

    await createdOnce();
    const bought = { name: `Oranges ${PURCHASED_SUFFIX}`, is_purchased: true, default_kg_per_pu_purchase: "12.5" };
    expect(created()).toMatchObject(bought);
    const oranges = await waitFor(() => rowOf(`Oranges ${PURCHASED_SUFFIX}`));
    expect(cellOf(oranges, "commissioning.default_kg_per_pu_purchase")).toHaveTextContent("12,500");
  });

  it("puts a new article into the share option the list is filtered to", async () => {
    const { user } = await renderLoaded();
    await pickFilter(user, HONEY_SHARE);

    await startNewArticle(user, "Acacia honey", PIECES);
    expect(editCheckbox(HONEY_SHARE)).toBeChecked();
    await saveRow(user);

    await createdOnce();
    expect(created()?.share_option_list).toEqual(["HONEY_SHARE"]);
    expect(flag(await waitFor(() => rowOf("Acacia honey")), HONEY_SHARE)).toBeChecked();
  });

  it("puts a new article into no share option on a farm without a vegetable share", async () => {
    api.activeShareOptions.mockImplementation(async () => ({ ...ACTIVE_SHARE_OPTIONS, HARVEST_SHARE: false }));
    const { user } = await renderLoaded();

    await startNewArticle(user, "Acacia honey", PIECES);
    expect(editCheckbox(VEG_SHARE)).not.toBeInTheDocument();
    expect(editCheckbox(HONEY_SHARE)).not.toBeChecked();
    await saveRow(user);

    await createdOnce();
    expect(created()?.share_option_list).toEqual([]);
  });

  it("refuses a new article repeating one hidden as inactive", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByText("Radishes")).not.toBeInTheDocument();

    await startNewArticle(user, "Radishes", "commissioning.units.bunch");
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("starts a new article with the farm's surcharge for the bulk packing list", async () => {
    tenantState.settings = { packing_mode: "BULK", percentage_added_to_bulk_packing_list: 15 };
    const { user } = await renderLoaded();

    expect(cellOf(rowOf("Carrots"), BULK_SURCHARGE)).toHaveTextContent("10 %");
    await startNewArticle(user, "Kohlrabi", PIECES);
    expect(within(editingRow()).getByLabelText(BULK_SURCHARGE)).toHaveValue("15");
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({ percentage_added_to_bulk_packing_list: 15 });
    expect(cellOf(await waitFor(() => rowOf("Kohlrabi")), BULK_SURCHARGE)).toHaveTextContent("15 %");
  });

  it("refuses a new article without a name and a unit", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(2);
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("refuses an article with the name, unit and purchase flag of another, and takes another unit", async () => {
    const { user } = await renderLoaded();

    await startNewArticle(user, "Carrots", KG);
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(within(editingRow()).getByLabelText(NAME)).toBeInvalid();
    expect(api.createArticle).not.toHaveBeenCalled();

    await choose(user, field(UNIT), "commissioning.units.bunch");
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({ name: "Carrots", default_movement_unit: "BUNCH", is_purchased: false });
    expect(screen.queryByText(DUPLICATE)).not.toBeInTheDocument();
  });

  it("checks a bought-in article for repeats under its marked name", async () => {
    const { user } = await renderLoaded();

    await startNewArticle(user, "Lemons", KG);
    await user.click(editCheckbox(PURCHASED)!);
    await saveRow(user);

    expect(await screen.findByText(DUPLICATE)).toBeVisible();
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new article", async () => {
    silenceConsoleErrors();
    const message = "share article with this article number already exists.";
    api.createArticle.mockRejectedValue(
      httpError(400, { code: "validation_error", message, details: { article_number: [message] } }),
    );
    const { user } = await renderLoaded();

    await startNewArticle(user, "Kohlrabi", PIECES);
    await typeInto(user, "commissioning.article_number", "A-100");
    await saveRow(user);

    const banner = `commissioning.article_number: ${message} — table.save_failed_hint`;
    expect(await screen.findByText(banner)).toBeVisible();
    expect(within(editingRow()).getByLabelText("commissioning.article_number")).toBeInvalid();
    expect(screen.queryByText("Kohlrabi")).not.toBeInTheDocument();
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    expect(within(editingRow()).getByLabelText(NAME)).toHaveValue("");
    expect(bodyRows()).toHaveLength(5);
  });
});

describe("ListShareArticles editing and deleting", () => {
  it("saves a changed article under its id, keeps share options without a column, and doesn't reload", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Apples");
    expect(within(editingRow()).getByLabelText("commissioning.kg_per_piece_M")).toHaveValue("0,200");
    await typeInto(user, DESCRIPTION, "Crisp, from the orchard");
    await typeInto(user, "commissioning.kg_per_piece_M", "0,18");
    await user.click(editCheckbox(VEG_SHARE)!);
    await saveRow(user);

    await updatedOnce();
    const changes = {
      name: "Apples", default_movement_unit: "KG", is_purchased: false, description: "Crisp, from the orchard",
      kg_per_piece_M: "0.18", share_option_list: ["HARVEST_SHARE_FRUIT"],
    };
    expect(api.updateArticle).toHaveBeenCalledWith("article-apples", expect.objectContaining(changes));
    expect(await screen.findByText("Crisp, from the orchard")).toBeInTheDocument();
    const apples = rowOf("Apples");
    expect(cellOf(apples, "commissioning.kg_per_piece_M")).toHaveTextContent("0,180");
    expect(flag(apples, VEG_SHARE)).not.toBeChecked();
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });

  it("locks the name, unit and purchase flag of an article in use, and offers no delete", async () => {
    const { user } = await renderLoaded();
    expect(within(rowOf("Carrots")).queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();

    await editRow(user, "Carrots");
    expect(within(editingRow()).queryByLabelText(NAME)).not.toBeInTheDocument();
    expect(within(editingRow()).queryByRole("combobox", { name: UNIT })).not.toBeInTheDocument();
    expect(editCheckbox(PURCHASED)).not.toBeInTheDocument();
    await typeInto(user, DESCRIPTION, "Washed, without greens");
    await saveRow(user);

    await updatedOnce();
    const sent = {
      name: "Carrots", default_movement_unit: "KG", is_purchased: false, description: "Washed, without greens",
      share_option_list: ["HARVEST_SHARE"], default_crate_harvest: EURO_CRATE.id,
      default_crate_reseller: HARVEST_BIN.id,
    };
    expect(api.updateArticle).toHaveBeenCalledWith("article-carrots", expect.objectContaining(sent));
  });

  it("removes an article after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Forest honey");

    await waitFor(() => expect(api.destroyArticle).toHaveBeenCalledWith("article-honey"));
    await waitFor(() => expect(api.listArticles).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Forest honey")).not.toBeInTheDocument();
    expect(screen.getByText("Carrots")).toBeInTheDocument();
  });

  it("shows why the server refused to delete an article and keeps it", async () => {
    silenceConsoleErrors();
    api.destroyArticle.mockRejectedValue(
      httpError(409, { code: "share_article.in_use", message: "The share article is still in use." }),
    );
    const { user } = await renderLoaded();

    await deleteRow(user, "Forest honey");

    expect(await screen.findByText(germanErrors.share_article.in_use)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Forest honey")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });
});

describe("ListShareArticles prices", () => {
  it("opens the prices of the article whose price button the office clicks", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByRole("dialog", { name: "Prices" })).not.toBeInTheDocument();

    await user.click(rowButton("Carrots", "commissioning.prices"));

    expect(screen.getByRole("dialog", { name: "Prices" })).toHaveTextContent("Prices of Carrots (article-carrots)");
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close prices" }));
    expect(screen.queryByRole("dialog", { name: "Prices" })).not.toBeInTheDocument();

    await user.click(rowButton(LEMONS_NAME, "commissioning.prices"));

    const lemonPrices = `Prices of ${LEMONS_NAME} (article-lemons)`;
    expect(screen.getByRole("dialog", { name: "Prices" })).toHaveTextContent(lemonPrices);
  });

  it.each(["gardener", "staff", "management"])("offers no prices to the %s, who doesn't manage them", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "commissioning.prices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Prices" })).not.toBeInTheDocument();
  });
});

describe("ListShareArticles organic status", () => {
  const certifyFarm = () => {
    tenantState.record.organic_control_number = "AT-BIO-301";
  };

  it("shows each article's organic status and starts a new article as organic on a certified farm", async () => {
    certifyFarm();
    const { user } = await renderLoaded();

    expect(columnTitles().indexOf(ORGANIC)).toBe(columnTitles().indexOf(PURCHASED) + 1);
    expect(cellOf(rowOf("Carrots"), ORGANIC)).toHaveTextContent("commissioning.organic.organic");
    expect(cellOf(rowOf(LEMONS_NAME), ORGANIC)).toHaveTextContent("commissioning.organic.in_conversion");
    expect(cellOf(rowOf("Forest honey"), ORGANIC)).toHaveTextContent("commissioning.organic.conventional");

    await startNewArticle(user, "Kohlrabi", PIECES);
    expect(selectedIn(field(ORGANIC))).toBe("commissioning.organic.organic");
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({ organic_status: "organic" });
  });

  it("saves a new article as conventional when the office picks that on a certified farm", async () => {
    certifyFarm();
    const { user } = await renderLoaded();

    await startNewArticle(user, "Kohlrabi", PIECES);
    await choose(user, field(ORGANIC), "commissioning.organic.conventional");
    await saveRow(user);

    await createdOnce();
    expect(created()).toMatchObject({ organic_status: "conventional" });
    const kohlrabi = await waitFor(() => rowOf("Kohlrabi"));
    expect(cellOf(kohlrabi, ORGANIC)).toHaveTextContent("commissioning.organic.conventional");
  });

  it("leaves the organic status out on a farm without an organic certificate", async () => {
    const { user } = await renderLoaded();
    expect(columnTitles()).not.toContain(ORGANIC);

    await startNewArticle(user, "Kohlrabi", PIECES);
    await saveRow(user);

    await createdOnce();
    expect(created()).not.toHaveProperty("organic_status");
  });
});

describe("ListShareArticles tenant settings", () => {
  it("leaves out the reseller and market flags when the farm sells to neither", async () => {
    tenantState.settings = { has_markets: false, sells_to_resellers: false };
    await renderLoaded();

    expect(columnTitles()).not.toContain("commissioning.for_resellers");
    expect(columnTitles()).not.toContain("commissioning.for_markets");
    expect(columnTitles()).toContain(HONEY_SHARE);
  });

  it("offers a packing station for each one the farm runs", async () => {
    tenantState.settings = { number_packing_stations: 3 };
    const { user } = await renderLoaded();

    await editRow(user, "Forest honey");

    expect(await optionsOf(user, field("commissioning.packing_station"))).toEqual(["", "1", "2", "3"]);
  });

  it.each([
    ["BULK", true], ["MIXED", true], ["BOXES", false],
  ])("shows the bulk packing surcharge, after the packing station, when the farm packs %s: %s", async (mode, shown) => {
    tenantState.settings = { packing_mode: mode };
    await renderLoaded();

    const titles = columnTitles();
    expect(titles.indexOf(BULK_SURCHARGE)).toBe(shown ? titles.indexOf("commissioning.packing_station") + 1 : -1);
  });
});

describe("ListShareArticles exports and import", () => {
  it("gives the office the price, list and combined exports, each in its own dialog", async () => {
    const { user } = await renderLoaded();
    const exports: [RegExp, string, string][] = [
      [/commissioning\.export_prices/, "Price export", "Close price export"],
      [/commissioning\.share_article_list_csv_export/, "Article list export", "Close list export"],
      [/commissioning\.export_all_articles_combined/, "Combined export", "Close combined export"],
    ];

    for (const [button, dialog, close] of exports) {
      expect(screen.queryByRole("dialog", { name: dialog })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: button }));
      expect(screen.getByRole("dialog", { name: dialog })).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: close }));
      expect(screen.queryByRole("dialog", { name: dialog })).not.toBeInTheDocument();
    }
  });

  it("exports the articles the list shows, with its columns, under the list's name", async () => {
    const { user } = await renderLoaded();
    await pickFilter(user, HONEY_SHARE);

    await user.click(screen.getByRole("button", { name: /commissioning\.share_article_list_csv_export/ }));

    expect(stubs.exportCsv?.filename).toBe("commissioning.share_articles");
    expect(stubs.exportCsv?.data.map((row) => row.id)).toEqual(["article-honey"]);
    expect(stubs.exportCsv?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining(["article_number", "name", "default_movement_unit", "honey_share"]),
    );
  });

  it("offers no CSV import unless the tenant allows uploads", async () => {
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "csv_upload.open" })).not.toBeInTheDocument();
  });

  it("imports articles from a template of the list's columns and reloads the list", async () => {
    tenantState.settings = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "csv_upload.open" }));

    expect(await screen.findByRole("dialog", { name: "csv_upload.import_title" })).toBeInTheDocument();
    const template = { filename: "commissioning.share_articles_template.csv", modelName: "share_article" };
    expect(stubs.template).toMatchObject(template);
    expect(stubs.template?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining(["name", "default_movement_unit", "is_purchased", "harvest_share", "honey_share"]),
    );

    serverArticles = [...serverArticles, article("article-beetroot", "Beetroot", ["HARVEST_SHARE"])];
    await user.click(screen.getByRole("button", { name: "Upload the filled-in template" }));

    expect(await screen.findByText("Beetroot")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(2);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "csv_upload.import_title" })).not.toBeInTheDocument(),
    );
  });
});

describe("ListShareArticles roles", () => {
  it.each([
    ["office", 3], ["admin", 3], ["gardener", 0], ["staff", 0],
  ])("lets the %s add, edit and delete articles, offering %i exports", async (role, exports) => {
    auth.roles = [role];
    await renderLoaded();

    expect(addButton()).toBeEnabled();
    expect(rowButton("Forest honey", "table.edit")).toBeEnabled();
    expect(rowButton("Forest honey", "table.delete")).toBeEnabled();
    expect(screen.queryAllByRole("button", { name: EXPORTS })).toHaveLength(exports);
  });

  it("shows the articles read-only to the management", async () => {
    auth.roles = ["management"];
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EXPORTS })).not.toBeInTheDocument();

    await user.click(screen.getByText("Forest honey"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });
});
