/**
 * ConfigurationLabels: the editor of the farm's label. A farm without a
 * template starts from the default one; changes stay a draft until saved. The
 * generated commissioning client is the mocking boundary: its hooks are real
 * TanStack queries and mutations around spies. What the editor does is read
 * from what Save sends, and from the documents a test print hands the PDF
 * library, which is stubbed.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LabelTemplate, LabelTemplateRequest } from "@shared/api/generated/models";
import { DEFAULT_LAYOUT, templateRequest } from "@features/commissioning/utils/labelLayout";
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
  const tenant = makeUseTenantMock({ tenantName: "Gärtnerei Sonnenhof" });
  return { useTenant: () => tenant };
});

const api = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@shared/api/generated/commissioning/commissioning", async () => {
  const { useMutation, useQuery } = await import("@tanstack/react-query");
  const listKey = () => ["/api/commissioning/label_templates/"];
  return {
    getCommissioningLabelTemplatesListQueryKey: listKey,
    useCommissioningLabelTemplatesList: () =>
      useQuery({ queryKey: listKey(), queryFn: async () => api.list() }),
    useCommissioningLabelTemplatesCreate: () =>
      useMutation({
        mutationFn: async ({ data }: { data: LabelTemplateRequest }) => api.create(data),
      }),
    useCommissioningLabelTemplatesUpdate: () =>
      useMutation({
        mutationFn: async ({ id, data }: { id: string; data: LabelTemplateRequest }) =>
          api.update(id, data),
      }),
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

const printed = vi.hoisted(() => ({
  documents: [] as { props: Record<string, unknown> }[],
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
vi.mock("@shared/utils/downloadBlob", () => ({ downloadBlob: () => {} }));

import ConfigurationLabels from "../ConfigurationLabels";

const STORED: LabelTemplate = {
  id: "tpl-1",
  ...templateRequest(DEFAULT_LAYOUT, "Etikett"),
};

let stored: LabelTemplate[];

function renderPage() {
  const profiler = profileRenders();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      {profiler.wrap(<ConfigurationLabels />)}
    </QueryClientProvider>,
  );
  return { profiler };
}

const SAVE = "commissioning.labels.save";
const canvas = () => screen.getByRole("group", { name: "commissioning.labels.canvas_aria" });
/** The field on the label that shows ``text``. */
const fieldShowing = (text: string) => {
  const field = within(canvas()).getByText(text).closest("button");
  if (!field) throw new Error(`No field shows ${text}`);
  return field;
};

async function saved(): Promise<LabelTemplateRequest> {
  await userEvent.click(screen.getByRole("button", { name: SAVE }));
  await waitFor(() =>
    expect(api.create.mock.calls.length + api.update.mock.calls.length).toBe(1),
  );
  return (api.create.mock.lastCall?.[0] ?? api.update.mock.lastCall?.[1]) as LabelTemplateRequest;
}

beforeEach(() => {
  stored = [STORED];
  printed.documents = [];
  api.list.mockReset().mockImplementation(async () => stored);
  api.create.mockReset().mockImplementation(async (data) => ({ id: "tpl-new", ...data }));
  api.update.mockReset().mockImplementation(async (id, data) => ({ id, ...data }));
});

