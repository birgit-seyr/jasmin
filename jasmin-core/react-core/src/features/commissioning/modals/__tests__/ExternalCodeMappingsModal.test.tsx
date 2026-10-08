/**
 * ExternalCodeMappingsModal: the code mappings of the weekly share import.
 * Each mapping ties a code from the farm's upload file to one internal object
 * of its kind — a share type variation, a delivery station or a delivery day —
 * with a note, and the import reads the file's codes through them.
 *
 * Rendered the way the import page uses it: mounted closed with the page,
 * opened from a button and hidden again when it closes. The real modal,
 * EditableTable and option hooks render; the generated commissioning client is
 * the mocking boundary, its list hooks real TanStack queries around spies that
 * answer from an in-memory server. Like the backend, that server refuses a
 * mapping whose internal id names no object of the mapping's kind.
 *
 * Nothing on this screen reads today's date, so the clock runs free.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DeliveryStation,
  ExternalCodeMapping,
  SharesDeliveryDay,
  ShareTypeVariation,
} from "@shared/api/generated/models";
import i18n from "@shared/i18n";
import {
  flushMicrotasks,
  profileRenders,
  type ProfileRendersHandle,
} from "@/test/profileRenders";

// The canonical mock, with one `t` for every render as react-i18next keeps it.
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

type MappingBody = Partial<ExternalCodeMapping> & Record<string, unknown>;

const api = vi.hoisted(() => ({
  mappings: vi.fn<(params?: unknown) => Promise<ExternalCodeMapping[]>>(),
  variations: vi.fn<(params?: unknown) => Promise<ShareTypeVariation[]>>(),
  stations: vi.fn<(params?: unknown) => Promise<DeliveryStation[]>>(),
  deliveryDays: vi.fn<(params?: unknown) => Promise<SharesDeliveryDay[]>>(),
  create: vi.fn<(body: MappingBody) => Promise<ExternalCodeMapping>>(),
  update: vi.fn<(id: string, body: MappingBody) => Promise<ExternalCodeMapping>>(),
  destroy: vi.fn<(id: string) => Promise<void>>(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  type Options = { query?: { enabled?: boolean } };
  const useListQuery = (
    path: string,
    params: unknown,
    answer: (params?: unknown) => Promise<unknown>,
    options?: Options,
  ) =>
    useQuery({
      queryKey: [`/api/commissioning/${path}/`, params],
      queryFn: () => answer(params),
      enabled: options?.query?.enabled,
    });
  return {
    useCommissioningExternalCodeMappingsList: (params: unknown, options?: Options) =>
      useListQuery("external_code_mappings", params, api.mappings, options),
    useCommissioningShareTypeVariationsList: (params: unknown, options?: Options) =>
      useListQuery("share_type_variations", params, api.variations, options),
    useCommissioningDeliveryStationsList: (params: unknown, options?: Options) =>
      useListQuery("delivery_stations", params, api.stations, options),
    useCommissioningSharesDeliveryDaysList: (params: unknown, options?: Options) =>
      useListQuery("shares_delivery_days", params, api.deliveryDays, options),
    commissioningExternalCodeMappingsCreate: (body: MappingBody) => api.create(body),
    commissioningExternalCodeMappingsPartialUpdate: (id: string, body: MappingBody) =>
      api.update(id, body),
    commissioningExternalCodeMappingsDestroy: (id: string) => api.destroy(id),
  };
});

import ExternalCodeMappingsModal from "../ExternalCodeMappingsModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

// The small vegetable box ran until the end of 2025, when a new one took over.
const VARIATIONS: ShareTypeVariation[] = [
  { id: "var-veg-s", share_type: "st-veg", share_type_name: "Vegetables", size: "S", valid_from: "2025-01-06", valid_until: "2025-12-28" },
  { id: "var-veg-s-2026", share_type: "st-veg", share_type_name: "Vegetables", size: "S", valid_from: "2025-12-29", valid_until: null },
  { id: "var-veg-l", share_type: "st-veg", share_type_name: "Vegetables", size: "L", valid_from: "2025-01-06" },
  { id: "var-bread", share_type: "st-bread", share_type_name: "Bread", size: "ONE_SIZE", valid_from: "2025-01-06" },
];

const STATIONS: DeliveryStation[] = [
  { id: "station-mill", short_name: "Mill", city: "Vienna" },
  { id: "station-farm", short_name: "Farm", city: "" },
  // Set up, but neither named nor placed yet.
  { id: "station-new", short_name: null, city: "" },
];

// Tuesday's delivery day ran until the end of 2025, when a new one took over.
const DELIVERY_DAYS: SharesDeliveryDay[] = [
  { id: "sdd-tue-2025", day_number: 1, valid_from: "2025-01-06", valid_until: "2025-12-28" },
  { id: "sdd-tue", day_number: 1, valid_from: "2025-12-29", valid_until: null },
  { id: "sdd-thu", day_number: 3, valid_from: "2025-01-06", valid_until: null },
];

// The internal objects as the modal labels them, dated in the default format.
const VEG_S = "var-veg-s — Vegetables · commissioning.S · 06.01.2025 → 28.12.2025";
const VEG_S_2026 = "var-veg-s-2026 — Vegetables · commissioning.S · 29.12.2025";
const VEG_L = "var-veg-l — Vegetables · commissioning.L · 06.01.2025";
const BREAD = "var-bread — Bread · commissioning.ONE_SIZE · 06.01.2025";
const MILL = "station-mill — Mill · Vienna";
const FARM = "station-farm — Farm";
const UNNAMED_STATION = "station-new — import_shares.mappings.no_label";
const TUE_2025 = "sdd-tue-2025 — delivery.di · 06.01.2025 → 28.12.2025";
const TUE = "sdd-tue — delivery.di · 29.12.2025";
const THU = "sdd-thu — delivery.do · 06.01.2025";

const MAPPINGS: ExternalCodeMapping[] = [
  // Still names the Tuesday delivery day that ended with 2025.
  { id: "map-tue", kind: "day", external_code: "TUE", internal_id: "sdd-tue-2025", note: "Tuesday round" },
  { id: "map-mill", kind: "station", external_code: "STN-001", internal_id: "station-mill", note: "Barn behind the mill" },
  { id: "map-veg-s", kind: "variation", external_code: "VEG-S", internal_id: "var-veg-s", note: null },
  // Its variation has been deleted since.
  { id: "map-veg-xl", kind: "variation", external_code: "VEG-XL", internal_id: "var-veg-xl", note: "Discontinued box" },
];

// Kind labels as the mocked `t` returns them.
const DAY = "import_shares.mappings.kind_day";
const STATION = "import_shares.mappings.kind_station";
const VARIATION = "import_shares.mappings.kind_variation";

// Column titles, which also name the inputs of the row being edited.
const KIND = "import_shares.mappings.kind";
const CODE = "import_shares.mappings.external_code";
const INTERNAL = "import_shares.mappings.internal_id";
const NOTE = "commissioning.note";

// The mappings as the modal lists them: kind, code, internal object, note.
const SHOWN_MAPPINGS = [
  [DAY, "TUE", TUE_2025, "Tuesday round"],
  [STATION, "STN-001", MILL, "Barn behind the mill"],
  [VARIATION, "VEG-S", VEG_S, ""],
  [VARIATION, "VEG-XL", "var-veg-xl", "Discontinued box"],
];

// ── The server ──────────────────────────────────────────────────────────────

interface Server {
  mappings: ExternalCodeMapping[];
  variations: ShareTypeVariation[];
  stations: DeliveryStation[];
  deliveryDays: SharesDeliveryDay[];
}
let server: Server;
let createdCount = 0;

const MODEL_OF_KIND = {
  variation: "ShareTypeVariation",
  station: "DeliveryStation",
  day: "SharesDeliveryDay",
} as const;

const objectsOfKind = (kind: ExternalCodeMapping["kind"]): { id?: string }[] =>
  ({ variation: server.variations, station: server.stations, day: server.deliveryDays })[kind];

/**
 * The fields of a request body the serializer reads, as JSON carries them:
 * without the undefined ones. The table sends its row bookkeeping along (the
 * row's key, and a saved row's read-only id), which the serializer ignores.
 */
