/**
 * ListSellers: the office's list of sellers, the farms and traders the farm
 * buys from. A seller is a reseller row with the seller role, so a seller can
 * be a reseller and a delivery station too. Rendered through the real
 * CrudListPage, EditableTable, contact columns, organic gate and CSV import
 * dialog; the generated commissioning client is the mocking boundary, its
 * list hook a real TanStack query around a spy that answers from an in-memory
 * server the way the backend does: it lists the rows with the seller role, and
 * a delete from the seller page drops that role, deleting the row only when it
 * was its last. The organic certificate editor is another screen and stands in
 * as a stub that shows whom it was opened for; so does the import dialog's
 * template and upload button, which talks to the import endpoint itself.
 *
 * Nothing on this page reads today's date, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Reseller } from "@shared/api/generated/models";
import germanErrors from "@shared/i18n/locales/de/errors.json";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// One `t` for every render, as react-i18next keeps it.
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

// `useRoles` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-office", roles: auth.roles } }),
}));

// Inline row editing, the mode a new user starts in.
vi.mock("@shared/contexts/ModalContext", () => ({ useModal: () => ({ isModalMode: false }) }));

const api = vi.hoisted(() => ({
  listResellers: vi.fn(),
  createReseller: vi.fn(),
  updateReseller: vi.fn(),
  destroyReseller: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const resellersKey = (params?: unknown) => [
    "/api/commissioning/resellers/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningResellersListQueryKey: resellersKey,
    useCommissioningResellersList: (params?: unknown) =>
      useQuery({ queryKey: resellersKey(params), queryFn: () => api.listResellers(params) }),
    commissioningResellersCreate: (body: unknown) => api.createReseller(body),
    commissioningResellersPartialUpdate: (id: string, body: unknown) => api.updateReseller(id, body),
    commissioningResellersDestroy: (id: string, params: unknown) => api.destroyReseller(id, params),
  };
});

type Row = Record<string, unknown>;
type CertificatesStubProps = {
  visible: boolean;
  onClose: () => void;
  reseller: string | null;
  reseller_name: string;
};
type TemplateStubProps = {
  columns: {
    dataIndex?: string | number;
    readOnly?: boolean;
    disabled?: unknown;
    importable?: boolean;
  }[];
  filename: string;
  modelName?: string;
  fixedValues?: Row;
  onUploadSuccess?: () => void;
  onImported?: () => void;
};

// The props the stubbed import template got on its last render.
const stubs = vi.hoisted(() => ({ template: null as TemplateStubProps | null }));

vi.mock("@features/commissioning/modals/OrganicCertificatesModal", () => ({
  default: ({ visible, onClose, reseller, reseller_name }: CertificatesStubProps) =>
    visible ? (
      <div role="dialog" aria-label="Organic certificates">
        <p>{`Certificates of ${reseller_name} (${reseller})`}</p>
        <button type="button" onClick={onClose}>
          Close certificates
        </button>
      </div>
    ) : null,
}));

// The real import button and dialog, without the rest of the shared modals.
vi.mock("@shared/modals", async () => ({
  CsvImportButton: (await import("@shared/modals/CsvImportModal")).CsvImportButton,
}));

// Its upload stands for a CSV the import endpoint took in full.
vi.mock("@shared/ui/DownloadCsvTemplateButton", () => ({
  default: (props: TemplateStubProps) => {
    stubs.template = props;
    const upload = () =>
      [props.onUploadSuccess, props.onImported].forEach((callback) => callback?.());
    return (
      <button type="button" onClick={upload}>
        Upload the filled-in template
      </button>
    );
  },
}));

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({
  default: notify,
  registerAnnouncer: () => {},
  announcePolite: () => {},
}));

import ListSellers from "../ListSellers";

// ── Fixtures ────────────────────────────────────────────────────────────────

/** A seller as the reseller list returns it. */
function seller(overrides: Partial<Reseller> & { id: string }): Reseller {
  return {
    is_seller: true, is_active_seller: true, is_reseller: false, is_active_reseller: false,
    is_also_delivery_station: false, linked_delivery_station_can_be_deleted: true,
    name_for_member_pages: null, company_name: null, first_name: null, last_name: null,
    address: "", zip_code: "", city: "", email: null, phone: null, phone_2: null,
    organic_control_number: null, has_active_organic_certificate: false,
    linked_user_info: null, can_be_deleted: true,
    ...overrides,
  };
}

