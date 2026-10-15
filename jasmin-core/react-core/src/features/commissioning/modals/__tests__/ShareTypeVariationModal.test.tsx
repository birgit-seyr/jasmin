/**
 * ShareTypeVariationModal: the sizes a share type comes in — each a
 * time-bound variation with its sort order, capacity, crate, description,
 * picture, prices and (for virtual variations) components. Rendered with the
 * real EditableTable, date pickers, column hooks and rich-text editor; the
 * generated client is the mocking boundary, answering from an in-memory
 * server that closes a size's open variation when a later one is added, as
 * the backend's succession does. The price and component modals are stubs.
 *
 * The clock is frozen on Monday 5 October 2026. Refusals that take the
 * backend's words show their error code here.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// The canonical mock, with one `t` for every render as react-i18next keeps it:
// the description editor re-validates whenever `t` changes.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("react-quill-new", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (content: string) => void;
  }) => (
    <textarea
      aria-label="Description text"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
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

const notify = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  validationError: vi.fn(),
}));
vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify,
}));

vi.mock("@shared/utils/apiError", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils/apiError")>()),
  messageForErrorCode: (code: string) => `errors.${code}`,
}));

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  destroy: vi.fn(),
  shareType: vi.fn(),
  crates: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const listKey = (params?: unknown) => [
    "/api/commissioning/share_type_variations/",
    ...(params ? [params] : []),
  ];
  return {
    getCommissioningShareTypeVariationsListQueryKey: listKey,
    useCommissioningShareTypeVariationsList: (
      params: unknown,
      options?: { query?: { enabled?: boolean } },
    ) =>
      useQuery({
        queryKey: listKey(params),
        queryFn: () => api.list(params),
        enabled: options?.query?.enabled,
      }),
    commissioningShareTypeVariationsCreate: (data: unknown) => api.create(data),
    commissioningShareTypeVariationsPartialUpdate: (
      id: string,
      data: unknown,
    ) => api.update(id, data),
    commissioningShareTypeVariationsDestroy: (id: string) => api.destroy(id),
    getCommissioningShareTypesRetrieveQueryOptions: (id: string) => ({
      queryKey: ["/api/commissioning/share_types/", id],
      queryFn: () => api.shareType(id),
    }),
    useCommissioningCratesList: (params: unknown) =>
      useQuery({
        queryKey: ["/api/commissioning/crates/", params],
        queryFn: () => api.crates(params),
      }),
  };
});

vi.mock(
  "@features/commissioning/modals/prices/ShareTypeVariationPriceModal",
  () => ({
    default: (props: {
      visible: boolean;
      share_type_variation: string | null;
    }) =>
      props.visible ? (
        <div data-testid="price-modal">{props.share_type_variation}</div>
      ) : null,
  }),
);

vi.mock("../VirtualComponentModal", () => ({
  default: (props: {
    visible: boolean;
    share_type_variation: string | number | null;
  }) =>
    props.visible ? (
      <div data-testid="components-modal">{props.share_type_variation}</div>
    ) : null,
}));

import ShareTypeVariationModal from "../ShareTypeVariationModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 5, 12, 0);

type Variation = Record<string, unknown> & { id: string };

function variation(overrides: Partial<Variation> & { id: string }): Variation {
  return {
    share_type: "st-veg",
    variation_type: "physical",
    size: "M",
    sort_order: 2,
    valid_from: "2026-01-05",
    valid_until: null,
    capacity: 100,
    average_weight: "2.500",
    used_crate: "crate-euro",
    used_crate_name: "Euro",
    description: "",
    picture: null,
    can_be_deleted: true,
    subscriptions_valid_until_max: null,
    has_open_ended_subscription: false,
    ...overrides,
  };
}

// M runs all year and is in use.
const MEDIUM = variation({
  id: "v-m",
  can_be_deleted: false,
  description: "<p>Medium box</p>",
});
// S ran until next week and comes back a week after that.
const SMALL_SPRING = variation({
  id: "v-s-spring",
  size: "S",
  sort_order: 1,
  valid_until: "2026-10-11",
  capacity: 60,
  can_be_deleted: false,
});
const SMALL_AUTUMN = variation({
  id: "v-s-autumn",
  size: "S",
  sort_order: 1,
  valid_from: "2026-10-19",
  capacity: 50,
});
// L ended last year.
const LARGE_OLD = variation({
  id: "v-l-2025",
  size: "L",
  sort_order: 3,
  valid_from: "2025-01-06",
  valid_until: "2025-12-28",
  capacity: 40,
});

let serverRows: Variation[] = [];

const dayBefore = (isoDate: string) => {
  const date = new Date(`${isoDate}T12:00:00`);
  date.setDate(date.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderModal() {
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
        <ShareTypeVariationModal
          visible
          onClose={vi.fn()}
          share_type="st-veg"
          share_type_name="Vegetables"
        />,
      )}
    </QueryClientProvider>,
  );
  return { profiler };
}

const table = () => {
  const element = document.querySelector<HTMLElement>(".ant-table-tbody");
  if (!element) throw new Error("No table is shown");
  return element;
};

/** The saved row of a variation, found by its capacity (unique per fixture). */
function rowWithCapacity(capacity: number): HTMLElement {
  const row = within(table())
    .getAllByRole("row")
    .find((candidate) =>
      within(candidate).queryByText(String(capacity), { exact: true }),
    );
  if (!row) throw new Error(`No row has capacity ${capacity}`);
  return row;
}

