/**
 * ExportCsv: the list pages' "export this list as CSV" dialog. It is handed the
 * grid's own columns and rows, lets the office pick the columns and downloads
 * the picked ones in the tenant's CSV format. The real dialog, column picker
 * and CSV helpers run; the browser download is recorded instead of saved.
 *
 * A grid's columns include buttons and links — a price button, an orders link —
 * that carry a `dataIndex` only because the table needs a key. No row has a
 * field under that key, so they have nothing to export.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The tenant's CSV format, per test.
const tenantState = vi.hoisted(() => ({ csvFormat: "en" }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "csv_format" ? tenantState.csvFormat : defaultValue,
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

import ExportCsv from "../ExportCsv";

// ── Fixtures ────────────────────────────────────────────────────────────────

const ACTIVE = { title: <>Active</>, dataIndex: "is_active", key: "is_active" };
const NAME = { title: <>Name</>, dataIndex: "name", key: "name" };
// A data column the grid draws through `render` — the unit shown by label.
const UNIT = {
  title: <>Unit</>,
  dataIndex: "default_movement_unit",
  key: "default_movement_unit",
  render: (value: string) => (value === "PCS" ? "Pieces" : value),
};
// The price button of the article and crate lists: no title, no field.
const PRICE_BUTTON = {
  title: "",
  dataIndex: "actions",
  key: "actions",
  render: () => <button type="button">Prices</button>,
};
// A titled link column, as the reseller list has one.
const ORDERS_LINK = {
  title: <>Link</>,
  dataIndex: "link",
  key: "link",
  render: () => <a href="/orders">Orders</a>,
};
const DESCRIPTION = { title: <>Description</>, dataIndex: "description", key: "description" };

const COLUMNS = [ACTIVE, NAME, PRICE_BUTTON, UNIT, ORDERS_LINK, DESCRIPTION];

const ROWS = [
  { key: "a", id: "a", is_active: true, name: "Gardening course", default_movement_unit: "PCS", description: null },
  { key: "b", id: "b", is_active: false, name: "Jute bag", default_movement_unit: "PCS", description: "Big" },
];

beforeEach(() => {
  tenantState.csvFormat = "en";
  downloads.files = [];
});

function readFile(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new TextDecoder().decode(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

async function downloadedLines(): Promise<string[]> {
  expect(downloads.files).toHaveLength(1);
  const content = await readFile(downloads.files[0].blob);
  return content.replace(/^﻿/, "").trim().split(/\r?\n/);
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("ExportCsv columns", () => {
  it("offers the list's data columns and no button or link column", () => {
    render(<ExportCsv open onClose={() => {}} columns={COLUMNS} data={ROWS} filename="Extras" />);

    const offered = screen.getAllByRole("checkbox").map((box) => box.closest("label")?.textContent);
    expect(offered).toEqual(["common.select_all", "Active", "Name", "Unit", "Description"]);
  });

  it("downloads only the data columns, a column the grid draws through render included", async () => {
    const user = userEvent.setup();
    render(<ExportCsv open onClose={() => {}} columns={COLUMNS} data={ROWS} filename="Extras" />);

    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    expect(downloads.files[0].name).toBe("Extras.csv");
    const [header, ...rows] = await downloadedLines();
    expect(header).toBe("Active,Name,Unit,Description");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("Gardening course");
    expect(rows[0]).toContain("PCS");
    expect(rows[1]).toContain("Big");
  });

  it("keeps a data column that is empty in every row", async () => {
    const user = userEvent.setup();
    const noDescriptions = ROWS.map((row) => ({ ...row, description: null }));
    render(<ExportCsv open onClose={() => {}} columns={COLUMNS} data={noDescriptions} filename="Extras" />);

    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    const [header] = await downloadedLines();
    expect(header).toBe("Active,Name,Unit,Description");
  });

  it("picks every data column that shows up once the rows have loaded", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ExportCsv open={false} onClose={() => {}} columns={COLUMNS} data={[]} filename="Extras" />,
    );

    rerender(<ExportCsv open onClose={() => {}} columns={COLUMNS} data={ROWS} filename="Extras" />);
    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    const [header] = await downloadedLines();
    expect(header).toBe("Active,Name,Unit,Description");
  });

  it("leaves out a column the office unticks", async () => {
    const user = userEvent.setup();
    render(<ExportCsv open onClose={() => {}} columns={COLUMNS} data={ROWS} filename="Extras" />);

    await user.click(screen.getByRole("checkbox", { name: "Unit" }));
    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    const [header] = await downloadedLines();
    expect(header).toBe("Active,Name,Description");
  });
});

describe("ExportCsv decimals", () => {
  // The API sends decimals as strings; the grid's input type says which
  // columns hold them. An article number is text, however it looks.
  const ARTICLE_NUMBER = { title: <>No.</>, dataIndex: "article_number", key: "article_number", inputType: "text" };
  const KG_PER_PIECE = {
    title: <>Kg per piece</>, dataIndex: "kg_per_piece_S", key: "kg_per_piece_S", inputType: "positive_decimal3",
  };
  const PIECES_PER_KG = {
    title: <>Pieces per kg</>, dataIndex: "pieces_per_kg_S", key: "pieces_per_kg_S", inputType: "positive_integer",
  };
  const DECIMAL_COLUMNS = [ARTICLE_NUMBER, NAME, KG_PER_PIECE, PIECES_PER_KG];
  const DECIMAL_ROWS = [
    { key: "a", id: "a", article_number: "1.10", name: "Leeks", kg_per_piece_S: "0.250", pieces_per_kg_S: 4 },
    { key: "b", id: "b", article_number: "2", name: "Kale", kg_per_piece_S: null, pieces_per_kg_S: null },
  ];

  it("writes a decimal column with the decimal comma of the tenant's German format, leaving text as it is", async () => {
    tenantState.csvFormat = "de";
    const user = userEvent.setup();
    render(<ExportCsv open onClose={() => {}} columns={DECIMAL_COLUMNS} data={DECIMAL_ROWS} filename="Articles" />);

    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    expect(await downloadedLines()).toEqual([
      "No.;Name;Kg per piece;Pieces per kg",
      "1.10;Leeks;0,250;4",
      "2;Kale;;",
    ]);
  });

  it("keeps the decimal point in the tenant's English format", async () => {
    const user = userEvent.setup();
    render(<ExportCsv open onClose={() => {}} columns={DECIMAL_COLUMNS} data={DECIMAL_ROWS} filename="Articles" />);

    await user.click(screen.getByRole("button", { name: /common\.download/ }));

    expect((await downloadedLines())[1]).toBe("1.10,Leeks,0.250,4");
  });
});
