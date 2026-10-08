/**
 * ExportCsvAtDateModal: the shell behind the "prices on a date" exports. The
 * office picks a date, loads the rows for it through the consumer's row hook,
 * then downloads a CSV built in the browser in the tenant's CSV format.
 * Rendered the way its consumers host it: mounted closed, opened from a
 * button, closed again when it reports a close. The row hook is a real
 * TanStack query around a spy, the date-format and CSV helpers run, and the
 * browser download is recorded instead of saved.
 *
 * The clock is frozen on Wednesday 7 October 2026, the date the picker starts on.
 */

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { flushMicrotasks } from "@/test/profileRenders";

// Shows the values a label is interpolated with after its key, so the count
// in the "rows loaded" line can be read.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: unknown) => {
    if (typeof options === "string") return options;
    if (options && typeof options === "object") {
      const values = Object.entries(options as Record<string, unknown>)
        .map(([name, value]) => `${name}=${String(value)}`);
      if (values.length > 0) return `${key} ${values.join(" ")}`;
    }
    return key;
  },
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
const tenantState = vi.hoisted(() => ({ settings: {} as Record<string, unknown> }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key in tenantState.settings ? tenantState.settings[key] : defaultValue,
  });
  return { useTenant: () => tenant };
});

// The files the browser was handed to save.
const downloads = vi.hoisted(() => ({ files: [] as { name: string; blob: Blob }[] }));
vi.mock("@shared/utils/downloadBlob", () => ({
  downloadBlob: (blob: Blob, filename: string) => {
    downloads.files.push({ name: filename, blob });
  },
}));

const api = vi.hoisted(() => ({
  listRows: vi.fn<(date: string) => Promise<Record<string, unknown>[]>>(),
}));

import ExportCsvAtDateModal, { type ExportCsvColumn } from "../ExportCsvAtDateModal";

// ── Fixtures ────────────────────────────────────────────────────────────────

const NOW = new Date(2026, 9, 7, 12, 0);

/** The row hook a consumer wires: one query per loaded date, nothing before. */
function usePriceRows(loadedDate: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: ["prices", loadedDate],
    queryFn: () => api.listRows(loadedDate as string),
    enabled: !!loadedDate,
  });
  return { rows: data ?? null, isLoading };
}

const COLUMNS: ExportCsvColumn[] = [
  { key: "name", label: "Name" },
  { key: "amount", label: "Amount", decimal: true },
  { key: "note", label: "Note" },
  {
    key: "is_active",
    label: "Active",
    render: (value, row) => `${value ? "yes" : "no"} (${String(row.unit)})`,
  },
];

const CARROTS = { name: "Carrots", amount: 2.5, note: null, is_active: true, unit: "kg" };
const LEMONS = { name: "Lemons, organic", amount: 12, note: "=1+1", is_active: false, unit: "pcs" };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  tenantState.settings = {};
  downloads.files = [];
  api.listRows.mockReset().mockResolvedValue([CARROTS, LEMONS]);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── Helpers ─────────────────────────────────────────────────────────────────

const OPEN_EXPORT = "Export prices";

function PriceListPage({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        {OPEN_EXPORT}
      </button>
      <ExportCsvAtDateModal
        open={open}
        onClose={() => {
          onClose();
          setOpen(false);
        }}
        title="Prices on a date"
        filenamePrefix="prices"
        columns={COLUMNS}
        useRows={usePriceRows}
      />
    </>
  );
}

let queryClient: QueryClient;

function renderPage() {
  const user = userEvent.setup();
  const onClose = vi.fn();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PriceListPage onClose={onClose} />
    </QueryClientProvider>,
  );
  return { user, onClose };
}

type User = ReturnType<typeof userEvent.setup>;

const dialog = () => screen.getByRole("dialog");
const dateInput = () => within(dialog()).getByRole("textbox");
const loadButton = () => within(dialog()).getByRole("button", { name: /common\.load/ });
const downloadButton = () => within(dialog()).getByRole("button", { name: /common\.download/ });
const cancelButton = () => within(dialog()).getByRole("button", { name: "common.cancel" });
const spinner = () => dialog().querySelector(".ant-spin");

async function openExport(user: User) {
  await user.click(screen.getByRole("button", { name: OPEN_EXPORT }));
  return screen.findByRole("dialog");
}

async function load(user: User) {
  const requests = api.listRows.mock.calls.length;
  await user.click(loadButton());
  await waitFor(() => {
    expect(api.listRows.mock.calls.length).toBeGreaterThan(requests);
    expect(queryClient.isFetching()).toBe(0);
    expect(spinner()).not.toBeInTheDocument();
  });
}

async function renderLoaded() {
  const rendered = renderPage();
  await openExport(rendered.user);
  await load(rendered.user);
  return rendered;
}

function openCalendar(): HTMLElement {
  const open = Array.from(document.querySelectorAll<HTMLElement>(".ant-picker-dropdown")).filter(
    (dropdown) => !dropdown.classList.contains("ant-picker-dropdown-hidden"),
  );
  const calendar = open[open.length - 1];
  if (!calendar) throw new Error("No date picker is open");
  return calendar;
}

async function pickDate(user: User, isoDate: string) {
  await user.click(dateInput());
  const cell = await waitFor(() => {
    const found = openCalendar().querySelector<HTMLElement>(`td[title="${isoDate}"]`);
    if (!found) throw new Error(`No calendar cell for ${isoDate}`);
    return found;
  });
  await user.click(cell);
}