function editingRow(): HTMLElement {
  const row = screen.getByRole("button", { name: "table.save" }).closest("tr");
  if (!row) throw new Error("No row is being edited");
  return row;
}

function openCalendar(): HTMLElement {
  const open = Array.from(
    document.querySelectorAll<HTMLElement>(".ant-picker-dropdown"),
  ).filter(
    (dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"),
  );
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

async function pickDate(label: string, isoDate: string) {
  await userEvent.click(within(editingRow()).getByLabelText(label));
  const cell = openCalendar().querySelector<HTMLElement>(
    `td[title="${isoDate}"]`,
  );
  if (!cell) throw new Error(`No calendar cell for ${isoDate}`);
  await userEvent.click(cell);
}

async function pickSize(size: string) {
  await userEvent.click(
    within(editingRow()).getByRole("combobox", { name: "commissioning.size" }),
  );
  const option = await waitFor(() => {
    const match = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
      ),
    ).find((item) => item.getAttribute("title") === `commissioning.${size}`);
    if (!match) throw new Error(`No size ${size} is offered`);
    return match;
  });
  await userEvent.click(option);
}

async function typeInto(label: string, text: string) {
  const input = within(editingRow()).getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, text);
}

const VALID_FROM = "configuration.valid_from";
const VALID_UNTIL = "configuration.valid_until";
const SORT_ORDER = "commissioning.sort_order";
const CAPACITY = "commissioning.capacity";

async function startNewVariation() {
  await userEvent.click(
    screen.getByRole("button", { name: /table\.add_record/ }),
  );
}

async function save() {
  await userEvent.click(screen.getByRole("button", { name: "table.save" }));
}

