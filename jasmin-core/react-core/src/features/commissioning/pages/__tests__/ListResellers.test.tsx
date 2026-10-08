/**
 * ListResellers: the office's list of resellers, the businesses the farm
 * delivers to. Rendered through the real useCrudListPage, EditableTable and
 * the contact, note, user-status and offer-group hooks; the generated
 * commissioning and auth clients are the mocking boundary, with the reseller
 * and offer-group list hooks real TanStack queries around spies that answer
 * from an in-memory server. The modals the page opens are stubs that show whom
 * they were opened for and hand the page's callbacks to the test.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OfferGroup, Reseller } from "@shared/api/generated/models";
import i18n from "@shared/i18n";
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
const tenantSettings = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantSettings.values ? tenantSettings.values[key] : defaultValue,
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

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({
  default: notify,
  registerAnnouncer: () => {},
  announcePolite: () => {},
}));

const api = vi.hoisted(() => ({
  listResellers: vi.fn(),
  createReseller: vi.fn(),
  updateReseller: vi.fn(),
  destroyReseller: vi.fn(),
  listOfferGroups: vi.fn(),
  updateLogin: vi.fn(),
  resendInvitation: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const resellersKey = (params?: unknown) => [
    "/api/commissioning/resellers/",
    ...(params ? [params] : []),
  ];
  const offerGroupsKey = () => ["/api/commissioning/offer_groups/"];
  return {
    getCommissioningResellersListQueryKey: resellersKey,
    useCommissioningResellersList: (params?: unknown) =>
      useQuery({ queryKey: resellersKey(params), queryFn: () => api.listResellers(params) }),
    commissioningResellersCreate: (body: unknown) => api.createReseller(body),
    commissioningResellersPartialUpdate: (id: string, body: unknown) =>
      api.updateReseller(id, body),
    commissioningResellersDestroy: (id: string, params: unknown) =>
      api.destroyReseller(id, params),
    getCommissioningOfferGroupsListQueryKey: offerGroupsKey,
    useCommissioningOfferGroupsList: () =>
      useQuery({ queryKey: offerGroupsKey(), queryFn: () => api.listOfferGroups() }),
  };
});

vi.mock("@shared/api/generated/auth/auth", () => ({
  authAdminUsersPartialUpdate: (id: string, body: unknown) => api.updateLogin(id, body),
  authAdminUsersResendInvitationCreate: (id: string) => api.resendInvitation(id),
}));

type Row = Record<string, unknown>;
type RowAction = ((record: Row) => void) | undefined;
type LoginInfo = { account_status?: string; is_invitation_expired?: boolean };
type UserInfoModalStubProps = {
  isOpen: boolean;
  onClose: () => void;
  record: Row | null;
  extra?: React.ReactNode;
} & Partial<Record<"onSendInvitation" | "onResendInvitation" | "onActivateUser" | "onDeactivateUser", RowAction>>;
type InviteUserModalStubProps = { open: boolean; onCreated?: () => void } & Row;
type ExportCsvStubProps = {
  open: boolean;
  onClose: () => void;
  columns: { dataIndex?: string }[];
  data: Row[];
  filename?: string;
};
type CsvImportButtonStubProps = {
  uploadAllowed: boolean;
  modelName: string;
  fixedValues?: Row;
  onUploadSuccess?: () => void;
};
type InvoiceSettingsStubProps = {
  open: boolean;
  reseller: Reseller | null;
  onClose: () => void;
  onSaved: (updated: Reseller) => void;
};

// The props each stubbed child got on its last render.
const stubs = vi.hoisted(() => ({
  invite: null as InviteUserModalStubProps | null,
  exportCsv: null as ExportCsvStubProps | null,
  csvImport: null as CsvImportButtonStubProps | null,
}));

vi.mock("@shared/modals", () => ({
  UserInfoModal: ({ isOpen, onClose, record, extra, ...actions }: UserInfoModalStubProps) => {
    if (!isOpen || !record) return null;
    const login = record.linked_user_info as LoginInfo | null;
    const expiry = login?.is_invitation_expired ? ", expired" : "";
    const buttons: [string, RowAction][] = [
      ["Send invitation", actions.onSendInvitation],
      ["Resend invitation", actions.onResendInvitation],
      ["Activate login", actions.onActivateUser],
      ["Deactivate login", actions.onDeactivateUser],
    ];
    return (
      <div data-testid="user-info-modal">
        <p>{`Login of ${String(record.company_name)}`}</p>
        <p>{login ? `${login.account_status}${expiry}` : "no login"}</p>
        {buttons.map(([label, action]) => (
          <button key={label} type="button" onClick={() => action?.(record)}>
            {label}
          </button>
        ))}
        <button type="button" onClick={onClose}>Close login</button>
        {extra}
      </div>
    );
  },
  InviteUserModal: (props: InviteUserModalStubProps) => {
    stubs.invite = props;
    return props.open ? (
      <div data-testid="invite-user-modal">
        <button type="button" onClick={() => props.onCreated?.()}>Invite</button>
      </div>
    ) : null;
  },
  CsvImportButton: (props: CsvImportButtonStubProps) => {
    stubs.csvImport = props;
    return props.uploadAllowed ? (
      <button type="button" onClick={() => props.onUploadSuccess?.()}>Import resellers</button>
    ) : null;
  },
}));

vi.mock("@features/commissioning/modals", () => ({
  ExportCsv: (props: ExportCsvStubProps) => {
    stubs.exportCsv = props;
    return props.open ? (
      <div data-testid="export-csv-modal">
        <button type="button" onClick={props.onClose}>Close export</button>
      </div>
    ) : null;
  },
}));

// The changes the stubbed invoice settings modal saves through the generated
// client before handing the server's answer back, as the real modal does.
const invoiceSettings = vi.hoisted(() => ({ changes: {} as Row }));
vi.mock("@features/commissioning/modals/ResellerInvoiceSettingsModal", () => ({
  ResellerInvoiceSettingsModal: ({ open, reseller, onClose, onSaved }: InvoiceSettingsStubProps) =>
    open && reseller ? (
      <div data-testid="invoice-settings-modal">
        <p>{`Invoice settings of ${reseller.company_name}`}</p>
        <button
          type="button"
          onClick={async () => {
            const id = String(reseller.id);
            onSaved((await api.updateReseller(id, invoiceSettings.changes)) as Reseller);
            onClose();
          }}
        >
          Save invoice settings
        </button>
      </div>
    ) : null,
}));

vi.mock("@features/members/components/GdprSubjectActions", () => ({
  ResellerDataProtection: ({ reseller }: { reseller: Row | null }) => (
    <p>{`Data protection of ${String(reseller?.id)}`}</p>
  ),
}));

import ListResellers from "../ListResellers";
import {
  BIOMARKT, CAFE, HOFLADEN, KANTINE, STANDARD, WHOLESALE, login, reseller,
} from "./listResellers.fixtures";

// ── Fixtures ────────────────────────────────────────────────────────────────

// What the server currently holds; the list requests answer from it.
let serverResellers: Reseller[] = [];
let serverOfferGroups: OfferGroup[] = [];

const loginOf = (row: Reseller) => row.linked_user_info as (Row & { id?: string }) | null;

/** Changes a login on the server and answers with it, as the admin-user
 *  endpoints do. */
