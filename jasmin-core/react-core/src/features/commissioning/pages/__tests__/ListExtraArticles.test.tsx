/**
 * ListExtraArticles: the farm's extra articles — share articles flagged `is_extra`, such as a gardening
 * course or a jute bag, sold on top of the shares — with their article number, name, unit and description,
 * edited inline by the office. Rendered through the real useCrudListPage, EditableTable, active-column and
 * unit-option hooks and the CSV import dialog. The generated commissioning client is the mocking boundary:
 * its list hook is a real TanStack query around a spy that answers from an in-memory farm the way the
 * backend does — regular articles unless the request asks for the extras — and whose mutations echo the
 * saved article. The price editor and the two exports are other screens and stand in as stubs that show
 * what they were opened for; so does the import dialog's template and upload button, which talks to the
 * import endpoint itself.
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

// The tenant's settings, per test; an unset setting falls back to the caller's default.
const tenantState = vi.hoisted(() => ({ settings: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
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
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryKey = (params?: unknown) => ["/api/commissioning/share_articles/", ...(params ? [params] : [])];
  return {
    useCommissioningShareArticlesList: function useShareArticlesList(params?: unknown) {
      return useQuery({ queryKey: queryKey(params), queryFn: async () => api.listArticles(params) });
    },
    getCommissioningShareArticlesListQueryKey: queryKey,
    commissioningShareArticlesCreate: (article: unknown) => api.createArticle(article),
    commissioningShareArticlesPartialUpdate: (id: string, article: unknown) => api.updateArticle(id, article),
    commissioningShareArticlesDestroy: (id: string) => api.destroyArticle(id),
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
  fixedValues?: Row; onUploadSuccess?: () => void; onImported?: () => void;
};

// The props the stubbed list export and import template got on their last render.
const stubs = vi.hoisted(() => ({
  exportCsv: null as ExportCsvStubProps | null, template: null as TemplateStubProps | null,
  priceExport: null as (DialogStubProps & { extrasOnly?: boolean }) | null,
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
  const ListExport = stubDialog("Extra article list export", "Close list export");
  const PriceExport = stubDialog("Price export", "Close price export");
  return {
    ExportCsv: (props: ExportCsvStubProps) => {
      stubs.exportCsv = props;
      return <ListExport open={props.open} onClose={props.onClose} />;
    },
    ExportCsvPricesShareArticle: (props: DialogStubProps & { extrasOnly?: boolean }) => {
      stubs.priceExport = props;
      return <PriceExport open={props.open} onClose={props.onClose} />;
    },
    ShareArticleExtraPriceModal: ({ visible, onClose, share_article, share_article_name }: PriceModalStubProps) =>
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

import ListExtraArticles from "../ListExtraArticles";

// ── Fixtures ────────────────────────────────────────────────────────────────

// What the server stores for the fields a request leaves out.
const MODEL_DEFAULTS: Row = {
  is_active: true, is_extra: false, article_number: null, description: null, share_option: null,
  share_option2: null, share_option3: null, is_purchased: false, is_sold_to_resellers: false, for_markets: false,
  organic_status: "conventional", can_be_deleted: true,
};

const extra = (id: string, name: string, fields: Row = {}) =>
  ({ ...MODEL_DEFAULTS, id, name, is_extra: true, default_movement_unit: "PCS", ...fields }) as ShareArticle;

// Already booked by members, so the backend protects it.
const COURSE = extra("extra-course", "Gardening course", {
  article_number: "X-100", description: "Saturday morning, three hours", can_be_deleted: false,
});
// Its article number keeps its leading zeros.
const JUTE_BAG = extra("extra-bag", "Jute bag", { article_number: "00042" });
// No longer offered.
const TRACTOR = extra("extra-tractor", "Tractor hire", { description: "Per hour, with driver", is_active: false });
// A regular share article, which belongs to the share-article list.
const CARROTS = {
  ...MODEL_DEFAULTS, id: "article-carrots", name: "Carrots", default_movement_unit: "KG", share_option: "HARVEST_SHARE",
} as ShareArticle;

// What the server currently holds; the list requests answer from it.
let serverArticles: ShareArticle[] = [];

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Row) =>
  Object.assign(new Error(`Request failed with status ${status}`), { isAxiosError: true, response: { status, data } });

beforeEach(() => {
  auth.roles = ["office"];
  tenantState.settings = {};
  Object.assign(stubs, { exportCsv: null, template: null, priceExport: null });
  serverArticles = [COURSE, JUTE_BAG, TRACTOR, CARROTS];
  let createdCount = 0;
  // Like the backend, a list without ``is_extra`` holds the regular articles only.
  api.listArticles.mockReset().mockImplementation(async (params?: { is_extra?: boolean }) =>
    serverArticles.filter((each) => Boolean(each.is_extra) === (params?.is_extra ?? false)),
  );
  api.createArticle.mockReset().mockImplementation(async (payload: Row) => {
    createdCount += 1;
    const { key: _key, ...fields } = payload;
    const saved = { ...MODEL_DEFAULTS, ...fields, id: `extra-new-${createdCount}` } as ShareArticle;
    serverArticles = [...serverArticles, saved];
    return saved;
  });
  api.updateArticle.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = serverArticles.find((each) => each.id === id);
    if (!current) throw httpError(404, { code: "share_article.not_found", message: "Not found." });
    const { key: _key, ...fields } = payload;
    const saved = { ...current, ...fields, id } as ShareArticle;
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
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListExtraArticles />)}</QueryClientProvider>);
  return { user, profiler };
}

const ACTIVE = "commissioning.is_active";
const NUMBER = "commissioning.article_number";
const NAME = "commissioning.name";
const UNIT = "commissioning.default_movement_unit";
const DESCRIPTION = "commissioning.description";
const PIECES = "commissioning.units.pcs";
const PRICES = "commissioning.prices";
const TITLE = "commissioning.extra_articles";

/** Renders the page and waits until the extras are there. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Gardening course");
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

/** The read-only checkbox a row shows for its active flag. */
const activeFlag = (row: HTMLElement) => within(cellOf(row, ACTIVE)).getByRole("checkbox");

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const addButton = () => screen.queryByRole("button", { name: /table\.add_record/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const heading = () => screen.getByRole("heading", { level: 1, name: TITLE });

type User = ReturnType<typeof userEvent.setup>;

const input = (label: string) => within(editingRow()).getByLabelText(label);
const activeCheckbox = () => within(editingRow()).getByRole("checkbox", { name: ACTIVE });
const unitSelect = () => within(editingRow()).queryByRole("combobox", { name: UNIT });

// The table puts the cursor into a row a frame after the row opens for editing
// — a new row's name, an existing row's first field — so a test waits for it
// before typing, and no keystroke lands in another field.
const cursorIn = (field: () => HTMLElement) => waitFor(() => expect(field()).toHaveFocus());

async function startNewRow(user: User) {
  await user.click(addButton()!);
  await cursorIn(() => input(NAME));
}

async function editRow(user: User, name: string) {
  await user.click(rowButton(name, "table.edit"));
  await cursorIn(activeCheckbox);
}

const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, name: string) {
  await user.click(rowButton(name, "table.delete"));
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  await user.clear(input(label));
  await user.type(input(label), text);
}

/** The request body of the last create, without the table's own row key. */
function created(): Row | undefined {
  const payload = api.createArticle.mock.lastCall?.[0] as Row | undefined;
  if (!payload) return undefined;
  const { key: _key, ...sent } = payload;
  return sent;
}
const createdOnce = () => waitFor(() => expect(api.createArticle).toHaveBeenCalledTimes(1));
const updatedOnce = () => waitFor(() => expect(api.updateArticle).toHaveBeenCalledTimes(1));
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("ListExtraArticles loading and layout", () => {
  it("asks for the extras only, once", async () => {
    renderPage();

    expect(await screen.findByText("Gardening course")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(1);
    expect(api.listArticles).toHaveBeenCalledWith({ is_extra: true });
    expect(shownNames()).toEqual(["Gardening course", "Jute bag"]);
    expect(screen.queryByText("Carrots")).not.toBeInTheDocument();
  });

  it("shows a spinner over the table while the extras load", async () => {
    let deliver: (rows: ShareArticle[]) => void = () => {};
    api.listArticles.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([COURSE]);

    expect(await screen.findByText("Gardening course")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(heading()).toBeVisible();
    expect(screen.getByText("commissioning.extra_articles_description")).toBeInTheDocument();
    // The price buttons' column has no title.
    expect(columnTitles()).toEqual(["table.actions", ACTIVE, NUMBER, NAME, "", UNIT, DESCRIPTION]);
    expect(screen.getByText("common.info")).toBeInTheDocument();
    expect(screen.getByText("explainers.list_extra_articles")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when the farm has no extras", async () => {
    serverArticles = [CARROTS];
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(screen.getByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the extras fail to load", async () => {
    api.listArticles.mockRejectedValue(httpError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listArticles).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(heading()).toBeVisible();
    expect(addButton()).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("ListExtraArticles rows", () => {
  it("shows each extra's number as written, its name, its unit by label and its description", async () => {
    await renderLoaded();

    expect(cellTexts(rowOf("Gardening course"), [NUMBER, UNIT, DESCRIPTION])).toEqual({
      [NUMBER]: "X-100", [UNIT]: PIECES, [DESCRIPTION]: "Saturday morning, three hours",
    });
    expect(cellTexts(rowOf("Jute bag"), [NUMBER, UNIT, DESCRIPTION])).toEqual({
      [NUMBER]: "00042", [UNIT]: PIECES, [DESCRIPTION]: "",
    });
    expect(activeFlag(rowOf("Gardening course"))).toBeChecked();
    expect(activeFlag(rowOf("Jute bag"))).toBeChecked();
  });

  it("hides the extras no longer offered until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(screen.queryByText("Tractor hire")).not.toBeInTheDocument();

    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(shownNames()).toEqual(["Gardening course", "Jute bag", "Tractor hire"]);
    expect(activeFlag(rowOf("Tractor hire"))).not.toBeChecked();
    expect(cellOf(rowOf("Tractor hire"), UNIT)).toHaveTextContent(PIECES);
  });

  it("finds extras by their shown details", async () => {
    const { user } = await renderLoaded();

    await user.type(screen.getByRole("searchbox", { name: "table.search_placeholder" }), "SATURDAY");

    expect(shownNames()).toEqual(["Gardening course"]);
  });
});

describe("ListExtraArticles new extra", () => {
  it("adds an active extra in pieces, marked as extra, and doesn't reload the list", async () => {
    const { user } = await renderLoaded();

    await startNewRow(user);
    expect(activeCheckbox()).toBeChecked();
    expect(unitSelect()).not.toBeInTheDocument();
    expect(within(editingRow()).getByRole("button", { name: PRICES })).toBeDisabled();
    await typeInto(user, NAME, "Farm tour");
    await typeInto(user, NUMBER, "X-200");
    await typeInto(user, DESCRIPTION, "Guided, ninety minutes");
    await saveRow(user);

    await createdOnce();
    expect(created()).toEqual({
      is_active: true, article_number: "X-200", name: "Farm tour", description: "Guided, ninety minutes",
      is_extra: true, default_movement_unit: "PCS",
    });
    const tour = await waitFor(() => rowOf("Farm tour"));
    expect(cellTexts(tour, [NUMBER, UNIT])).toEqual({ [NUMBER]: "X-200", [UNIT]: PIECES });
    await user.click(within(tour).getByRole("button", { name: PRICES }));
    expect(screen.getByRole("dialog", { name: "Prices" })).toHaveTextContent("Prices of Farm tour (extra-new-1)");
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });

  it("refuses a new extra without a name", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, DESCRIPTION, "Guided, ninety minutes");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(1);
    expect(input(NAME)).toBeInvalid();
    expect(api.createArticle).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new extra", async () => {
    silenceConsoleErrors();
    const message = "share article with this article number already exists.";
    api.createArticle.mockRejectedValue(
      httpError(400, { code: "validation_error", message, details: { article_number: [message] } }),
    );
    const { user } = await renderLoaded();

    await startNewRow(user);
    await typeInto(user, NAME, "Farm tour");
    await typeInto(user, NUMBER, "X-100");
    await saveRow(user);

    expect(await screen.findByText(`${NUMBER}: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(input(NUMBER)).toBeInvalid();
    expect(input(NAME)).toHaveValue("Farm tour");
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    await cursorIn(() => input(NAME));
    expect(input(NAME)).toHaveValue("");
    expect(bodyRows()).toHaveLength(3);
  });
});

describe("ListExtraArticles editing and deleting", () => {
  it("saves a changed extra under its id, still as an extra in pieces, and doesn't reload", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Jute bag");
    expect(input(NUMBER)).toHaveValue("00042");
    expect(unitSelect()).not.toBeInTheDocument();
    expect(cellOf(editingRow(), UNIT)).toHaveTextContent(PIECES);
    await typeInto(user, NUMBER, "00043");
    await typeInto(user, DESCRIPTION, "Printed with the farm's logo");
    await saveRow(user);

    await updatedOnce();
    const changes = {
      name: "Jute bag", is_active: true, article_number: "00043", description: "Printed with the farm's logo",
      is_extra: true, default_movement_unit: "PCS",
    };
    expect(api.updateArticle).toHaveBeenCalledWith("extra-bag", expect.objectContaining(changes));
    expect(await screen.findByText("Printed with the farm's logo")).toBeInTheDocument();
    expect(cellTexts(rowOf("Jute bag"), [NUMBER, UNIT])).toEqual({ [NUMBER]: "00043", [UNIT]: PIECES });
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });

  it("retires an extra when the office unticks it as active", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Jute bag");
    await user.click(activeCheckbox());
    await saveRow(user);

    await updatedOnce();
    expect(api.updateArticle).toHaveBeenCalledWith(
      "extra-bag", expect.objectContaining({ name: "Jute bag", is_active: false, is_extra: true }),
    );
  });

  it("locks the name of an extra in use and offers no delete for it", async () => {
    const { user } = await renderLoaded();
    expect(within(rowOf("Gardening course")).queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
    expect(rowButton("Jute bag", "table.delete")).toBeEnabled();

    await editRow(user, "Gardening course");
    expect(within(editingRow()).queryByLabelText(NAME)).not.toBeInTheDocument();
    await typeInto(user, DESCRIPTION, "Saturday afternoon, three hours");
    await saveRow(user);

    await updatedOnce();
    const sent = {
      name: "Gardening course", article_number: "X-100", description: "Saturday afternoon, three hours",
      is_extra: true, default_movement_unit: "PCS",
    };
    expect(api.updateArticle).toHaveBeenCalledWith("extra-course", expect.objectContaining(sent));
  });

  it("removes an extra after confirmation and reloads the list", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Jute bag");

    await waitFor(() => expect(api.destroyArticle).toHaveBeenCalledWith("extra-bag"));
    await waitFor(() => expect(api.listArticles).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Jute bag")).not.toBeInTheDocument();
    expect(screen.getByText("Gardening course")).toBeInTheDocument();
  });

  it("shows why the server refused to delete an extra and keeps it", async () => {
    silenceConsoleErrors();
    api.destroyArticle.mockRejectedValue(
      httpError(409, { code: "share_article.in_use", message: "The share article is still in use." }),
    );
    const { user } = await renderLoaded();

    await deleteRow(user, "Jute bag");

    expect(await screen.findByText(germanErrors.share_article.in_use)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Jute bag")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(1);
  });
});

describe("ListExtraArticles prices", () => {
  it("opens the prices of the extra whose price button the office clicks", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByRole("dialog", { name: "Prices" })).not.toBeInTheDocument();

    await user.click(rowButton("Gardening course", PRICES));

    const prices = screen.getByRole("dialog", { name: "Prices" });
    expect(prices).toHaveTextContent("Prices of Gardening course (extra-course)");
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(within(prices).getByRole("button", { name: "Close prices" }));
    expect(screen.queryByRole("dialog", { name: "Prices" })).not.toBeInTheDocument();

    await user.click(rowButton("Jute bag", PRICES));

    expect(screen.getByRole("dialog", { name: "Prices" })).toHaveTextContent("Prices of Jute bag (extra-bag)");
  });
});

describe("ListExtraArticles exports and import", () => {
  it("opens the price export and the list export, each in its own dialog", async () => {
    const { user } = await renderLoaded();
    const exports: [RegExp, string, string][] = [
      [/commissioning\.export_prices/, "Price export", "Close price export"],
      [/commissioning\.csv_export_extra_articles/, "Extra article list export", "Close list export"],
    ];

    for (const [button, dialog, close] of exports) {
      expect(screen.queryByRole("dialog", { name: dialog })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: button }));
      expect(screen.getByRole("dialog", { name: dialog })).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: close }));
      expect(screen.queryByRole("dialog", { name: dialog })).not.toBeInTheDocument();
    }
  });

  it("exports the prices of the extras only", async () => {
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: /commissioning\.export_prices/ }));

    expect(stubs.priceExport?.extrasOnly).toBe(true);
  });

  it("exports the extras the list shows, with its columns, under the list's name", async () => {
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: /commissioning\.csv_export_extra_articles/ }));

    expect(stubs.exportCsv?.filename).toBe(TITLE);
    expect(stubs.exportCsv?.data.map((row) => row.id)).toEqual(["extra-course", "extra-bag"]);
    expect(stubs.exportCsv?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining(["is_active", "article_number", "name", "default_movement_unit", "description"]),
    );

    await user.click(screen.getByRole("button", { name: "Close list export" }));
    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(stubs.exportCsv?.data.map((row) => row.id)).toEqual(["extra-course", "extra-bag", "extra-tractor"]);
  });

  it("offers no CSV import unless the tenant allows uploads", async () => {
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "csv_upload.open" })).not.toBeInTheDocument();
  });

  it("imports share articles as extras in pieces with a template of the list's columns and reloads the list after it", async () => {
    tenantState.settings = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "csv_upload.open" }));

    expect(await screen.findByRole("dialog", { name: "csv_upload.import_title" })).toBeInTheDocument();
    expect(stubs.template).toMatchObject({
      filename: "commissioning.extra_articles_template.csv", modelName: "share_article",
      fixedValues: { is_extra: true, default_movement_unit: "PCS" },
    });
    expect(stubs.template?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining(["is_active", "article_number", "name", "description"]),
    );

    serverArticles = [...serverArticles, extra("extra-seed", "Seed potatoes")];
    await user.click(screen.getByRole("button", { name: "Upload the filled-in template" }));

    expect(await screen.findByText("Seed potatoes")).toBeInTheDocument();
    expect(api.listArticles).toHaveBeenCalledTimes(2);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "csv_upload.import_title" })).not.toBeInTheDocument(),
    );
  });
});

describe("ListExtraArticles roles", () => {
  it.each(["office", "admin"])("lets the %s add, edit and delete extras", async (role) => {
    auth.roles = [role];
    await renderLoaded();

    expect(addButton()).toBeEnabled();
    expect(rowButton("Jute bag", "table.edit")).toBeEnabled();
    expect(rowButton("Jute bag", "table.delete")).toBeEnabled();
    expect(rowButton("Gardening course", "table.edit")).toBeEnabled();
  });

  it.each(["gardener", "staff", "management"])("shows the extras read-only to the %s", async (role) => {
    auth.roles = [role];
    const { user } = await renderLoaded();

    expect(addButton()).not.toBeInTheDocument();
    expect(columnTitles()).not.toContain("table.actions");
    expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();
    expect(cellTexts(rowOf("Jute bag"), [NUMBER, UNIT])).toEqual({ [NUMBER]: "00042", [UNIT]: PIECES });

    await user.click(screen.getByText("Jute bag"));
    await user.keyboard("+");

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });
});