describe("ConfigurationLabels", () => {
  it("starts a farm without a template from the default one and creates it on save", async () => {
    stored = [];
    renderPage();
    await screen.findByText("commissioning.labels.unsaved");

    const data = await saved();

    expect(data).toEqual(templateRequest(DEFAULT_LAYOUT, "commissioning.labels.template_name"));
    expect(api.update).not.toHaveBeenCalled();
  });

  it("offers no save before a stored template is changed", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");

    expect(screen.getByRole("button", { name: SAVE })).toBeDisabled();
    expect(screen.queryByText("commissioning.labels.unsaved")).not.toBeInTheDocument();
  });

  it("adds a clicked field to the label and saves it into the template", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");

    await userEvent.click(
      screen.getByRole("button", { name: "commissioning.labels.fields.order_number" }),
    );

    expect(
      screen.getByText("commissioning.labels.fields.order_number", { selector: ".ant-card-head-title" }),
    ).toBeInTheDocument();
    const data = await saved();
    expect(api.update).toHaveBeenCalledWith("tpl-1", expect.anything());
    expect(data.elements.at(-1)).toMatchObject({
      field: "order_number",
      x_mm: 1,
      y_mm: 1,
      width_mm: 40,
      height_mm: 6,
    });
  });

  it("moves a field with the arrow keys, by 5 mm with Shift, and resizes it with Alt", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");
    const sort = fieldShowing("commissioning.labels.sample.sort");

    fireEvent.focus(sort);
    fireEvent.keyDown(sort, { key: "ArrowDown" });
    fireEvent.keyDown(sort, { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(sort, { key: "ArrowLeft", altKey: true });

    const data = await saved();
    // From 2/20 mm: one down, and to the left edge, where the 5 mm stop.
    expect(data.elements.find((element) => element.id === "sort")).toMatchObject({
      x_mm: 0,
      y_mm: 21,
      width_mm: 65,
    });
  });

  it("removes a field with Delete", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");

    fireEvent.keyDown(fieldShowing("commissioning.labels.sample.sort"), { key: "Delete" });

    expect(
      within(canvas()).queryByText("commissioning.labels.sample.sort"),
    ).not.toBeInTheDocument();
    const data = await saved();
    expect(data.elements.map((element) => element.id)).not.toContain("sort");
  });

  it("lays the labels out on an A4 sheet from a preset", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");

    await userEvent.click(screen.getByText("commissioning.labels.print_mode_sheet"));
    await userEvent.click(
      screen.getByRole("combobox", { name: "commissioning.labels.sheet_preset" }),
    );
    // The fifth preset: 63.5 x 38.1 mm, 3 x 7, with margins and a gap.
    const options = document.querySelectorAll<HTMLElement>(".ant-select-item-option");
    await userEvent.click(options[4]);

    expect(await saved()).toMatchObject({
      print_mode: "sheet",
      width_mm: "63.5",
      height_mm: "38.1",
      sheet_columns: 3,
      sheet_rows: 7,
      sheet_margin_top_mm: "15.1",
      sheet_margin_left_mm: "7.2",
      sheet_gap_x_mm: "2.5",
    });
  });

  it("test-prints one sample label on a label printer", async () => {
    renderPage();
    await screen.findByText("commissioning.labels.sample.sort");

    await userEvent.click(screen.getByRole("button", { name: /commissioning\.labels\.test_print$/ }));

    await waitFor(() => expect(printed.documents).toHaveLength(1));
    const { labels } = printed.documents[0].props as { labels: Record<string, string>[] };
    expect(labels).toEqual([
      expect.objectContaining({
        reseller: "commissioning.labels.sample.reseller",
        sort: "commissioning.labels.sample.sort",
      }),
    ]);
  });

  it("shows a label at real size, and one wider than the space shrunk to fit", async () => {
    stored = [{ ...STORED, width_mm: "300.0" }];
    // The frame the label sits in is 400 px wide.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(private readonly report: ResizeObserverCallback) {}
        observe() {
          this.report(
            [{ contentRect: { width: 400 } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          );
        }
        disconnect() {}
      },
    );
    try {
      renderPage();
      await screen.findByText("commissioning.labels.sample.sort");

      // 300 mm are about 1134 px at real size.
      expect(screen.getByText("commissioning.labels.shown_smaller")).toBeInTheDocument();
      expect(parseFloat(canvas().style.width)).toBeLessThanOrEqual(400);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("settles after loading instead of re-rendering in a loop", async () => {
    const { profiler } = renderPage();
    await screen.findByText("commissioning.labels.sample.sort");
    await flushMicrotasks();

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