/** Waits until the variations are listed. */
async function loaded() {
  await waitFor(() => rowWithCapacity(100));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantSettings.values = {};
  auth.roles = ["office"];
  Object.values(notify).forEach((fn) => fn.mockReset());
  serverRows = [MEDIUM, SMALL_SPRING, SMALL_AUTUMN, LARGE_OLD];
  api.list.mockReset().mockImplementation(async () => [...serverRows]);
  api.shareType.mockReset().mockResolvedValue({
    id: "st-veg",
    name: "Vegetables",
    amount_of_jokers: 0,
    amount_of_donation_jokers: 0,
  });
  api.crates
    .mockReset()
    .mockResolvedValue([
      { id: "crate-euro", name: "Euro crate", short_name: "Euro" },
    ]);
  api.create.mockReset().mockImplementation(async (data: Variation) => {
    const saved = { ...variation({ id: "v-new" }), ...data, id: "v-new" };
    // The backend closes the size's open variation the day before a later one.
    serverRows = [
      saved,
      ...serverRows.map((row) =>
        row.size === data.size &&
        row.valid_until === null &&
        String(row.valid_from) < String(data.valid_from)
          ? { ...row, valid_until: dayBefore(String(data.valid_from)) }
          : row,
      ),
    ];
    return saved;
  });
  api.update
    .mockReset()
    .mockImplementation(async (id: string, data: Variation) => {
      serverRows = serverRows.map((row) =>
        row.id === id ? { ...row, ...data, id } : row,
      );
      return serverRows.find((row) => row.id === id);
    });
  api.destroy.mockReset().mockImplementation(async (id: string) => {
    serverRows = serverRows.filter((row) => row.id !== id);
  });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Loading ─────────────────────────────────────────────────────────────────

describe("ShareTypeVariationModal loading", () => {
  it("lists the variations of the share type it was opened for", async () => {
    renderModal();
    await loaded();

    expect(api.list).toHaveBeenCalledWith({ share_type: "st-veg" });
    expect(
      within(screen.getByRole("dialog")).getByText(
        "commissioning.variations Vegetables",
      ),
    ).toBeInTheDocument();
    const medium = rowWithCapacity(100);
    expect(within(medium).getByText("commissioning.M")).toBeInTheDocument();
    expect(within(medium).getByText("Euro")).toBeInTheDocument();
    expect(
      within(rowWithCapacity(40)).getByText("28.12.2025"),
    ).toBeInTheDocument();
  });

  it("shows the trial, bulk-packing and opt-in columns only where they apply", async () => {
    renderModal();
    await loaded();
    const headers = () =>
      screen
        .getAllByRole("columnheader")
        .map((header) => header.textContent ?? "");

    expect(headers().join("|")).not.toMatch(
      /allowed_for_trial_subscription|is_packed_bulk|requires_optin/,
    );
  });

  it("offers the optional columns the tenant has switched on", async () => {
    tenantSettings.values = {
      allows_trial_subscriptions: true,
      packing_mode: "MIXED",
      allows_share_type_variation_optin: true,
    };
    renderModal();
    await loaded();

    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent ?? "")
      .join("|");
    expect(headers).toMatch(/commissioning\.allowed_for_trial_subscription/);
    expect(headers).toMatch(/commissioning\.is_packed_bulk/);
    expect(headers).toMatch(/commissioning\.requires_optin/);
  });

  it("shows a tenant that uploads its weekly share amounts no capacity, trial or prices", async () => {
    tenantSettings.values = {
      uploads_weekly_share_amount: true,
      allows_trial_subscriptions: true,
    };
    renderModal();
    // ``loaded`` finds the rows by their capacity, which this tenant doesn't see.
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", {
          name: "commissioning.configure_virtual_components",
        }),
      ).toHaveLength(serverRows.length),
    );

    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent ?? "")
      .join("|");
    expect(headers).not.toMatch(/commissioning\.capacity/);
    expect(headers).not.toMatch(
      /commissioning\.allowed_for_trial_subscription/,
    );
    expect(
      screen.queryByRole("button", { name: "commissioning.configure_prices" }),
    ).not.toBeInTheDocument();
  });

  it("hides the opt-in columns for a share type with jokers", async () => {
    tenantSettings.values = { allows_share_type_variation_optin: true };
    api.shareType.mockResolvedValue({
      id: "st-veg",
      name: "Vegetables",
      amount_of_jokers: 2,
      amount_of_donation_jokers: 0,
    });
    renderModal();
    await loaded();
    await waitFor(() => expect(api.shareType).toHaveBeenCalled());
    await flushMicrotasks();

    expect(
      screen
        .getAllByRole("columnheader")
        .map((header) => header.textContent ?? "")
        .join("|"),
    ).not.toMatch(/commissioning\.requires_optin/);
  });

  it("settles after mounting instead of re-rendering in a loop", async () => {
    const { profiler } = renderModal();
    await loaded();
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(120);
  });
});

// ── Sizes over time ─────────────────────────────────────────────────────────

describe("ShareTypeVariationModal sizes over time", () => {
  it("adds a successor to a running size, keeping its sort order, and shows the old one ended", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("M");
    await pickDate(VALID_FROM, "2026-11-02");
    await typeInto(SORT_ORDER, "2");
    await typeInto(CAPACITY, "120");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        share_type: "st-veg",
        size: "M",
        valid_from: "2026-11-02",
        sort_order: "2",
      }),
    );
    await waitFor(() =>
      expect(
        within(rowWithCapacity(100)).getByText("01.11.2026"),
      ).toBeInTheDocument(),
    );
  });

  it("brings back a size that has ended, with the sort order it had", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("L");
    await pickDate(VALID_FROM, "2026-10-12");
    await typeInto(SORT_ORDER, "3");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        size: "L",
        valid_from: "2026-10-12",
        sort_order: "3",
      }),
    );
  });

  it("refuses a new variation starting before the coming one of its size", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("S");
    await pickDate(VALID_FROM, "2026-10-12");
    await save();

    expect(
      await screen.findAllByText(
        /errors\.time_bound\.succession_start_before_predecessor/,
      ),
    ).not.toHaveLength(0);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("refuses a new variation starting the same day as the running one of its size", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("S");
    await pickDate(VALID_FROM, "2026-10-19");
    await save();

    expect(
      await screen.findAllByText(/errors\.time_bound\.overlap/),
    ).not.toHaveLength(0);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("saves a variation of a size that has another one at another time", async () => {
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(50)).getByRole("button", { name: "table.edit" }),
    );
    await typeInto(CAPACITY, "55");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update).toHaveBeenCalledWith(
      "v-s-autumn",
      expect.objectContaining({ size: "S", capacity: "55" }),
    );
  });

  it("refuses stretching a variation into the next one of its size", async () => {
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(60)).getByRole("button", { name: "table.edit" }),
    );
    await pickDate(VALID_UNTIL, "2026-10-25");
    await save();

    expect(
      await screen.findAllByText(/errors\.time_bound\.overlap/),
    ).not.toHaveLength(0);
    expect(api.update).not.toHaveBeenCalled();
  });
});