function writableFields(body: MappingBody): Partial<ExternalCodeMapping> {
  return Object.fromEntries(
    (["kind", "external_code", "internal_id", "note"] as const)
      .filter((field) => body[field] !== undefined)
      .map((field) => [field, body[field]]),
  );
}

/** The backend's refusal of a mapping whose internal id names no object of its kind. */
const targetMissing = ({ kind, internal_id }: ExternalCodeMapping) => ({
  isAxiosError: true,
  response: {
    status: 400,
    data: {
      code: "share_import.mapping_target_missing",
      message: `No ${MODEL_OF_KIND[kind]} has the id '${internal_id}'.`,
      field: "internal_id",
      details: { kind, internal_id },
    },
  },
});

function saveOnServer(id: string, body: MappingBody): ExternalCodeMapping {
  const current = server.mappings.find((mapping) => mapping.id === id);
  const saved = { note: null, ...current, ...writableFields(body), id } as ExternalCodeMapping;
  if (!objectsOfKind(saved.kind).some((object) => object.id === saved.internal_id)) {
    throw targetMissing(saved);
  }
  server.mappings = current
    ? server.mappings.map((mapping) => (mapping.id === id ? saved : mapping))
    : [...server.mappings, saved];
  return { ...saved };
}

// The server lists the mappings by kind, then by code.
const listedMappings = () =>
  [...server.mappings]
    .sort((a, b) => a.kind.localeCompare(b.kind) || a.external_code.localeCompare(b.external_code))
    .map((mapping) => ({ ...mapping }));

