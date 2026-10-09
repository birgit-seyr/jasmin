/**
 * usePackingBaseColumns: the packing lists' leading columns — the article
 * (locked once saved), its unit and size (each with the backup article's on a
 * grey second line), a read-only note column for the end, and the unit/size
 * labels the PDF reads. The generated share-articles client is the boundary.
 */
import { render, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareArticle } from "@shared/api/generated/models";
import type { EditableColumnConfig, SelectOption, TableRecord } from "@shared/tables/BasicEditableTable/types";

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

const settings = vi.hoisted(() => ({ showSizeColumn: true }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "show_size_column" ? settings.showSizeColumn : defaultValue,
  });
  return { useTenant: () => tenant };
});

// One array, as TanStack keeps the same data between renders.
const articlesApi = vi.hoisted(() => ({ data: [] as ShareArticle[], params: [] as unknown[] }));
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningShareArticlesList: (params: unknown) => {
    articlesApi.params.push(params);
    return { data: articlesApi.data, isLoading: false, error: null, refetch: () => {} };
  },
}));

import { usePackingBaseColumns, withBackupSubline } from "../usePackingBaseColumns";

// ── Fixtures ────────────────────────────────────────────────────────────────

const carrots = { id: "sa-carrots", name: "Karotten" } as ShareArticle;
const leeks = { id: "sa-leeks", name: "Lauch" } as ShareArticle;

const savedRow = (fields: Record<string, unknown> = {}): TableRecord => ({
  key: "pl-1",
  id: "pl-1",
  share_article: "sa-carrots",
  share_article_name: "Karotten",
  unit: "KG",
  size: "M",
  note: "",
  ...fields,
});

const withBackup = savedRow({
  backup_share_article_name: "Lauch",
  backup_share_article_unit: "BUNCH",
  backup_share_article_size: "L",
});

// ── Helpers ─────────────────────────────────────────────────────────────────

const columnsFor = (options?: Parameters<typeof usePackingBaseColumns>[0]) =>
  renderHook(() => usePackingBaseColumns(options)).result.current;

const column = (columns: EditableColumnConfig<TableRecord>[], dataIndex: string) => {
  const found = columns.find((c) => c.dataIndex === dataIndex);
  if (!found) throw new Error(`No column ${dataIndex}`);
  return found;
};

/** A cell as its lines: [main] or [main, grey backup line]. */
function cellLines(col: EditableColumnConfig<TableRecord>, record: TableRecord): string[] {
  const { container } = render(<>{col.render?.(record[col.dataIndex as string], record, 0) as ReactNode}</>);
  const subline = container.querySelector(".text-subline");
  if (!subline) return [container.textContent ?? ""];
  return [subline.previousElementSibling?.textContent ?? "", subline.textContent ?? ""];
}

const isLocked = (col: EditableColumnConfig<TableRecord>, record: TableRecord) =>
  typeof col.disabled === "function" ? col.disabled(record) : Boolean(col.disabled);

beforeEach(() => {
  settings.showSizeColumn = true;
  articlesApi.data = [carrots, leeks];
  articlesApi.params = [];
});

// ── withBackupSubline ───────────────────────────────────────────────────────

describe("withBackupSubline", () => {
  it.each([null, undefined, ""])("returns the main content alone without a backup (%s)", (backup) => {
    expect(withBackupSubline("Karotten", backup)).toBe("Karotten");
  });

  it("returns an empty string for neither", () => {
    expect(withBackupSubline(null, null)).toBe("");
  });
});

// ── The columns ─────────────────────────────────────────────────────────────

describe("usePackingBaseColumns columns", () => {
  it("leads with the article, unit and size columns, without an amount", () => {
    const { baseColumns } = columnsFor();

    expect(baseColumns.map((c) => c.dataIndex)).toEqual(["share_article_name", "unit", "size"]);
  });

  it("offers the active harvest articles by default and the caller's filter otherwise", () => {
    const { baseColumns } = columnsFor();
    expect(articlesApi.params[0]).toEqual({ is_harvest_share_article: true, is_active: true });
    expect((column(baseColumns, "share_article_name").options as SelectOption[]).map((o) => o.label)).toEqual(["Karotten", "Lauch"]);

    articlesApi.params = [];
    columnsFor({ shareArticleFilters: { is_extra: true } });
    expect(articlesApi.params[0]).toEqual({ is_extra: true });
  });

  it("lets the article, unit and size be chosen on a new row only", () => {
    const { baseColumns } = columnsFor();
    const newRow = { key: -1 } as TableRecord;

    for (const col of baseColumns) {
      expect(isLocked(col, newRow)).toBe(false);
      expect(isLocked(col, savedRow())).toBe(true);
    }
  });

  it("hides the size column on a farm without sizes", () => {
    settings.showSizeColumn = false;
    const { baseColumns } = columnsFor();

    expect(column(baseColumns, "size").hidden).toBe(true);
    expect(column(baseColumns, "unit").hidden).toBeUndefined();
  });

  it.skip("hands back the same columns on every render while the articles stay the same", () => {
    const { result, rerender } = renderHook(() => usePackingBaseColumns());
    const first = result.current.baseColumns;

    rerender();

    expect(result.current.baseColumns).toBe(first);
  });

  it("ends with a read-only note column", () => {
    const { noteColumn } = columnsFor();

    expect(noteColumn).toMatchObject({ dataIndex: "note", inputType: "optional", disabled: true });
  });
});