// ── Sort order ──────────────────────────────────────────────────────────────

describe("ShareTypeVariationModal sort order", () => {
  it("refuses a sort order another variation holds at the same time", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("XL");
    await pickDate(VALID_FROM, "2026-10-12");
    await typeInto(SORT_ORDER, "2");
    await save();

    expect(
      await screen.findAllByText(/validation\.unique\.sort_order/),
    ).not.toHaveLength(0);
    expect(within(editingRow()).getByLabelText(SORT_ORDER)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(api.create).not.toHaveBeenCalled();
  });

  it("lets a sort order be reused once its variation has ended", async () => {
    renderModal();
    await loaded();

    await startNewVariation();
    await pickSize("XL");
    await pickDate(VALID_FROM, "2026-10-12");
    await typeInto(SORT_ORDER, "3");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
  });
});

// ── Prices, components, description ─────────────────────────────────────────

describe("ShareTypeVariationModal details", () => {
  it("opens the prices of the variation it is clicked for", async () => {
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(50)).getByRole("button", {
        name: "commissioning.configure_prices",
      }),
    );

    expect(screen.getByTestId("price-modal")).toHaveTextContent("v-s-autumn");
  });

  it("opens the components of the variation it is clicked for", async () => {
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(100)).getByRole("button", {
        name: "commissioning.configure_virtual_components",
      }),
    );

    expect(screen.getByTestId("components-modal")).toHaveTextContent("v-m");
  });

  it("saves an edited description and closes the editor", async () => {
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(100)).getByRole("button", {
        name: "commissioning.edit_description",
      }),
    );
    const editor = await screen.findByRole("textbox", {
      name: "Description text",
    });
    expect(editor).toHaveValue("<p>Medium box</p>");
    await userEvent.clear(editor);
    await userEvent.type(editor, "Medium box, about 3 kg");
    await userEvent.click(screen.getByRole("button", { name: /common\.save/ }));

    await waitFor(() =>
      expect(api.update).toHaveBeenCalledWith("v-m", {
        description: "Medium box, about 3 kg",
      }),
    );
    expect(notify.success).toHaveBeenCalledWith("common.saved_successfully");
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "Description text" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the editor open with the text when the description can't be saved", async () => {
    api.update.mockRejectedValue(new Error("Network Error"));
    renderModal();
    await loaded();

    await userEvent.click(
      within(rowWithCapacity(100)).getByRole("button", {
        name: "commissioning.edit_description",
      }),
    );
    const editor = await screen.findByRole("textbox", {
      name: "Description text",
    });
    await userEvent.clear(editor);
    await userEvent.type(editor, "Medium box, about 3 kg");
    await userEvent.click(screen.getByRole("button", { name: /common\.save/ }));

    await waitFor(() => expect(notify.error).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("textbox", { name: "Description text" }),
    ).toHaveValue("Medium box, about 3 kg");
  });
});

// ── Deleting and roles ──────────────────────────────────────────────────────

describe("ShareTypeVariationModal deleting and roles", () => {
  it("offers to delete only variations no subscription uses", async () => {
    renderModal();
    await loaded();

    expect(
      within(rowWithCapacity(100)).queryByRole("button", {
        name: "table.delete",
      }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(rowWithCapacity(40)).getByRole("button", { name: "table.delete" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "table.yes" }),
    );

    await waitFor(() => expect(api.destroy).toHaveBeenCalledWith("v-l-2025"));
    await waitFor(() =>
      expect(screen.queryByText("28.12.2025")).not.toBeInTheDocument(),
    );
  });

  it("shows the variations read-only to staff without the office role", async () => {
    auth.roles = ["staff"];
    renderModal();
    await loaded();

    expect(
      screen.queryByRole("button", { name: /table\.add_record/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "table.delete" }),
    ).not.toBeInTheDocument();
  });
});