beforeEach(() => {
  tenantSettings.values = {};
  auth.roles = ["office"];
  createdCount = 0;
  server = {
    mappings: MAPPINGS.map((mapping) => ({ ...mapping })),
    variations: [...VARIATIONS],
    stations: [...STATIONS],
    deliveryDays: [...DELIVERY_DAYS],
  };
  api.mappings.mockReset().mockImplementation(async () => listedMappings());
  api.variations
    .mockReset()
    .mockImplementation(async () => server.variations.map((variation) => ({ ...variation })));
  api.stations
    .mockReset()
    .mockImplementation(async () => server.stations.map((station) => ({ ...station })));
  api.deliveryDays
    .mockReset()
    .mockImplementation(async () => server.deliveryDays.map((day) => ({ ...day })));
  api.create
    .mockReset()
    .mockImplementation(async (body) => saveOnServer(`map-new-${++createdCount}`, body));
  api.update.mockReset().mockImplementation(async (id, body) => saveOnServer(id, body));
  api.destroy.mockReset().mockImplementation(async (id) => {
    server.mappings = server.mappings.filter((mapping) => mapping.id !== id);
  });
});

// ── Helpers ─────────────────────────────────────────────────────────────────

const OPEN_MAPPINGS = "Code mappings";

/** The import page, as far as the mappings go: a button opens them, closing hides them. */
function ImportPage({
  onClose,
  profiler,
}: {
  onClose: () => void;
  profiler: ProfileRendersHandle;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        {OPEN_MAPPINGS}
      </button>
      {profiler.wrap(
        <ExternalCodeMappingsModal
          open={open}
          onClose={() => {
            onClose();
            setOpen(false);
          }}
        />,
      )}
    </>
  );
}

let queryClient: QueryClient;

function renderPage() {
  const onClose = vi.fn();
  const profiler = profileRenders();
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ImportPage onClose={onClose} profiler={profiler} />
    </QueryClientProvider>,
  );
  return { onClose, profiler };
}

const dialog = () => screen.getByRole("dialog");

// AntD's Spin turns itself off in an effect, a render after the rows arrive.
const spinner = () => document.querySelector(".ant-modal .ant-spin-spinning");

const bodyRows = () =>
  Array.from(
    document.querySelectorAll<HTMLTableRowElement>(
      ".ant-modal .ant-table-tbody > tr.ant-table-row",
    ),
  );