// Has sold to the farm, so the backend protects it; certified organic, with a
// certificate valid today.
const GRUBER = seller({
  id: "res-gruber", company_name: "Gemüsebau Gruber", first_name: "Anna", last_name: "Gruber",
  address: "Feldweg 4", zip_code: "4020", city: "Linz", email: "anna@gruber.example",
  phone: "+43 732 100", phone_2: "+43 664 200", name_for_member_pages: "Gruber's vegetables",
  organic_control_number: "AT-BIO-301", has_active_organic_certificate: true, can_be_deleted: false,
});
// Certified organic, but its certificate has run out; also a reseller.
const OBSTHOF = seller({
  id: "res-obsthof", company_name: "Obsthof Maier", first_name: "Bernd", last_name: "Maier",
  address: "Obstgasse 2", zip_code: "4600", city: "Wels",
  organic_control_number: "AT-BIO-402", is_reseller: true, is_active_reseller: true,
});
// A cheese dairy without a control number, also a delivery station.
const BERGER = seller({
  id: "res-berger", company_name: "Hofkäserei Berger", address: "Almweg 7", zip_code: "4400",
  city: "Steyr", is_also_delivery_station: true,
});
// No longer bought from.
const HUBER = seller({
  id: "res-huber", company_name: "Imkerei Huber", address: "Bienenweg 1", zip_code: "4470",
  city: "Enns", is_active_seller: false,
});

// What the server currently holds; the list requests answer from it.
let serverRows: Reseller[] = [];
let createdCount = 0;

/** A rejected request as axios hands it over, carrying the server's body. */
function axiosError(status: number, data: Row) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });
}

/** The fields of a request body the serializer stores; the row's bookkeeping falls away. */
function storedFields(body: Row): Row {
  const { key: _key, ...fields } = body;
  return fields;
}