// ── Cells ───────────────────────────────────────────────────────────────────

describe("usePackingBaseColumns cells", () => {
  it("shows the article, unit and size of a row without a backup on one line", () => {
    const { baseColumns } = columnsFor();
    const row = savedRow({ size: "S" });

    expect(cellLines(column(baseColumns, "share_article_name"), row)).toEqual(["Karotten"]);
    expect(cellLines(column(baseColumns, "unit"), row)).toEqual(["commissioning.units.kg"]);
    expect(cellLines(column(baseColumns, "size"), row)).toEqual(["commissioning.small"]);
  });

  it("puts the backup's article, unit and size on a second line", () => {
    const { baseColumns } = columnsFor();

    expect(cellLines(column(baseColumns, "share_article_name"), withBackup)).toEqual([
      "Karotten",
      "commissioning.backup: Lauch",
    ]);
    expect(cellLines(column(baseColumns, "unit"), withBackup)).toEqual([
      "commissioning.units.kg",
      "commissioning.units.bunch",
    ]);
    expect(cellLines(column(baseColumns, "size"), withBackup)).toEqual(["commissioning.medium", "commissioning.large"]);
  });

  it("leaves the unit and size lines out for a backup without them", () => {
    const { baseColumns } = columnsFor();
    const row = savedRow({ backup_share_article_name: "Lauch", backup_share_article_unit: null });

    expect(cellLines(column(baseColumns, "share_article_name"), row)).toHaveLength(2);
    expect(cellLines(column(baseColumns, "unit"), row)).toEqual(["commissioning.units.kg"]);
    expect(cellLines(column(baseColumns, "size"), row)).toEqual(["commissioning.medium"]);
  });

  it("ignores a backup unit and size without a backup article", () => {
    const { baseColumns } = columnsFor();
    const row = savedRow({ backup_share_article_unit: "BUNCH", backup_share_article_size: "L" });

    expect(cellLines(column(baseColumns, "unit"), row)).toEqual(["commissioning.units.kg"]);
    expect(cellLines(column(baseColumns, "size"), row)).toEqual(["commissioning.medium"]);
  });

  it("falls back to the cell value for an article without a name", () => {
    const { baseColumns } = columnsFor();
    const col = column(baseColumns, "share_article_name");
    const row = savedRow({ share_article_name: undefined });

    const { container } = render(<>{col.render?.("sa-carrots", row, 0) as ReactNode}</>);
    expect(container.textContent).toBe("sa-carrots");
  });
});

// ── PDF ─────────────────────────────────────────────────────────────────────

describe("usePackingBaseColumns PDF", () => {
  it("prints the article, then the unit and size labels, then the note", () => {
    const { baseColumns, noteColumn } = columnsFor();

    expect(baseColumns.map((c) => c.pdf)).toEqual([
      { include: true, width: "30%", dataKey: "share_article_name", align: "left", title: "commissioning.vegetables_and_fruits" },
      { include: true, width: "10%", dataKey: "unit_label", align: "center", title: "commissioning.unit" },
      { include: true, width: "10%", dataKey: "size_label", align: "center", title: "commissioning.size" },
    ]);
    expect(noteColumn.pdf).toEqual({
      include: true,
      width: "10%",
      dataKey: "note",
      align: "left",
      title: "commissioning.note",
    });
  });

  it("gives the note the width the caller asks for", () => {
    const { noteColumn } = columnsFor({ noteWidth: "25%" });

    expect(noteColumn.pdf?.width).toBe("25%");
  });

  it("adds the unit and size labels to each row, empty where a row has none", () => {
    const { withUnitSizeLabels } = columnsFor();
    const rows = [savedRow({ size: "L" }), savedRow({ key: "pl-2", id: "pl-2", unit: null, size: "" })];

    expect(withUnitSizeLabels(rows).map((r) => [r.key, r.unit_label, r.size_label])).toEqual([
      ["pl-1", "commissioning.units.kg", "commissioning.large"],
      ["pl-2", "", ""],
    ]);
    expect(rows[0]).not.toHaveProperty("unit_label");
  });
});