/** Opens the mappings from the page and waits until they and their objects are there. */
async function openMappings() {
  const count = server.mappings.length;
  await userEvent.click(screen.getByRole("button", { name: OPEN_MAPPINGS }));
  await waitFor(() => {
    expect(bodyRows()).toHaveLength(count);
    expect(queryClient.isFetching()).toBe(0);
    expect(spinner()).not.toBeInTheDocument();
  });
}

async function renderOpen() {
  const page = renderPage();
  await openMappings();
  return page;
}

const columnTitles = () =>
  Array.from(dialog().querySelectorAll(".ant-table-thead > tr > th")).map(
    (th) => th.textContent ?? "",
  );

function cellOf(row: HTMLElement, title: string): HTMLElement {
  const index = columnTitles().indexOf(title);
  const cell = row.querySelectorAll<HTMLElement>(":scope > td")[index];
  if (index < 0 || !cell) throw new Error(`No column titled ${title}`);
  return cell;
}

/** What each row shows: the mapping's kind, code, internal object and note. */
const shownMappings = () =>
  bodyRows().map((row) =>
    [KIND, CODE, INTERNAL, NOTE].map((title) => cellOf(row, title).textContent),
  );

function rowAround(element: HTMLElement, what: string): HTMLElement {
  const row = element.closest("tr");
  if (!row) throw new Error(`No table row ${what}`);
  return row;
}

/** The row of the mapping with this code, while it isn't being edited. */
const rowOf = (code: string) => rowAround(within(dialog()).getByText(code), `shows ${code}`);

/** The row being edited — the one offering a save button. */
const editingRow = () =>
  rowAround(within(dialog()).getByRole("button", { name: "table.save" }), "is being edited");

const select = (title: string) => within(editingRow()).getByRole("combobox", { name: title });
const textField = (title: string) => within(editingRow()).getByRole("textbox", { name: title });
const addButton = () => within(dialog()).queryByRole("button", { name: /table\.add_plus_icon$/ });

async function waitForEditing() {
  await within(dialog()).findByRole("button", { name: "table.save" });
}

async function startNewMapping() {
  await userEvent.click(addButton()!);
  await waitForEditing();
}

async function editMapping(code: string) {
  await userEvent.click(within(rowOf(code)).getByRole("button", { name: "table.edit" }));
  await waitForEditing();
}

async function retype(title: string, text: string) {
  const input = textField(title);
  await userEvent.clear(input);
  if (text) await userEvent.type(input, text);
}

function openPopup(): HTMLElement {
  const popup = Array.from(document.querySelectorAll<HTMLElement>(".ant-select-dropdown"))
    .filter((each) => !each.classList.contains("ant-select-dropdown-hidden"))
    .pop();
  if (!popup) throw new Error("No select is open");
  return popup;
}

async function openSelect(title: string): Promise<HTMLElement> {
  await userEvent.click(select(title));
  return waitFor(openPopup);
}

/** The options the select of the column titled `title` offers. */
async function optionsOf(title: string): Promise<string[]> {
  const popup = await openSelect(title);
  return Array.from(popup.querySelectorAll(".ant-select-item-option-content")).map(
    (option) => option.textContent ?? "",
  );
}

async function choose(title: string, option: string) {
  const popup = await openSelect(title);
  await userEvent.click(within(popup).getByText(option));
}

/** The label the select of the column titled `title` shows for its value. */
const selectedIn = (title: string) =>
  select(title).closest(".ant-select")?.querySelector(".ant-select-selection-item")
    ?.textContent ?? "";

async function save() {
  await userEvent.click(within(dialog()).getByRole("button", { name: "table.save" }));
}

const created = () => writableFields(api.create.mock.lastCall![0]);
const updated = () => {
  const [id, body] = api.update.mock.lastCall!;
  return [id, writableFields(body)];
};

const closeIcon = () => within(dialog()).getByRole("button", { name: "Close" });