beforeEach(() => {
  auth.roles = ["office"];
  tenantState.record.organic_control_number = "";
  tenantState.settings = {};
  stubs.template = null;
  createdCount = 0;
  serverRows = [GRUBER, OBSTHOF, BERGER, HUBER];
  notify.success.mockReset();
  notify.error.mockReset();
  api.listResellers.mockReset().mockImplementation(async (params?: { is_seller?: boolean }) =>
    serverRows.filter((row) => !params?.is_seller || row.is_seller),
  );
  api.createReseller.mockReset().mockImplementation(async (body: Row) => {
    createdCount += 1;
    const saved = seller({ ...storedFields(body), id: `res-new-${createdCount}` });
    serverRows = [...serverRows, saved];
    return saved;
  });
  api.updateReseller.mockReset().mockImplementation(async (id: string, body: Row) => {
    const current = serverRows.find((row) => row.id === id);
    if (!current) throw axiosError(404, { code: "reseller.not_found", message: "Not found." });
    const saved = { ...current, ...storedFields(body), id } as Reseller;
    serverRows = serverRows.map((row) => (row.id === id ? saved : row));
    return saved;
  });
  // A delete from the seller page drops the seller role, and the row with it
  // when that was its only role.
  api.destroyReseller.mockReset().mockImplementation(async (id: string) => {
    serverRows = serverRows.flatMap((row) => {
      if (row.id !== id) return [row];
      return row.is_reseller ? [{ ...row, is_seller: false }] : [];
    });
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(<QueryClientProvider client={queryClient}>{profiler.wrap(<ListSellers />)}</QueryClientProvider>);
  return { user, profiler };
}

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}
const rowOf = (text: string) => rowAround(screen.getByText(text), `shows ${text}`);
/** The row being edited inline — the one offering a save button. */
const editingRow = () =>
  rowAround(screen.getByRole("button", { name: "table.save" }), "is being edited");

/** Renders the page and waits until the sellers are listed. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Gemüsebau Gruber");
  await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  return rendered;
}

const bodyRows = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-tbody > tr.ant-table-row"));

const columnTitles = () =>
  Array.from(document.querySelectorAll<HTMLElement>(".ant-table-thead > tr > th")).map(
    (th) => th.textContent?.trim() ?? "",
  );

function cellOf(row: HTMLElement, columnTitle: string): HTMLElement {
  const index = columnTitles().indexOf(columnTitle);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${columnTitle}`);
  return cell;
}

/** The read-only checkbox a row shows for one of its flags. */
const flag = (row: HTMLElement, columnTitle: string) =>
  within(cellOf(row, columnTitle)).getByRole("checkbox");

const shownCompanies = () => bodyRows().map((row) => cellOf(row, COMPANY).textContent);

const rowButton = (text: string, name: string) => within(rowOf(text)).getByRole("button", { name });
const addButton = () => screen.queryByRole("button", { name: /table\.add_plus_icon/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const pageTitle = () => screen.queryByRole("heading", { level: 1, name: "resellers.list_sellers" });

type User = ReturnType<typeof userEvent.setup>;

const editRow = (user: User, company: string) => user.click(rowButton(company, "table.edit"));
const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));
const showInactive = (user: User) => user.click(screen.getByText("commissioning.hide_inactive"));

async function deleteRow(user: User, company: string) {
  await user.click(rowButton(company, "table.delete"));
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await user.clear(input);
  await user.type(input, text);
}

/** Fills the new row with a seller the table accepts. */
async function fillNewSeller(user: User) {
  await typeInto(user, COMPANY, "Gärtnerei Lindner");
  await typeInto(user, "resellers.address", "Lindenweg 3");
  await typeInto(user, "resellers.zip_code", "4400");
  await typeInto(user, "resellers.city", "Steyr");
}

const created = () => api.createReseller.mock.lastCall?.[0] as Row | undefined;
const silenceConsoleErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

// Column titles, as the mocked `t` returns them.
const ACTIVE = "resellers.is_active";
const DELIVERY_STATION = "resellers.is_also_delivery_station";
const RESELLER = "resellers.is_reseller";
const MEMBER_PAGE_NAME = "resellers.name_for_member_pages";
const COMPANY = "resellers.company_name";
const CONTROL_NUMBER = "resellers.organic_control_number";
const CERTIFICATES = "resellers.organic_certificates";
const MANAGE_CERTIFICATES = "resellers.manage_organic_certificates";
const CONTACT_TITLES = [
  "resellers.first_name", "resellers.last_name", "resellers.address", "resellers.zip_code",
  "resellers.city", "resellers.email", "resellers.phone", "resellers.phone2",
];

const certifyFarm = () => {
  tenantState.record.organic_control_number = "AT-BIO-100";
};

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListSellers loading and layout", () => {
  it("loads the sellers with one request scoped to sellers", async () => {
    renderPage();

    expect(await screen.findByText("Gemüsebau Gruber")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
    expect(api.listResellers).toHaveBeenCalledWith({ is_seller: true });
  });

  it("shows a spinner over the table while the sellers load", async () => {
    let deliver: (rows: Reseller[]) => void = () => {};
    api.listResellers.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([GRUBER]);

    expect(await screen.findByText("Gemüsebau Gruber")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(pageTitle()).toBeInTheDocument();
    expect(columnTitles()).toEqual([
      "table.actions", ACTIVE, DELIVERY_STATION, RESELLER, MEMBER_PAGE_NAME, COMPANY, ...CONTACT_TITLES,
    ]);
    expect(screen.getByRole("img", { name: "tooltip.name_for_member_pages" })).toBeInTheDocument();
    expect(screen.getByText("explainers.list_sellers")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no sellers", async () => {
    serverRows = [];
    renderPage();

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the sellers fail to load", async () => {
    api.listResellers.mockRejectedValue(axiosError(500, { message: "Boom" }));
    renderPage();

    await waitFor(() => expect(api.listResellers).toHaveBeenCalled());
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);
    expect(pageTitle()).toBeInTheDocument();
    expect(addButton()).toBeEnabled();
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = await renderLoaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

// ── Rows ────────────────────────────────────────────────────────────────────

describe("ListSellers rows", () => {
  it("shows each seller's contact details and the name members see", async () => {
    await renderLoaded();

    const gruber = rowOf("Gemüsebau Gruber");
    expect(
      Object.fromEntries(
        [MEMBER_PAGE_NAME, ...CONTACT_TITLES].map((title) => [title, cellOf(gruber, title).textContent]),
      ),
    ).toEqual({
      [MEMBER_PAGE_NAME]: "Gruber's vegetables",
      "resellers.first_name": "Anna",
      "resellers.last_name": "Gruber",
      "resellers.address": "Feldweg 4",
      "resellers.zip_code": "4020",
      "resellers.city": "Linz",
      "resellers.email": "anna@gruber.example",
      "resellers.phone": "+43 732 100",
      "resellers.phone2": "+43 664 200",
    });
  });

  it("ticks the roles and flags each seller has", async () => {
    await renderLoaded();

    const gruber = rowOf("Gemüsebau Gruber");
    expect(flag(gruber, ACTIVE)).toBeChecked();
    expect(flag(gruber, DELIVERY_STATION)).not.toBeChecked();
    expect(flag(gruber, RESELLER)).not.toBeChecked();
    expect(flag(rowOf("Obsthof Maier"), RESELLER)).toBeChecked();
    expect(flag(rowOf("Hofkäserei Berger"), DELIVERY_STATION)).toBeChecked();
  });
});

// ── Filters ─────────────────────────────────────────────────────────────────

describe("ListSellers filters", () => {
  it("hides sellers no longer bought from until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(screen.queryByText("Imkerei Huber")).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);

    await showInactive(user);

    expect(flag(rowOf("Imkerei Huber"), ACTIVE)).not.toBeChecked();
    expect(bodyRows()).toHaveLength(4);
  });

  it("finds sellers by any shown detail", async () => {
    const { user } = await renderLoaded();
    const search = screen.getByRole("searchbox", { name: "table.search_placeholder" });

    await user.type(search, "WELS");

    expect(shownCompanies()).toEqual(["Obsthof Maier"]);

    await user.clear(search);
    await user.type(search, "gruber's");

    expect(shownCompanies()).toEqual(["Gemüsebau Gruber"]);
  });
});

// ── New seller ──────────────────────────────────────────────────────────────

describe("ListSellers new seller", () => {
  it("adds an active seller with the seller role and shows it without reloading", async () => {
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    expect(within(editingRow()).getByRole("checkbox", { name: ACTIVE })).toBeChecked();
    expect(within(editingRow()).getByRole("checkbox", { name: RESELLER })).not.toBeChecked();
    await fillNewSeller(user);
    await typeInto(user, MEMBER_PAGE_NAME, "Lindner's herbs");
    await saveRow(user);

    await waitFor(() => expect(api.createReseller).toHaveBeenCalledTimes(1));
    expect(created()).toMatchObject({
      company_name: "Gärtnerei Lindner",
      address: "Lindenweg 3",
      zip_code: "4400",
      city: "Steyr",
      name_for_member_pages: "Lindner's herbs",
      is_seller: true,
      is_active_seller: true,
    });
    expect(created()).not.toHaveProperty("comes_from_seller_page");
    const lindner = await waitFor(() => rowOf("Gärtnerei Lindner"));
    expect(flag(lindner, ACTIVE)).toBeChecked();
    expect(cellOf(lindner, "resellers.city")).toHaveTextContent("Steyr");
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("adds a seller that is also a reseller when the office ticks it", async () => {
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await fillNewSeller(user);
    await user.click(within(editingRow()).getByRole("checkbox", { name: RESELLER }));
    await saveRow(user);

    await waitFor(() => expect(api.createReseller).toHaveBeenCalledTimes(1));
    expect(created()).toMatchObject({ is_seller: true, is_reseller: true });
    expect(flag(await waitFor(() => rowOf("Gärtnerei Lindner")), RESELLER)).toBeChecked();
  });

  it("refuses a new seller without address, ZIP code and city", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await typeInto(user, COMPANY, "Gärtnerei Lindner");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(3);
    expect(api.createReseller).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new seller and keeps the row open", async () => {
    silenceConsoleErrors();
    const message = "Enter a valid email address.";
    api.createReseller.mockRejectedValue(
      axiosError(400, { code: "validation_error", message, details: { email: [message] } }),
    );
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await fillNewSeller(user);
    await typeInto(user, "resellers.email", "lindner-at-example");
    await saveRow(user);

    expect(await screen.findByText(`resellers.email: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(within(editingRow()).getByLabelText("resellers.email")).toBeInvalid();
    expect(within(editingRow()).getByLabelText(COMPANY)).toHaveValue("Gärtnerei Lindner");
    expect(screen.queryByText("Gärtnerei Lindner")).not.toBeInTheDocument();
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    expect(within(editingRow()).getByLabelText(COMPANY)).toHaveValue("");
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListSellers editing and deleting", () => {
  it("keeps a seller's delivery station ticked while the station is still in use", async () => {
    serverRows = serverRows.map((row) =>
      row.id === BERGER.id ? { ...row, linked_delivery_station_can_be_deleted: false } : row,
    );
    const { user } = await renderLoaded();

    await editRow(user, "Hofkäserei Berger");

    const box = within(cellOf(editingRow(), DELIVERY_STATION)).getByRole("checkbox");
    expect(box).toBeChecked();
    expect(box).toBeDisabled();
  });

  it("lets the office untick a delivery station nobody uses yet, and tick one for a seller without", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Hofkäserei Berger");
    const box = within(cellOf(editingRow(), DELIVERY_STATION)).getByRole("checkbox");
    expect(box).toBeEnabled();
    await user.click(box);
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-berger",
      expect.objectContaining({ is_also_delivery_station: false }),
    );

    await editRow(user, "Gemüsebau Gruber");
    expect(within(cellOf(editingRow(), DELIVERY_STATION)).getByRole("checkbox")).toBeEnabled();
  });

  it("saves a changed seller under its id, keeping its seller role, without reloading", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Hofkäserei Berger");
    await typeInto(user, "resellers.email", "kaese@berger.example");
    await user.click(within(editingRow()).getByRole("checkbox", { name: ACTIVE }));
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-berger",
      expect.objectContaining({
        email: "kaese@berger.example",
        is_active_seller: false,
        is_seller: true,
        company_name: "Hofkäserei Berger",
        city: "Steyr",
      }),
    );
    expect(await screen.findByText("kaese@berger.example")).toBeInTheDocument();
    expect(flag(rowOf("Hofkäserei Berger"), ACTIVE)).not.toBeChecked();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("locks the names of a seller the farm has bought from, and offers no delete", async () => {
    const { user } = await renderLoaded();
    expect(within(rowOf("Gemüsebau Gruber")).queryByRole("button", { name: "table.delete" })).toBeNull();

    await editRow(user, "Gemüsebau Gruber");
    for (const field of [COMPANY, "resellers.first_name", "resellers.last_name"]) {
      expect(within(editingRow()).queryByLabelText(field)).not.toBeInTheDocument();
    }
    await typeInto(user, "resellers.address", "Feldweg 6");
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-gruber",
      expect.objectContaining({
        company_name: "Gemüsebau Gruber", first_name: "Anna", last_name: "Gruber",
        address: "Feldweg 6", is_seller: true,
      }),
    );
    expect(await screen.findByText("Feldweg 6")).toBeInTheDocument();
  });

  it("refuses to save a seller without a city", async () => {
    silenceConsoleErrors();
    const { user } = await renderLoaded();

    await editRow(user, "Hofkäserei Berger");
    await user.clear(within(editingRow()).getByLabelText("resellers.city"));
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(1);
    expect(api.updateReseller).not.toHaveBeenCalled();
  });

  it("removes a seller after confirmation, deleting from the seller page", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Hofkäserei Berger");

    const context = { delete_context: "sellers" };
    await waitFor(() => expect(api.destroyReseller).toHaveBeenCalledWith("res-berger", context));
    await waitFor(() => expect(api.listResellers).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Hofkäserei Berger")).not.toBeInTheDocument();
    expect(screen.getByText("Gemüsebau Gruber")).toBeInTheDocument();
  });

  it("shows why the server refused to delete a seller and keeps it", async () => {
    silenceConsoleErrors();
    api.destroyReseller.mockRejectedValue(
      axiosError(409, { code: "conflict", message: "Database integrity error" }),
    );
    const { user } = await renderLoaded();

    await deleteRow(user, "Hofkäserei Berger");

    expect(await screen.findByText(germanErrors.conflict)).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Hofkäserei Berger")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });
});

// ── Organic certificates ────────────────────────────────────────────────────

describe("ListSellers organic certificates", () => {
  it("leaves out the organic columns on a farm without an organic certificate", async () => {
    await renderLoaded();

    expect(columnTitles()).not.toContain(CONTROL_NUMBER);
    expect(columnTitles()).not.toContain(CERTIFICATES);
    expect(screen.queryByRole("button", { name: MANAGE_CERTIFICATES })).not.toBeInTheDocument();
  });

  it("shows each seller's control number after its company on a certified farm", async () => {
    certifyFarm();
    await renderLoaded();

    const titles = columnTitles();
    expect(titles.slice(titles.indexOf(COMPANY), titles.indexOf(COMPANY) + 4)).toEqual([
      COMPANY, CONTROL_NUMBER, CERTIFICATES, "resellers.first_name",
    ]);
    expect(cellOf(rowOf("Gemüsebau Gruber"), CONTROL_NUMBER)).toHaveTextContent("AT-BIO-301");
    expect(cellOf(rowOf("Hofkäserei Berger"), CONTROL_NUMBER)).toHaveTextContent("");
  });

  it("marks whether a certified seller has a certificate valid today, and offers none to a seller without a control number", async () => {
    certifyFarm();
    await renderLoaded();

    expect(rowButton("Gemüsebau Gruber", MANAGE_CERTIFICATES)).toHaveClass("has-certificate");
    expect(rowButton("Obsthof Maier", MANAGE_CERTIFICATES)).toHaveClass("missing-certificate");
    expect(
      within(rowOf("Hofkäserei Berger")).queryByRole("button", { name: MANAGE_CERTIFICATES }),
    ).not.toBeInTheDocument();
  });

  it("opens the certificates of the seller whose button the office clicks", async () => {
    certifyFarm();
    const { user } = await renderLoaded();
    expect(screen.queryByRole("dialog", { name: "Organic certificates" })).not.toBeInTheDocument();

    await user.click(rowButton("Obsthof Maier", MANAGE_CERTIFICATES));

    expect(screen.getByRole("dialog", { name: "Organic certificates" })).toHaveTextContent(
      "Certificates of Obsthof Maier (res-obsthof)",
    );
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close certificates" }));
    expect(screen.queryByRole("dialog", { name: "Organic certificates" })).not.toBeInTheDocument();

    await user.click(rowButton("Gemüsebau Gruber", MANAGE_CERTIFICATES));

    expect(screen.getByRole("dialog", { name: "Organic certificates" })).toHaveTextContent(
      "Certificates of Gemüsebau Gruber (res-gruber)",
    );
  });

  it.each([
    ["the name members see", { name_for_member_pages: "Lang's eggs" }, "Lang's eggs"],
    ["the contact's name", {}, "Lena Lang"],
  ])(
    "titles the certificates of a seller without a company name by %s",
    async (_label, names, title) => {
      certifyFarm();
      serverRows = [
        ...serverRows,
        seller({
          id: "res-lang", first_name: "Lena", last_name: "Lang", address: "Hofweg 2",
          zip_code: "4020", city: "Linz", organic_control_number: "AT-BIO-555", ...names,
        }),
      ];
      const { user } = await renderLoaded();

      await user.click(rowButton("Lena", MANAGE_CERTIFICATES));

      expect(screen.getByRole("dialog", { name: "Organic certificates" })).toHaveTextContent(
        `Certificates of ${title} (res-lang)`,
      );
    },
  );

  it("offers the certificates of a seller once it is given a control number", async () => {
    certifyFarm();
    const { user } = await renderLoaded();

    await editRow(user, "Hofkäserei Berger");
    await typeInto(user, CONTROL_NUMBER, "AT-BIO-777");
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-berger",
      expect.objectContaining({ organic_control_number: "AT-BIO-777" }),
    );
    const button = await waitFor(() => rowButton("Hofkäserei Berger", MANAGE_CERTIFICATES));
    expect(button).toHaveClass("missing-certificate");
    await user.click(button);
    expect(screen.getByRole("dialog", { name: "Organic certificates" })).toHaveTextContent(
      "Certificates of Hofkäserei Berger (res-berger)",
    );
  });
});

// ── CSV import ──────────────────────────────────────────────────────────────

describe("ListSellers CSV import", () => {
  it("leaves the certificate button column out of the template on a certified farm", async () => {
    certifyFarm();
    tenantState.settings = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "csv_upload.open" }));
    await screen.findByRole("dialog", { name: "csv_upload.import_title" });

    // The columns the template emits, by the rule DownloadCsvTemplateButton applies.
    const emitted = (stubs.template?.columns ?? []).filter(
      (column) =>
        column.importable === true || (column.readOnly !== true && column.disabled !== true),
    );
    expect(emitted.map((column) => column.dataIndex)).toContain("organic_control_number");
    expect(emitted.map((column) => column.dataIndex)).not.toContain("organic_certificates");
  });

  it("offers no CSV import unless the tenant allows uploads", async () => {
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "csv_upload.open" })).not.toBeInTheDocument();
  });

  it("imports sellers from a template of the list's columns and reloads the list", async () => {
    tenantState.settings = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();

    await user.click(screen.getByRole("button", { name: "csv_upload.open" }));

    expect(await screen.findByRole("dialog", { name: "csv_upload.import_title" })).toBeInTheDocument();
    expect(stubs.template).toMatchObject({
      filename: "commissioning.sellers_template.csv",
      modelName: "reseller",
      // The template has no role column, so every imported row is made a
      // seller, or it would land outside this list.
      fixedValues: { is_seller: true },
    });
    expect(stubs.template?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining([
        "is_active_seller", "company_name", "first_name", "last_name", "address", "zip_code", "city", "email",
      ]),
    );

    serverRows = [
      ...serverRows,
      seller({ id: "res-moser", company_name: "Mühle Moser", address: "Mühlweg 1", zip_code: "4020", city: "Linz" }),
    ];
    await user.click(screen.getByRole("button", { name: "Upload the filled-in template" }));

    expect(await screen.findByText("Mühle Moser")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(2);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "csv_upload.import_title" })).not.toBeInTheDocument(),
    );
  });
});

// ── Roles ───────────────────────────────────────────────────────────────────

describe("ListSellers roles", () => {
  it.each([{ roles: ["office"] }, { roles: ["admin"] }])(
    "lets $roles add, edit and delete sellers",
    async ({ roles }) => {
      auth.roles = roles;
      await renderLoaded();

      expect(addButton()).toBeEnabled();
      expect(rowButton("Hofkäserei Berger", "table.edit")).toBeEnabled();
      expect(rowButton("Hofkäserei Berger", "table.delete")).toBeEnabled();
    },
  );

  it.each([{ roles: ["management"] }, { roles: ["staff"] }, { roles: ["gardener"] }])(
    "shows the sellers read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      const { user } = await renderLoaded();

      expect(addButton()).not.toBeInTheDocument();
      expect(columnTitles()).not.toContain("table.actions");
      expect(screen.queryByRole("button", { name: /table\.(edit|delete)/ })).not.toBeInTheDocument();

      await user.click(screen.getByText("Hofkäserei Berger"));
      await user.keyboard("+");

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    },
  );
});