/** Reads a file as the bytes the browser saves, a byte order mark included. */
function readFile(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(new TextDecoder("utf-8", { ignoreBOM: true }).decode(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

async function download(user: User) {
  await user.click(downloadButton());
  expect(downloads.files).toHaveLength(1);
  const [file] = downloads.files;
  return { name: file.name, type: file.blob.type, content: await readFile(file.blob) };
}

// ── Loading ─────────────────────────────────────────────────────────────────

describe("ExportCsvAtDateModal loading", () => {
  it("starts on today's date, fetches nothing and offers no download before Load", async () => {
    const { user } = renderPage();

    await openExport(user);

    expect(within(dialog()).getByText("Prices on a date")).toBeInTheDocument();
    expect(dateInput()).toHaveValue("07.10.2026");
    expect(downloadButton()).toBeDisabled();
    await flushMicrotasks();
    expect(api.listRows).not.toHaveBeenCalled();
  });

  it("shows the date in the tenant's date format", async () => {
    tenantState.settings = { date_format: "YYYY-MM-DD" };
    const { user } = renderPage();

    await openExport(user);

    expect(dateInput()).toHaveValue("2026-10-07");
  });

  it("loads the rows for the picked date and says how many came in", async () => {
    await renderLoaded();

    expect(api.listRows).toHaveBeenCalledTimes(1);
    expect(api.listRows).toHaveBeenCalledWith("2026-10-07");
    expect(within(dialog()).getByText("commissioning.prices_loaded count=2")).toBeVisible();
    expect(downloadButton()).toBeEnabled();
  });

  it("spins while the rows are on their way and offers no download yet", async () => {
    let answer: (rows: Record<string, unknown>[]) => void = () => {};
    api.listRows.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { user } = renderPage();
    await openExport(user);

    await user.click(loadButton());

    await waitFor(() => expect(spinner()).toBeInTheDocument());
    expect(downloadButton()).toBeDisabled();
    answer([CARROTS]);
    await waitFor(() => expect(spinner()).not.toBeInTheDocument());
    expect(within(dialog()).getByText("commissioning.prices_loaded count=1")).toBeVisible();
    expect(downloadButton()).toBeEnabled();
  });

  it("says there is nothing for a date without rows and offers no download", async () => {
    api.listRows.mockResolvedValue([]);
    await renderLoaded();

    expect(within(dialog()).getByText("common.no_data")).toBeVisible();
    expect(downloadButton()).toBeDisabled();
  });

  it("loads another date once it is picked", async () => {
    const { user } = await renderLoaded();

    await pickDate(user, "2026-10-12");
    expect(dateInput()).toHaveValue("12.10.2026");
    await load(user);

    expect(api.listRows).toHaveBeenLastCalledWith("2026-10-12");
  });

  it("forgets the loaded rows when cancelled, so a reopened dialog loads again", async () => {
    const { user, onClose } = await renderLoaded();

    await user.click(cancelButton());
    expect(onClose).toHaveBeenCalledTimes(1);
    await openExport(user);

    expect(within(dialog()).queryByText(/commissioning\.prices_loaded/)).not.toBeInTheDocument();
    expect(downloadButton()).toBeDisabled();
  });
});

// ── The file ────────────────────────────────────────────────────────────────

describe("ExportCsvAtDateModal download", () => {
  it("writes a German-format CSV by default and names the file after the date", async () => {
    const { user, onClose } = await renderLoaded();

    const file = await download(user);

    expect(file.name).toBe("prices_2026-10-07.csv");
    expect(file.type).toBe("text/csv;charset=utf-8;");
    expect(file.content.startsWith("﻿")).toBe(true);
    expect(file.content.slice(1).split("\n")).toEqual([
      "Name;Amount;Note;Active",
      "Carrots;2,5;;yes (kg)",
      "Lemons, organic;12;'=1+1;no (pcs)",
    ]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("writes the tenant's English format: commas between cells, points in numbers", async () => {
    tenantState.settings = { csv_format: "en" };
    const { user } = await renderLoaded();

    const file = await download(user);

    expect(file.content.slice(1).split("\n")).toEqual([
      "Name,Amount,Note,Active",
      "Carrots,2.5,,yes (kg)",
      '"Lemons, organic",12,\'=1+1,no (pcs)',
    ]);
  });

  it("names the file after another date once that date is loaded", async () => {
    const { user } = await renderLoaded();

    await pickDate(user, "2026-10-12");
    await load(user);
    const file = await download(user);

    expect(file.name).toBe("prices_2026-10-12.csv");
  });

  it("names the file after the date its rows were loaded for, not a date picked afterwards", async () => {
    const { user } = await renderLoaded();

    await pickDate(user, "2026-10-12");
    const file = await download(user);

    expect(api.listRows).toHaveBeenCalledTimes(1);
    expect(file.name).toBe("prices_2026-10-07.csv");
  });

  it("writes the decimal strings the API sends with the tenant's decimal comma", async () => {
    api.listRows.mockResolvedValue([{ ...CARROTS, amount: "2.50" }]);
    const { user } = await renderLoaded();

    const file = await download(user);

    expect(file.content.slice(1).split("\n")[1]).toBe("Carrots;2,50;;yes (kg)");
  });

  it("keeps the decimal point of the tenant's English format", async () => {
    tenantState.settings = { csv_format: "en" };
    api.listRows.mockResolvedValue([{ ...CARROTS, amount: "-2.50" }]);
    const { user } = await renderLoaded();

    const file = await download(user);

    expect(file.content.slice(1).split("\n")[1]).toBe("Carrots,-2.50,,yes (kg)");
  });

  it("leaves a decimal-looking text in a column not marked as decimal as it is", async () => {
    api.listRows.mockResolvedValue([{ ...CARROTS, note: "1.10" }]);
    const { user } = await renderLoaded();

    const file = await download(user);

    expect(file.content.slice(1).split("\n")[1]).toBe("Carrots;2,5;1.10;yes (kg)");
  });
});