// ── What the office sees ────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal contents", () => {
  it("asks for nothing until the office opens it, then for every mapping, variation, station and delivery day", async () => {
    renderPage();
    await act(() => flushMicrotasks());

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    for (const list of [api.mappings, api.variations, api.stations, api.deliveryDays]) {
      expect(list).not.toHaveBeenCalled();
    }

    await openMappings();

    // Unfiltered, so ended variations and delivery days a mapping may still
    // name come along.
    for (const list of [api.mappings, api.variations, api.stations, api.deliveryDays]) {
      expect(list).toHaveBeenCalledTimes(1);
      expect(list.mock.calls[0][0] ?? {}).toEqual({});
    }
  });

  it("shows a spinner over the table while the mappings load", async () => {
    let deliver: (mappings: ExternalCodeMapping[]) => void = () => {};
    api.mappings.mockImplementation(
      () => new Promise((resolve) => (deliver = resolve)),
    );
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: OPEN_MAPPINGS }));

    await waitFor(() => expect(spinner()).toBeInTheDocument());
    expect(bodyRows()).toHaveLength(0);

    deliver(listedMappings());

    await waitFor(() => expect(shownMappings()).toEqual(SHOWN_MAPPINGS));
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
  });

  it("is titled, says what the mappings are for and explains them", async () => {
    await renderOpen();

    expect(await screen.findAllByText("import_shares.mappings.title")).not.toHaveLength(0);
    expect(within(dialog()).getByText("import_shares.mappings.subtitle")).toBeInTheDocument();
    expect(
      within(dialog()).getByText("import_shares.mappings.explainer_body"),
    ).toBeInTheDocument();
  });

  it("lists each mapping with its kind, code, internal object and note, as the server orders them", async () => {
    await renderOpen();

    expect(columnTitles()).toEqual(["table.actions", KIND, CODE, INTERNAL, NOTE]);
    expect(shownMappings()).toEqual(SHOWN_MAPPINGS);
  });

  it("shows an object's bare id until its list arrives, then its label", async () => {
    let deliver: (variations: ShareTypeVariation[]) => void = () => {};
    api.variations.mockImplementation(
      () => new Promise((resolve) => (deliver = resolve)),
    );
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: OPEN_MAPPINGS }));
    await waitFor(() => expect(bodyRows()).toHaveLength(MAPPINGS.length));

    expect(cellOf(rowOf("VEG-S"), INTERNAL).textContent).toBe("var-veg-s");
    expect(cellOf(rowOf("STN-001"), INTERNAL).textContent).toBe(MILL);

    deliver(VARIATIONS);

    await waitFor(() => expect(cellOf(rowOf("VEG-S"), INTERNAL).textContent).toBe(VEG_S));
    // No list knows the variation VEG-XL names.
    expect(cellOf(rowOf("VEG-XL"), INTERNAL).textContent).toBe("var-veg-xl");
  });

  it("dates the variations in the tenant's format, so a replaced one tells from its successor", async () => {
    tenantSettings.values = { date_format: "MM/DD/YYYY" };
    await renderOpen();

    expect(cellOf(rowOf("VEG-S"), INTERNAL).textContent).toBe(
      "var-veg-s — Vegetables · commissioning.S · 01/06/2025 → 12/28/2025",
    );
    await editMapping("VEG-S");
    expect((await optionsOf(INTERNAL)).slice(0, 2)).toEqual([
      "var-veg-s — Vegetables · commissioning.S · 01/06/2025 → 12/28/2025",
      "var-veg-s-2026 — Vegetables · commissioning.S · 12/29/2025",
    ]);
  });

  it("shows an id of another kind's object as unknown", async () => {
    server.mappings.push(
      { id: "map-stn-veg", kind: "station", external_code: "STN-VEG", internal_id: "var-veg-s", note: null },
      { id: "map-day-mill", kind: "day", external_code: "DAY-MILL", internal_id: "station-mill", note: null },
    );
    await renderOpen();

    expect(cellOf(rowOf("STN-VEG"), INTERNAL).textContent).toBe("var-veg-s");
    expect(cellOf(rowOf("DAY-MILL"), INTERNAL).textContent).toBe("station-mill");
  });

  it("dates the delivery days in the tenant's format", async () => {
    tenantSettings.values = { date_format: "MM/DD/YYYY" };
    await renderOpen();

    expect(cellOf(rowOf("TUE"), INTERNAL).textContent).toBe(
      "sdd-tue-2025 — delivery.di · 01/06/2025 → 12/28/2025",
    );
    await editMapping("TUE");
    expect(await optionsOf(INTERNAL)).toEqual([
      "sdd-tue-2025 — delivery.di · 01/06/2025 → 12/28/2025",
      "sdd-tue — delivery.di · 12/29/2025",
      "sdd-thu — delivery.do · 01/06/2025",
    ]);
  });

  it("says there are none yet when the farm has no mappings", async () => {
    server.mappings = [];
    await renderOpen();

    expect(within(dialog()).getByText("table.no_data")).toBeInTheDocument();
    expect(addButton()).toBeInTheDocument();
  });

  it("settles after opening instead of re-rendering in a loop", async () => {
    const { profiler } = await renderOpen();
    await act(() => flushMicrotasks());

    expect(profiler.onRender.mock.calls.length).toBeLessThan(100);
  });
});