function changeLogin(userId: string, changes: Row): Row {
  const owner = serverResellers.find((row) => loginOf(row)?.id === userId);
  if (!owner) throw new Error(`No login ${userId}`);
  const updated = { ...loginOf(owner), ...changes };
  serverResellers = serverResellers.map((row) =>
    row === owner ? { ...row, linked_user_info: updated } : row,
  );
  return updated;
}

/** A rejected request as axios hands it over, carrying the server's body. */
function axiosError(status: number, data: Row) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });
}

beforeEach(() => {
  auth.roles = ["office"];
  tenantSettings.values = {};
  invoiceSettings.changes = {};
  Object.assign(stubs, { invite: null, exportCsv: null, csvImport: null });
  serverResellers = [HOFLADEN, BIOMARKT, CAFE, KANTINE];
  serverOfferGroups = [STANDARD, WHOLESALE];
  notify.success.mockReset();
  notify.error.mockReset();
  api.listResellers.mockReset().mockImplementation(async () => [...serverResellers]);
  api.listOfferGroups.mockReset().mockImplementation(async () => [...serverOfferGroups]);
  api.createReseller.mockReset().mockImplementation(async (payload: Row) => {
    const saved = { ...payload, id: "res-new", linked_user_info: null, can_be_deleted: true };
    serverResellers = [...serverResellers, saved as Reseller];
    return saved;
  });
  api.updateReseller.mockReset().mockImplementation(async (id: string, payload: Row) => {
    const current = serverResellers.find((row) => row.id === id);
    if (!current) throw new Error(`No reseller ${id}`);
    const saved = { ...current, ...payload, id } as Reseller;
    serverResellers = serverResellers.map((row) => (row.id === id ? saved : row));
    return saved;
  });
  api.destroyReseller.mockReset().mockImplementation(async (id: string) => {
    serverResellers = serverResellers.filter((row) => row.id !== id);
  });
  api.updateLogin.mockReset().mockImplementation(async (userId: string, body: Row) =>
    changeLogin(userId, { ...body, is_active: body.account_status === "active" }),
  );
  api.resendInvitation.mockReset().mockImplementation(async (userId: string) =>
    changeLogin(userId, { account_status: "pending_invitation", is_invitation_expired: false }),
  );
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const user = userEvent.setup();
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{profiler.wrap(<ListResellers />)}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { user, profiler };
}

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

/** Renders the page and waits until the resellers show their offer groups. */
async function renderLoaded() {
  const rendered = renderPage();
  await screen.findByText("Hofladen Gruber");
  await within(rowOf("Hofladen Gruber")).findByText("Standard");
  return rendered;
}

/** The row being edited inline — the one offering a save button. */
function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
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

const rowButton = (text: string, name: string) =>
  within(rowOf(text)).getByRole("button", { name });
const ordersLink = (company: string) => within(rowOf(company)).getByRole("link", { name: "resellers.go_to_orders" });
const statusButton = (company: string) =>
  within(cellOf(rowOf(company), "members.user_status")).getByRole("button");
const addButton = () => screen.queryByRole("button", { name: /table\.add_plus_icon/ });
// AntD's Spin turns itself off in an effect, a render after the rows arrive,
// so a test waits for it to go.
const spinner = () => document.querySelector(".ant-spin-spinning");
const pageTitle = () => screen.getByRole("heading", { level: 1, name: "resellers.list_resellers" });

/** A checkbox of the row being edited, by its column title. */
const editCheckbox = (name: string) => within(editingRow()).queryByRole("checkbox", { name });

type User = ReturnType<typeof userEvent.setup>;
const editRow = (user: User, company: string) => user.click(rowButton(company, "table.edit"));
const saveRow = (user: User) => user.click(screen.getByRole("button", { name: "table.save" }));

async function deleteRow(user: User, company: string) {
  await user.click(rowButton(company, "table.delete"));
  await user.click(await screen.findByRole("button", { name: "table.yes" }));
}

async function typeInto(user: User, label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await user.clear(input);
  await user.type(input, text);
}

/** Fills the new row with a reseller the table accepts. */
async function fillNewReseller(user: User) {
  await typeInto(user, "resellers.company_name", "Gasthaus Linde");
  await typeInto(user, "resellers.address", "Lindenweg 3");
  await typeInto(user, "resellers.zip_code", "4400");
  await typeInto(user, "resellers.city", "Steyr");
}

// ── Loading and layout ──────────────────────────────────────────────────────

describe("ListResellers loading and layout", () => {
  it("loads the resellers with one request scoped to resellers", async () => {
    renderPage();

    expect(await screen.findByText("Hofladen Gruber")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
    expect(api.listResellers).toHaveBeenCalledWith({ is_reseller: true });
    expect(api.listOfferGroups).toHaveBeenCalledTimes(1);
  });

  it("shows a spinner over the table while the resellers load", async () => {
    let deliver: (rows: Reseller[]) => void = () => {};
    api.listResellers.mockImplementation(() => new Promise((resolve) => (deliver = resolve)));
    renderPage();

    expect(spinner()).toBeInTheDocument();

    deliver([HOFLADEN]);

    expect(await screen.findByText("Hofladen Gruber")).toBeInTheDocument();
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("shows the title, the columns in order and the explainer", async () => {
    await renderLoaded();

    expect(pageTitle()).toBeInTheDocument();
    expect(columnTitles()).toEqual([
      "table.actions", "Link", "", "resellers.is_active", "members.user_status",
      "resellers.is_also_delivery_station", "resellers.is_seller", "resellers.company_name",
      "resellers.first_name", "resellers.last_name", "resellers.address", "resellers.zip_code",
      "resellers.city", "resellers.email", "resellers.phone", "resellers.phone2",
      "resellers.offer_group", "resellers.offer_via_email", "resellers.delivery_note_via_email",
      "commissioning.note",
    ]);
    expect(screen.getByText("explainers.list_resellers")).toBeInTheDocument();
  });

  it("shows a hint instead of rows when there are no resellers", async () => {
    serverResellers = [];
    renderPage();

    expect(await screen.findByText("table.no_data")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(0);
    expect(addButton()).toBeEnabled();
  });

  it("keeps the page usable when the resellers fail to load", async () => {
    api.listResellers.mockRejectedValue(axiosError(500, { message: "Boom" }));
    renderPage();

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

// ── Columns ─────────────────────────────────────────────────────────────────

describe("ListResellers columns", () => {
  it("shows each reseller's contact details, note and offer group by name", async () => {
    await renderLoaded();

    const hofladen = rowOf("Hofladen Gruber");
    for (const text of [
      "Anna", "Gruber", "Dorfstraße 1", "4020", "Linz", "hofladen@example.com",
      "+43 732 100", "Delivery on Mondays", "Standard",
    ]) {
      expect(within(hofladen).getByText(text)).toBeInTheDocument();
    }
    expect(within(rowOf("Biomarkt Sonnenschein")).getByText("Wholesale")).toBeInTheDocument();
  });

  it("ticks the flags each reseller has set", async () => {
    await renderLoaded();

    const hofladen = rowOf("Hofladen Gruber");
    expect(flag(hofladen, "resellers.is_active")).toBeChecked();
    expect(flag(hofladen, "resellers.is_seller")).toBeChecked();
    expect(flag(hofladen, "resellers.is_also_delivery_station")).not.toBeChecked();
    expect(flag(hofladen, "resellers.offer_via_email")).toBeChecked();
    expect(flag(hofladen, "resellers.delivery_note_via_email")).toBeChecked();
    const biomarkt = rowOf("Biomarkt Sonnenschein");
    expect(flag(biomarkt, "resellers.is_seller")).not.toBeChecked();
    expect(flag(biomarkt, "resellers.is_also_delivery_station")).toBeChecked();
    expect(flag(biomarkt, "resellers.offer_via_email")).not.toBeChecked();
  });

  it("links each reseller to its orders and shows the state of its login", async () => {
    const { user } = await renderLoaded();

    expect(ordersLink("Hofladen Gruber")).toHaveAttribute("href", "/commissioning/customer-orders/res-hofladen");
    expect(ordersLink("Biomarkt Sonnenschein")).toHaveAttribute("href", "/commissioning/customer-orders/res-biomarkt");
    expect(statusButton("Hofladen Gruber")).toHaveAccessibleName("button_library.user_active");
    expect(statusButton("Biomarkt Sonnenschein")).toHaveAccessibleName("button_library.user_not_invited");
    expect(statusButton("Café Zentral")).toHaveAccessibleName("button_library.user_pending_invitation");
    await user.click(screen.getByText("commissioning.hide_inactive"));
    expect(statusButton("Kantine Nord")).toHaveAccessibleName("button_library.user_inactive");
  });

  it("leaves out the offer group column when the tenant has no offer groups", async () => {
    serverOfferGroups = [];
    renderPage();
    await screen.findByText("Hofladen Gruber");
    await waitFor(() => expect(api.listOfferGroups).toHaveBeenCalled());
    await flushMicrotasks();

    expect(columnTitles()).not.toContain("resellers.offer_group");
    expect(columnTitles()).toContain("resellers.offer_via_email");
  });
});

// ── Filters ─────────────────────────────────────────────────────────────────

describe("ListResellers filters", () => {
  it("hides inactive resellers until asked to show them", async () => {
    const { user } = await renderLoaded();

    expect(screen.queryByText("Kantine Nord")).not.toBeInTheDocument();
    expect(bodyRows()).toHaveLength(3);

    await user.click(screen.getByText("commissioning.hide_inactive"));

    expect(flag(rowOf("Kantine Nord"), "resellers.is_active")).not.toBeChecked();
    expect(bodyRows()).toHaveLength(4);
  });

  it("finds resellers by any shown detail, the offer group's name included", async () => {
    const { user } = await renderLoaded();
    const search = screen.getByRole("searchbox", { name: "table.search_placeholder" });

    await user.type(search, "LINZ");

    expect(screen.getByText("Hofladen Gruber")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(1);

    await user.clear(search);
    await user.type(search, "wholesale");

    expect(screen.getByText("Biomarkt Sonnenschein")).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(1);
  });
});

// ── New reseller ────────────────────────────────────────────────────────────

describe("ListResellers new reseller", () => {
  it("adds a reseller with the tenant's payment terms and the default offer group", async () => {
    const discount = { early_payment_discount_percent: "2.00", early_payment_discount_days: 10 };
    tenantSettings.values = { payment_terms_reseller_in_days: 30, ...discount };
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    const draft = editingRow();
    expect(within(draft).getByText("Standard")).toBeInTheDocument();
    const invoiceSettingsButton = { name: "resellers.invoice_settings_title" };
    expect(within(draft).queryByRole("button", invoiceSettingsButton)).not.toBeInTheDocument();
    expect(within(draft).queryByRole("link")).not.toBeInTheDocument();
    expect(within(cellOf(draft, "members.user_status")).queryByRole("button")).not.toBeInTheDocument();
    await fillNewReseller(user);
    await saveRow(user);

    await waitFor(() => expect(api.createReseller).toHaveBeenCalledTimes(1));
    expect(api.createReseller).toHaveBeenCalledWith(
      expect.objectContaining({
        company_name: "Gasthaus Linde", address: "Lindenweg 3", zip_code: "4400", city: "Steyr",
        is_reseller: true, is_active_reseller: true, is_seller: false, offer_group: "og-standard",
        is_also_delivery_station: false, payment_terms_in_days: 30,
        early_payment_discount_percent: "2.00", early_payment_discount_days: 10,
      }),
    );
    await screen.findByText("Gasthaus Linde");
    expect(within(rowOf("Gasthaus Linde")).getByText("Standard")).toBeInTheDocument();
    expect(statusButton("Gasthaus Linde")).toHaveAccessibleName("button_library.user_not_invited");
    expect(ordersLink("Gasthaus Linde")).toHaveAttribute("href", "/commissioning/customer-orders/res-new");
    await user.click(rowButton("Gasthaus Linde", "resellers.invoice_settings_title"));
    expect(screen.getByText("Invoice settings of Gasthaus Linde")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("falls back to 14 days' payment terms and lets the office pick another offer group", async () => {
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await user.click(within(editingRow()).getByRole("combobox", { name: "resellers.offer_group" }));
    await user.click(await screen.findByTitle("Wholesale"));
    await fillNewReseller(user);
    await saveRow(user);

    await waitFor(() => expect(api.createReseller).toHaveBeenCalledTimes(1));
    expect(api.createReseller).toHaveBeenCalledWith(
      expect.objectContaining({ offer_group: "og-wholesale", payment_terms_in_days: 14 }),
    );
    expect(within(rowOf("Gasthaus Linde")).getByText("Wholesale")).toBeInTheDocument();
  });

  it("refuses a new reseller without address, ZIP code and city", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await typeInto(user, "resellers.company_name", "Gasthaus Linde");
    await saveRow(user);

    expect(await screen.findByText("table.save_failed_generic — table.save_failed_hint")).toBeVisible();
    expect(within(editingRow()).getAllByText("table.required")).toHaveLength(3);
    expect(api.createReseller).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses a new reseller", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const message = "Enter a valid email address.";
    api.createReseller.mockRejectedValue(
      axiosError(400, { code: "validation_error", message, details: { email: [message] } }),
    );
    const { user } = await renderLoaded();

    await user.click(addButton()!);
    await fillNewReseller(user);
    await typeInto(user, "resellers.email", "linde-at-example");
    await saveRow(user);

    expect(await screen.findByText(`resellers.email: ${message} — table.save_failed_hint`)).toBeVisible();
    expect(within(editingRow()).getByLabelText("resellers.email")).toBeInvalid();
    expect(screen.queryByText("Gasthaus Linde")).not.toBeInTheDocument();
  });

  it("opens a new row with the + key", async () => {
    const { user } = await renderLoaded();

    await user.keyboard("+");

    expect(within(editingRow()).getByLabelText("resellers.company_name")).toHaveValue("");
    expect(bodyRows()).toHaveLength(4);
  });
});

// ── Editing and deleting ────────────────────────────────────────────────────

describe("ListResellers editing and deleting", () => {
  it("saves a changed reseller under its id and keeps it in view without reloading", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Biomarkt Sonnenschein");
    await typeInto(user, "resellers.email", "bestellung@biomarkt.example");
    await user.click(editCheckbox("resellers.is_active")!);
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-biomarkt",
      expect.objectContaining({
        email: "bestellung@biomarkt.example", is_active_reseller: false, is_reseller: true,
        company_name: "Biomarkt Sonnenschein", city: "Wels", offer_group: "og-wholesale",
      }),
    );
    expect(await screen.findByText("bestellung@biomarkt.example")).toBeInTheDocument();
    expect(flag(rowOf("Biomarkt Sonnenschein"), "resellers.is_active")).not.toBeChecked();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("locks the name and address of a reseller that already has orders, and offers no delete", async () => {
    const { user } = await renderLoaded();
    expect(within(rowOf("Hofladen Gruber")).queryByRole("button", { name: "table.delete" })).toBeNull();

    await editRow(user, "Hofladen Gruber");
    for (const field of ["company_name", "first_name", "last_name", "address", "zip_code", "city"]) {
      expect(within(editingRow()).queryByLabelText(`resellers.${field}`)).not.toBeInTheDocument();
    }
    await typeInto(user, "commissioning.note", "Delivery on Tuesdays");
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller).toHaveBeenCalledWith(
      "res-hofladen",
      expect.objectContaining({
        company_name: "Hofladen Gruber", first_name: "Anna", last_name: "Gruber",
        address: "Dorfstraße 1", zip_code: "4020", city: "Linz", note: "Delivery on Tuesdays",
      }),
    );
  });

  it("keeps the delivery station of a reseller while the station is in use", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Biomarkt Sonnenschein");

    expect(editCheckbox("resellers.is_also_delivery_station")).not.toBeInTheDocument();
    expect(flag(editingRow(), "resellers.is_also_delivery_station")).toBeChecked();
    await saveRow(user);
    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller.mock.calls[0]).toEqual([
      "res-biomarkt",
      expect.objectContaining({ is_also_delivery_station: true }),
    ]);
  });

  it("lets the office drop a delivery station nobody collects from yet", async () => {
    const { user } = await renderLoaded();

    await editRow(user, "Café Zentral");
    const station = editCheckbox("resellers.is_also_delivery_station")!;
    expect(station).toBeChecked();
    await user.click(station);
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(1));
    expect(api.updateReseller.mock.calls[0]).toEqual([
      "res-cafe",
      expect.objectContaining({ is_also_delivery_station: false }),
    ]);
  });

  it("removes a reseller after confirmation, dropping only its reseller role", async () => {
    const { user } = await renderLoaded();

    await deleteRow(user, "Biomarkt Sonnenschein");

    const context = { delete_context: "resellers" };
    await waitFor(() => expect(api.destroyReseller).toHaveBeenCalledWith("res-biomarkt", context));
    await waitFor(() => expect(api.listResellers).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Biomarkt Sonnenschein")).not.toBeInTheDocument();
    expect(screen.getByText("Hofladen Gruber")).toBeInTheDocument();
  });

  it("shows why the server refused to delete a reseller", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const details = { station: "Biomarkt Sonnenschein", delivery_count: 12 };
    const message = "The delivery station still has deliveries.";
    api.destroyReseller.mockRejectedValue(
      axiosError(409, { code: "delivery_station.in_use", message, details }),
    );
    const { user } = await renderLoaded();

    await deleteRow(user, "Biomarkt Sonnenschein");

    expect(await screen.findByText(i18n.t("errors.delivery_station.in_use"))).toBeVisible();
    expect(screen.getByText("table.delete_failed_title")).toBeInTheDocument();
    expect(screen.getByText("Biomarkt Sonnenschein")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });
});

// ── Row actions ─────────────────────────────────────────────────────────────

describe("ListResellers row actions", () => {
  it("opens the invoice settings of the row's reseller and keeps what they save for its next edit", async () => {
    const invoiceEmail = "rechnung@biomarkt.example";
    invoiceSettings.changes = { payment_terms_in_days: 30, invoice_via_email: true, invoice_email: invoiceEmail };
    const { user } = await renderLoaded();

    await user.click(rowButton("Biomarkt Sonnenschein", "resellers.invoice_settings_title"));
    expect(screen.getByTestId("invoice-settings-modal")).toHaveTextContent(
      "Invoice settings of Biomarkt Sonnenschein",
    );
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save invoice settings" }));
    await waitFor(() => expect(screen.queryByTestId("invoice-settings-modal")).toBeNull());

    await editRow(user, "Biomarkt Sonnenschein");
    await typeInto(user, "commissioning.note", "Ring twice");
    await saveRow(user);

    await waitFor(() => expect(api.updateReseller).toHaveBeenCalledTimes(2));
    expect(api.updateReseller).toHaveBeenLastCalledWith(
      "res-biomarkt",
      expect.objectContaining({ note: "Ring twice", ...invoiceSettings.changes }),
    );
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("opens the login details of the reseller whose status was clicked", async () => {
    const { user } = await renderLoaded();

    await user.click(statusButton("Hofladen Gruber"));

    const modal = screen.getByTestId("user-info-modal");
    expect(within(modal).getByText("Login of Hofladen Gruber")).toBeInTheDocument();
    expect(within(modal).getByText("active")).toBeInTheDocument();
    expect(within(modal).getByText("Data protection of res-hofladen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close login" }));

    expect(screen.queryByTestId("user-info-modal")).not.toBeInTheDocument();
  });

  it("invites a contact of a reseller without a login as its customer", async () => {
    const { user } = await renderLoaded();

    await user.click(statusButton("Biomarkt Sonnenschein"));
    await user.click(screen.getByRole("button", { name: "Send invitation" }));

    expect(screen.queryByTestId("user-info-modal")).not.toBeInTheDocument();
    expect(screen.getByTestId("invite-user-modal")).toBeInTheDocument();
    const customer = ["customer"];
    expect(stubs.invite).toMatchObject({
      title: "users.invite_title",
      defaultRoles: customer,
      lockedRoles: customer,
      allowedRoles: customer,
      initialValues: { first_name: "Ben", last_name: "Huber", reseller_id: "res-biomarkt" },
    });
    expect(stubs.invite?.initialValues).toHaveProperty("email", "einkauf@biomarkt.example");

    // The server binds the invited login to the reseller.
    const invited = login({ id: "user-ben", account_status: "pending_invitation" });
    serverResellers = serverResellers.map((row) =>
      row.id === "res-biomarkt" ? { ...row, linked_user_info: invited } : row,
    );
    await user.click(screen.getByRole("button", { name: "Invite" }));

    expect(screen.queryByTestId("invite-user-modal")).not.toBeInTheDocument();
    await waitFor(() => expect(api.listResellers).toHaveBeenCalledTimes(2));
    const pending = "button_library.user_pending_invitation";
    await waitFor(() => expect(statusButton("Biomarkt Sonnenschein")).toHaveAccessibleName(pending));
  });

  it.each([
    ["deactivates", "Deactivate login", "Hofladen Gruber", "user-anna", "inactive", "users.deactivated"],
    ["reactivates", "Activate login", "Kantine Nord", "user-dora", "active", "users.activated"],
  ])(
    "%s a reseller's login and shows its new status without reloading the list",
    async (_verb, action, company, userId, accountStatus, message) => {
      const { user } = await renderLoaded();
      await user.click(screen.getByText("commissioning.hide_inactive"));

      await user.click(statusButton(company));
      await user.click(screen.getByRole("button", { name: action }));

      await waitFor(() => expect(notify.success).toHaveBeenCalledWith(message));
      expect(api.updateLogin).toHaveBeenCalledWith(userId, { account_status: accountStatus });
      expect(screen.queryByTestId("user-info-modal")).not.toBeInTheDocument();
      await waitFor(() =>
        expect(statusButton(company)).toHaveAccessibleName(`button_library.user_${accountStatus}`),
      );
      expect(api.listResellers).toHaveBeenCalledTimes(1);
    },
  );

  it("resends an expired invitation and hands on the renewed one", async () => {
    const invitation = { account_status: "pending_invitation", is_invitation_expired: true };
    const expired = login({ id: "user-clara", ...invitation });
    serverResellers = [HOFLADEN, { ...CAFE, linked_user_info: expired }];
    const { user } = await renderLoaded();
    expect(statusButton("Café Zentral")).toHaveAccessibleName("button_library.user_pending_invitation_expired");
    await user.click(statusButton("Café Zentral"));
    expect(screen.getByText("pending_invitation, expired")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Resend invitation" }));

    await waitFor(() => expect(notify.success).toHaveBeenCalledWith("users.invitation_resent"));
    expect(api.resendInvitation).toHaveBeenCalledWith("user-clara");
    expect(screen.queryByTestId("user-info-modal")).not.toBeInTheDocument();

    await user.click(statusButton("Café Zentral"));

    expect(within(screen.getByTestId("user-info-modal")).getByText("pending_invitation")).toBeVisible();
    expect(api.listResellers).toHaveBeenCalledTimes(1);
  });

  it("reports a refused status change and leaves the login as it was", async () => {
    const message = "This login can't be changed right now.";
    api.updateLogin.mockRejectedValue(axiosError(400, { message }));
    const { user } = await renderLoaded();

    await user.click(statusButton("Hofladen Gruber"));
    await user.click(screen.getByRole("button", { name: "Deactivate login" }));

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith(message));
    expect(notify.success).not.toHaveBeenCalled();
    expect(screen.getByTestId("user-info-modal")).toBeInTheDocument();
    expect(statusButton("Hofladen Gruber")).toHaveAccessibleName("button_library.user_active");
  });

  it.each([
    ["the server's reason", { message: "Mail server down" }, "Mail server down"],
    ["its own message without one", {}, "users.resend_failed"],
  ])("reports a failed resend with %s and keeps the login details open", async (_, body, shown) => {
    api.resendInvitation.mockRejectedValue(axiosError(503, body));
    const { user } = await renderLoaded();
    await user.click(statusButton("Café Zentral"));
    await user.click(screen.getByRole("button", { name: "Resend invitation" }));
    await waitFor(() => expect(notify.error).toHaveBeenCalledWith(shown));
    expect(notify.success).not.toHaveBeenCalled();
    expect(screen.getByTestId("user-info-modal")).toBeInTheDocument();
  });
});

// ── CSV ─────────────────────────────────────────────────────────────────────

describe("ListResellers CSV", () => {
  it("exports every reseller, inactive ones included, under the list's name", async () => {
    const { user } = await renderLoaded();
    expect(screen.queryByTestId("export-csv-modal")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /commissioning\.csv_export_resellers/ }));

    expect(screen.getByTestId("export-csv-modal")).toBeInTheDocument();
    expect(stubs.exportCsv?.filename).toBe("resellers.list_resellers");
    expect(stubs.exportCsv?.data.map((row) => `${row.id}: ${row.offer_group_name}`)).toEqual([
      "res-hofladen: Standard", "res-biomarkt: Wholesale", "res-cafe: Standard", "res-kantine: Standard",
    ]);
    expect(stubs.exportCsv?.columns.map((column) => column.dataIndex)).toEqual(
      expect.arrayContaining([
        "company_name", "first_name", "last_name", "address", "zip_code", "city",
        "email", "phone", "note",
      ]),
    );

    await user.click(screen.getByRole("button", { name: "Close export" }));

    expect(screen.queryByTestId("export-csv-modal")).not.toBeInTheDocument();
  });

  it("offers no CSV import unless the tenant allows uploads", async () => {
    await renderLoaded();

    expect(screen.queryByRole("button", { name: "Import resellers" })).not.toBeInTheDocument();
  });

  it("imports resellers from a CSV and reloads the list", async () => {
    tenantSettings.values = { allow_upload_for_data_lists: true };
    const { user } = await renderLoaded();
    expect(stubs.csvImport?.modelName).toBe("reseller");
    // The template has no role column, so every imported row is made a
    // reseller, or it would land outside this list.
    expect(stubs.csvImport?.fixedValues).toEqual({ is_reseller: true });

    serverResellers = [
      ...serverResellers,
      reseller({ id: "res-moser", company_name: "Bäckerei Moser", city: "Linz" }),
    ];
    await user.click(screen.getByRole("button", { name: "Import resellers" }));

    expect(await screen.findByText("Bäckerei Moser")).toBeInTheDocument();
    expect(api.listResellers).toHaveBeenCalledTimes(2);
  });
});

// ── Role gating ─────────────────────────────────────────────────────────────

describe("ListResellers role gating", () => {
  it.each([{ roles: ["office"] }, { roles: ["admin"] }])(
    "lets $roles add, edit and delete resellers",
    async ({ roles }) => {
      auth.roles = roles;
      await renderLoaded();

      expect(addButton()).toBeEnabled();
      expect(rowButton("Biomarkt Sonnenschein", "table.edit")).toBeEnabled();
      expect(rowButton("Biomarkt Sonnenschein", "table.delete")).toBeEnabled();
    },
  );

  it.each([{ roles: ["management"] }, { roles: ["staff"] }])(
    "shows the resellers read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      const { user } = await renderLoaded();

      expect(addButton()).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.delete" })).not.toBeInTheDocument();
      for (const editButton of screen.queryAllByRole("button", { name: "table.edit" })) {
        expect(editButton).toBeDisabled();
      }

      await user.click(screen.getByText("Biomarkt Sonnenschein"));
      await user.keyboard("+");

      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
    },
  );
});
