/**
 * LabelsResellers: the labels of a delivery day's order lines, one per packing
 * unit, printed from the farm's label template. Rendered through the real
 * selectors, table, number inputs and PDF button. The generated commissioning
 * client is the mocking boundary: its hooks are real TanStack queries around
 * spies that answer from an in-memory farm. The PDF library and the download
 * are stubbed, so the test reads the labels handed to the label PDF.
 *
 * The clock is frozen on Tuesday 6 October 2026 (ISO week 41), the delivery
 * day the page opens on.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CommissioningListResellersEntry,
  LabelTemplate,
} from "@shared/api/generated/models";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

const NOW = vi.hoisted(() => {
  const now = new Date(2026, 9, 6, 12, 0);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  return now;
});

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
  const tenant = makeUseTenantMock({
    tenantName: "Gärtnerei Sonnenhof",
    tenant: { organic_control_number: "DE-ÖKO-006" } as never,
  });
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the signed-in user's roles from here.
const auth = vi.hoisted(() => ({ roles: ["office"] as string[] }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-office", roles: auth.roles } }),
}));

const api = vi.hoisted(() => ({
  resellers: vi.fn(),
  days: vi.fn(),
  templates: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useQuery } = await import("@tanstack/react-query");
  const queryHook = (path: string, request: (params: unknown) => unknown) =>
    function useGeneratedQuery(
      paramsOrOptions?: unknown,
      options?: { query?: { enabled?: boolean } },
    ) {
      const params = path === "label_templates" ? undefined : paramsOrOptions;
      return useQuery({
        queryKey: [`/api/commissioning/${path}/`, ...(params ? [params] : [])],
        queryFn: async () => request(params),
        enabled: options?.query?.enabled,
      });
    };
  return {
    useCommissioningCommissioningListsResellersList: queryHook(
      "commissioning_lists_resellers",
      api.resellers,
    ),
    useCommissioningDaysWithOrdersRetrieve: queryHook("days_with_orders", api.days),
    useCommissioningLabelTemplatesList: queryHook("label_templates", api.templates),
  };
});

vi.mock("@features/commissioning/pdfs", async () => ({
  LabelsPDFGenerator: (
    await import("@features/commissioning/pdfs/exports/LabelsPDFGenerator")
  ).default,
}));
vi.mock("@features/commissioning/pdfs/exports/LabelsPDF", () => ({
  default: function LabelsPDF() {
    return null;
  },
}));

// The documents handed to the PDF renderer, in order.
const printed = vi.hoisted(() => ({
  documents: [] as { props: Record<string, unknown> }[],
  files: [] as string[],
}));
vi.mock("@react-pdf/renderer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
  pdf: (document: { props: Record<string, unknown> }) => ({
    toBlob: async () => {
      printed.documents.push({ props: document.props });
      return new Blob(["%PDF-1.7"], { type: "application/pdf" });
    },
  }),
}));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (_blob: Blob, filename: string) => {
    printed.files.push(filename);
  },
}));

import LabelsResellers from "../LabelsResellers";

// ── Fixtures ────────────────────────────────────────────────────────────────

type Line = CommissioningListResellersEntry["order"]["contents"][number];

const line = (
  id: string,
  article: string,
  amount: number,
  amountPerPu: number,
  values: Partial<Line> = {},
): Line => ({
  id,
  share_article_id: `sa-${id}`,
  share_article_name: article,
  organic_status: "conventional",
  amount,
  amount_per_pu: amountPerPu,
  size: "M",
  unit: "KG",
  sort: null,
  note: "",
  ...values,
});

const reseller = (
  name: string,
  number: string,
  lines: Line[],
): CommissioningListResellersEntry => ({
  id: `res-${name}`,
  name,
  address: "Hauptstraße 1",
  zip_code: "77933",
  city: "Lahr",
  order: { id: `order-${name}`, number, note: "", contents: lines },
});

const CARROTS = line("carrots", "Karotten", 12.5, 5, {
  organic_status: "organic",
  sort: "Nantaise",
});
const POTATOES = line("potatoes", "Kartoffeln", 10, 10);
const BEETROOT = line("beetroot", "Rote Bete", 6, 0, { unit: "PCS" });

const TEMPLATE: LabelTemplate = {
  id: "tpl-1",
  name: "Etikett",
  width_mm: "70.0",
  height_mm: "37.0",
  print_mode: "label_printer",
  elements: [
    { id: "reseller", field: "reseller_name", x_mm: 2, y_mm: 2, width_mm: 60, height_mm: 6 },
    { id: "article", field: "article", x_mm: 2, y_mm: 10, width_mm: 60, height_mm: 8 },
    { id: "amount", field: "amount_per_pu", x_mm: 40, y_mm: 28, width_mm: 28, height_mm: 7 },
    { id: "control", field: "control_number", x_mm: 2, y_mm: 28, width_mm: 30, height_mm: 6 },
  ],
};

let farm: {
  resellers: CommissioningListResellersEntry[];
  templates: LabelTemplate[];
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{profiler.wrap(<LabelsResellers />)}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { profiler };
}

const DOWNLOAD = /download\.selected_labels$/;
const SUM = /commissioning\.sum_labels/;

function rowOf(text: string): HTMLElement {
  const row = screen.getByText(text).closest("tr");
  if (!row) throw new Error(`No table row shows ${text}`);
  return row;
}

async function download() {
  await userEvent.click(screen.getByRole("button", { name: DOWNLOAD }));
  await waitFor(() => expect(printed.documents).toHaveLength(1));
  return printed.documents[0].props as {
    labels: Record<string, string>[];
    startPosition?: number;
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  auth.roles = ["office"];
  printed.documents = [];
  printed.files = [];
  farm = {
    resellers: [
      reseller("Hofladen", "B-0042", [CARROTS, POTATOES]),
      reseller("Markthalle", "B-0043", [BEETROOT]),
    ],
    templates: [TEMPLATE],
  };
  api.resellers.mockReset().mockImplementation(async () => farm.resellers);
  api.days.mockReset().mockResolvedValue({ days: [1] });
  api.templates.mockReset().mockImplementation(async () => farm.templates);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("LabelsResellers", () => {
  it("opens on today's delivery day and counts a label per packing unit", async () => {
    renderPage();
    await screen.findByText("Karotten Nantaise");

    expect(api.resellers).toHaveBeenCalledWith(
      expect.objectContaining({ year: 2026, delivery_week: 41, day_number: 1 }),
    );
    expect(within(rowOf("Karotten Nantaise")).getByRole("spinbutton")).toHaveValue("3");
    expect(within(rowOf("Kartoffeln")).getByRole("spinbutton")).toHaveValue("1");
    expect(within(rowOf("Rote Bete")).getByRole("spinbutton")).toHaveValue("1");
    expect(screen.getByText(SUM)).toHaveTextContent("5");
  });

  it("prints every line's labels with the order line's data when none is selected", async () => {
    renderPage();
    await screen.findByText("Karotten Nantaise");

    const { labels } = await download();

    expect(labels).toHaveLength(5);
    expect(labels[0]).toEqual({
      reseller: "Hofladen",
      article: "commissioning.organic.organic Karotten",
      amount: "5 commissioning.units.kg",
      control: "DE-ÖKO-006",
    });
    expect(labels[2]).toMatchObject({ amount: "2,5 commissioning.units.kg" });
    // A conventional article carries neither the organic word nor the number.
    expect(labels[3]).toEqual({
      reseller: "Hofladen",
      article: "Kartoffeln",
      amount: "10 commissioning.units.kg",
    });
    expect(labels[4]).toMatchObject({ reseller: "Markthalle", article: "Rote Bete" });
    expect(printed.files).toEqual([
      "commissioning.labels.page_title_2026_commissioning.KW41_COMMONWEEKDAYTUESDAY.pdf",
    ]);
  });

  it("prints the selected lines only", async () => {
    renderPage();
    await screen.findByText("Karotten Nantaise");

    await userEvent.click(within(rowOf("Rote Bete")).getByRole("checkbox"));

    expect(screen.getByText(SUM)).toHaveTextContent("1");
    const { labels } = await download();
    expect(labels).toEqual([
      expect.objectContaining({ reseller: "Markthalle", article: "Rote Bete" }),
    ]);
  });

  it("prints as many labels of a line as asked for", async () => {
    renderPage();
    await screen.findByText("Karotten Nantaise");
    const count = within(rowOf("Karotten Nantaise")).getByRole("spinbutton");

    await userEvent.clear(count);
    await userEvent.type(count, "1");
    await userEvent.tab();

    expect(screen.getByText(SUM)).toHaveTextContent("3");
  });

  it("asks for a layout and keeps the download disabled without a template", async () => {
    farm.templates = [];
    renderPage();
    await screen.findByText("Karotten Nantaise");

    expect(await screen.findByText("commissioning.labels.no_template")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "commissioning.labels.to_editor" })).toBeNull();
    expect(screen.getByRole("button", { name: DOWNLOAD })).toBeDisabled();
  });

  it("links an admin to the layout", async () => {
    farm.templates = [];
    auth.roles = ["admin"];
    renderPage();

    expect(
      await screen.findByRole("link", { name: "commissioning.labels.to_editor" }),
    ).toHaveAttribute("href", "/configuration/labels");
  });

  it("starts an A4 sheet at the place asked for", async () => {
    farm.templates = [{ ...TEMPLATE, print_mode: "sheet", sheet_columns: 3, sheet_rows: 8 }];
    renderPage();
    await screen.findByText("Karotten Nantaise");
    const start = await screen.findByRole("spinbutton", {
      name: "commissioning.labels.start_position",
    });

    await userEvent.clear(start);
    await userEvent.type(start, "7");
    await userEvent.tab();

    expect((await download()).startPosition).toBe(7);
  });

  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("Karotten Nantaise");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