// ── The internal-object picker ──────────────────────────────────────────────

describe("ExternalCodeMappingsModal picker", () => {
  it.each([
    { kind: "variation", code: "VEG-S", current: VEG_S, offered: [VEG_S, VEG_S_2026, VEG_L, BREAD] },
    { kind: "station", code: "STN-001", current: MILL, offered: [MILL, FARM, UNNAMED_STATION] },
    { kind: "day", code: "TUE", current: TUE_2025, offered: [TUE_2025, TUE, THU] },
  ])(
    "offers a $kind mapping the farm's objects of its kind",
    async ({ code, current, offered }) => {
      await renderOpen();
      await editMapping(code);

      expect(selectedIn(INTERNAL)).toBe(current);
      expect(await optionsOf(INTERNAL)).toEqual(offered);
    },
  );

  it("offers the three kinds, and every object while a new mapping has no kind yet", async () => {
    await renderOpen();
    await startNewMapping();

    expect(await optionsOf(KIND)).toEqual([VARIATION, STATION, DAY]);
    expect(await optionsOf(INTERNAL)).toEqual([
      VEG_S,
      VEG_S_2026,
      VEG_L,
      BREAD,
      MILL,
      FARM,
      UNNAMED_STATION,
      TUE_2025,
      TUE,
      THU,
    ]);
  });

  it("empties the internal object and offers the new kind's objects when the kind changes", async () => {
    await renderOpen();
    await startNewMapping();
    await choose(KIND, STATION);
    await choose(INTERNAL, FARM);
    expect(selectedIn(INTERNAL)).toBe(FARM);

    await choose(KIND, DAY);

    expect(selectedIn(INTERNAL)).toBe("");
    expect(await optionsOf(INTERNAL)).toEqual([TUE_2025, TUE, THU]);
    await userEvent.click(within(openPopup()).getByText(THU));
    await retype(CODE, "THU");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(created()).toEqual({ kind: "day", external_code: "THU", internal_id: "sdd-thu" });
    await waitFor(() => expect(shownMappings()[0]).toEqual([DAY, "THU", THU, ""]));
  });
});

// ── Adding ──────────────────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal adding", () => {
  it("adds a mapping with its kind, code, internal object and note, and lists it", async () => {
    await renderOpen();
    await startNewMapping();

    await choose(KIND, STATION);
    await retype(CODE, "STN-002");
    await choose(INTERNAL, FARM);
    await retype(NOTE, "Farm shop");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(created()).toEqual({
      kind: "station",
      external_code: "STN-002",
      internal_id: "station-farm",
      note: "Farm shop",
    });
    await waitFor(() => expect(api.mappings).toHaveBeenCalledTimes(2));
    expect(shownMappings()).toEqual([
      [STATION, "STN-002", FARM, "Farm shop"],
      ...SHOWN_MAPPINGS,
    ]);
    expect(within(dialog()).queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });

  it("requires a kind, a code and an internal object, but no note", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderOpen();
    await startNewMapping();

    await save();

    await waitFor(() => expect(select(KIND)).toBeInvalid());
    expect(textField(CODE)).toBeInvalid();
    expect(select(INTERNAL)).toBeInvalid();
    expect(textField(NOTE)).toBeValid();
    await act(() => flushMicrotasks());
    expect(api.create).not.toHaveBeenCalled();

    await choose(KIND, VARIATION);
    await retype(CODE, "BREAD");
    await choose(INTERNAL, BREAD);
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(created()).toEqual({
      kind: "variation",
      external_code: "BREAD",
      internal_id: "var-bread",
    });
    await waitFor(() => expect(shownMappings()[0]).toEqual([VARIATION, "BREAD", BREAD, ""]));
  });

  it("refuses a second mapping of a kind's code without asking the server, and saves it under its own code", async () => {
    await renderOpen();
    await startNewMapping();
    await choose(KIND, DAY);
    await retype(CODE, "TUE");
    await choose(INTERNAL, THU);

    await save();

    expect(
      await within(dialog()).findByText(
        "validation.unique.external_code_mapping — table.save_failed_hint",
      ),
    ).toBeInTheDocument();
    await act(() => flushMicrotasks());
    expect(api.create).not.toHaveBeenCalled();
    expect(selectedIn(INTERNAL)).toBe(THU);

    await retype(CODE, "THU");
    await save();

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(created()).toEqual({ kind: "day", external_code: "THU", internal_id: "sdd-thu" });
    await waitFor(() => expect(shownMappings()[0]).toEqual([DAY, "THU", THU, ""]));
    expect(within(dialog()).queryByText(/table\.save_failed_hint$/)).not.toBeInTheDocument();
  });
});

// ── Editing ─────────────────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal editing", () => {
  it("points a mapping at the delivery day that took over from the one it names", async () => {
    await renderOpen();
    await editMapping("TUE");

    await choose(INTERNAL, TUE);
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(updated()).toEqual([
      "map-tue",
      { kind: "day", external_code: "TUE", internal_id: "sdd-tue", note: "Tuesday round" },
    ]);
    await waitFor(() => expect(api.mappings).toHaveBeenCalledTimes(2));
    expect(shownMappings()).toEqual([
      [DAY, "TUE", TUE, "Tuesday round"],
      ...SHOWN_MAPPINGS.slice(1),
    ]);
    expect(within(dialog()).queryByRole("button", { name: "table.save" })).not.toBeInTheDocument();
  });

  it("re-points a mapping whose variation is gone, with a new code and note", async () => {
    await renderOpen();
    await editMapping("VEG-XL");
    expect(selectedIn(INTERNAL)).toBe("var-veg-xl");

    await choose(INTERNAL, VEG_L);
    await retype(CODE, "VEG-L");
    await retype(NOTE, "Large box");
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(updated()).toEqual([
      "map-veg-xl",
      { kind: "variation", external_code: "VEG-L", internal_id: "var-veg-l", note: "Large box" },
    ]);
    await waitFor(() => expect(api.mappings).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(shownMappings()).toEqual([
        ...SHOWN_MAPPINGS.slice(0, 2),
        [VARIATION, "VEG-L", VEG_L, "Large box"],
        [VARIATION, "VEG-S", VEG_S, ""],
      ]),
    );
  });

  it("keeps the row open with its choice when the server finds the object gone, says why, and saves another", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderOpen();
    await editMapping("VEG-S");
    await choose(INTERNAL, BREAD);
    // The bread variation is deleted while the office is choosing.
    server.variations = server.variations.filter((variation) => variation.id !== "var-bread");

    await save();

    const message = i18n.t("errors.share_import.mapping_target_missing");
    expect(message).not.toBe("errors.share_import.mapping_target_missing");
    expect(
      await within(dialog()).findByText(`${message} — table.save_failed_hint`),
    ).toBeInTheDocument();
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(selectedIn(INTERNAL)).toBe(BREAD);
    expect(api.mappings).toHaveBeenCalledTimes(1);

    await choose(INTERNAL, VEG_L);
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2));
    expect(updated()).toEqual([
      "map-veg-s",
      { kind: "variation", external_code: "VEG-S", internal_id: "var-veg-l", note: null },
    ]);
    await waitFor(() => expect(cellOf(rowOf("VEG-S"), INTERNAL).textContent).toBe(VEG_L));
    expect(
      within(dialog()).queryByText(`${message} — table.save_failed_hint`),
    ).not.toBeInTheDocument();
  });

  it("lets an admin change mappings like the office", async () => {
    auth.roles = ["admin"];
    await renderOpen();
    expect(addButton()).toBeInTheDocument();

    await editMapping("STN-001");
    await choose(INTERNAL, FARM);
    await save();

    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(updated()).toEqual([
      "map-mill",
      {
        kind: "station",
        external_code: "STN-001",
        internal_id: "station-farm",
        note: "Barn behind the mill",
      },
    ]);
  });
});

// ── Deleting ────────────────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal deleting", () => {
  it("deletes a mapping once the office confirms it", async () => {
    await renderOpen();

    await userEvent.click(within(rowOf("STN-001")).getByRole("button", { name: "table.delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "table.yes" }));

    await waitFor(() => expect(api.destroy).toHaveBeenCalledTimes(1));
    expect(api.destroy).toHaveBeenCalledWith("map-mill");
    await waitFor(() => expect(api.mappings).toHaveBeenCalledTimes(2));
    expect(shownMappings()).toEqual(
      SHOWN_MAPPINGS.filter(([, code]) => code !== "STN-001"),
    );
  });

  it("keeps a mapping the office doesn't confirm deleting", async () => {
    await renderOpen();

    await userEvent.click(within(rowOf("STN-001")).getByRole("button", { name: "table.delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "table.no" }));

    await act(() => flushMicrotasks());
    expect(api.destroy).not.toHaveBeenCalled();
    expect(shownMappings()).toEqual(SHOWN_MAPPINGS);
  });
});

// ── Other roles ─────────────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal for roles other than the office", () => {
  it.each([{ roles: ["staff"] }, { roles: ["gardener"] }, { roles: ["management"] }])(
    "shows the mappings read-only to $roles",
    async ({ roles }) => {
      auth.roles = roles;
      await renderOpen();

      expect(shownMappings()).toEqual(SHOWN_MAPPINGS);
      expect(columnTitles()).toEqual([KIND, CODE, INTERNAL, NOTE]);
      expect(addButton()).not.toBeInTheDocument();
      expect(
        within(dialog()).queryByRole("button", { name: "table.edit" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog()).queryByRole("button", { name: "table.delete" }),
      ).not.toBeInTheDocument();

      await userEvent.click(cellOf(rowOf("STN-001"), CODE));
      await userEvent.click(cellOf(rowOf("VEG-S"), INTERNAL));

      expect(within(dialog()).queryByRole("textbox")).not.toBeInTheDocument();
      expect(within(dialog()).queryByRole("combobox")).not.toBeInTheDocument();
      expect(api.update).not.toHaveBeenCalled();
    },
  );
});

// ── Closing ─────────────────────────────────────────────────────────────────

describe("ExternalCodeMappingsModal closing", () => {
  it("closes from its close icon", async () => {
    const { onClose } = await renderOpen();

    await userEvent.click(closeIcon());

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("drops a mapping begun but not saved, and lists the mappings afresh when opened again", async () => {
    const { onClose } = await renderOpen();
    await startNewMapping();
    await choose(KIND, DAY);
    await retype(CODE, "WED");

    await userEvent.click(closeIcon());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await openMappings();

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api.create).not.toHaveBeenCalled();
    expect(api.mappings).toHaveBeenCalledTimes(2);
    expect(shownMappings()).toEqual(SHOWN_MAPPINGS);
    expect(
      within(dialog()).queryByRole("button", { name: "table.save" }),
    ).not.toBeInTheDocument();
  });
});
