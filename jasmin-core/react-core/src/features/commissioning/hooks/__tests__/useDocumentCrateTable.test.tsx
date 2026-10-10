/**
 * useDocumentCrateTable: a delivery note's or an invoice's crate table. A new
 * line takes a crate type the document doesn't list yet — the picker offers
 * only those and the save refuses a repeat — while saved lines may share a
 * type. Every write names the document, and the rows the table reports stand
 * until the document is read again.
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CrateItemSummary } from "@shared/api/generated/models/crateItemSummary";
import { RowSaveRefused } from "@shared/tables/BasicEditableTable/RowSaveRefused";
import type { ApiFunctions, TableRecord } from "@shared/tables/BasicEditableTable/types";

vi.mock("../columns/useCratesColumns", () => {
  const crates = [
    { value: "eurobox", label: "Eurobox" },
    { value: "pallet", label: "Pallet" },
  ];
  const cratesColumns = [
    { key: "crate_type_name", dataIndex: "crate_type_name", options: crates },
    { key: "amount", dataIndex: "amount" },
  ];
  return { useCratesColumns: () => ({ cratesColumns, crates }) };
});

import { refuseRepeatedCrateType, useDocumentCrateTable } from "../useDocumentCrateTable";

const line = (id: string, crateType: string): CrateItemSummary => ({
  id,
  crate_type: crateType,
  crate_type_name: crateType,
  amount: 2,
  price_per_unit: "3.00",
  rabatt: 0,
  line_netto: "6.00",
  tax_rate: 19,
});

const apiFunctions = {} as ApiFunctions;

const renderTable = (crateItems: CrateItemSummary[] | undefined, canWrite = true) => {
  const refetchDocument = vi.fn();
  const hook = renderHook(
    ({ items }) =>
      useDocumentCrateTable({
        crateItems: items,
        documentField: "invoice_id",
        documentId: "inv-1",
        canWrite,
        apiFunctions,
        refetchDocument,
        repeatedTypeMessage: "already listed",
      }),
    { initialProps: { items: crateItems } },
  );
  return { ...hook, refetchDocument };
};

const pickerOptions = (columns: { key?: string; options?: unknown }[]) =>
  (columns.find((column) => column.key === "crate_type_name")?.options ?? []) as {
    value: string;
  }[];

describe("refuseRepeatedCrateType", () => {
  const rows = [{ crate_type: "eurobox" }];

  it("refuses a new line of a listed crate type, on the crate type", () => {
    let thrown: unknown;
    try {
      refuseRepeatedCrateType(rows, { crate_type: "eurobox" }, { key: -1 }, "already listed");
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toBeInstanceOf(RowSaveRefused);
    expect((thrown as RowSaveRefused).fieldErrors).toEqual({ crate_type_name: "already listed" });
  });

  it("lets a saved line keep a listed crate type", () => {
    expect(() =>
      refuseRepeatedCrateType(rows, { crate_type: "eurobox" }, { key: "line-1" }, "x"),
    ).not.toThrow();
  });

  it("lets a new line of an unlisted or empty crate type through", () => {
    expect(() => refuseRepeatedCrateType(rows, { crate_type: "pallet" }, { key: -1 }, "x")).not.toThrow();
    expect(() => refuseRepeatedCrateType(rows, { crate_type: "" }, { key: -1 }, "x")).not.toThrow();
  });
});

describe("useDocumentCrateTable", () => {
  it("keys the document's lines by id and offers only unlisted crate types", () => {
    const { result } = renderTable([line("l1", "eurobox")]);
    const { tableProps } = result.current;
    expect(tableProps.initialData.map((row) => row.key)).toEqual(["l1"]);
    expect(pickerOptions(tableProps.columns).map((option) => option.value)).toEqual(["pallet"]);
    expect(tableProps.permissions).toEqual({ canAdd: true, canEdit: true, canDelete: true });
  });

  it("allows no new line once every crate type is listed", () => {
    const { result } = renderTable([line("l1", "eurobox"), line("l2", "pallet")]);
    expect(result.current.tableProps.permissions.canAdd).toBe(false);
  });

  it("allows nothing without write access", () => {
    const { result } = renderTable([], false);
    expect(result.current.tableProps.permissions).toEqual({
      canAdd: false,
      canEdit: false,
      canDelete: false,
    });
  });

  it("names the document on a save and refuses a repeated crate type", () => {
    const { result } = renderTable([line("l1", "eurobox")]);
    const { customSave } = result.current.tableProps;
    expect(customSave({ crate_type: "pallet", amount: 1 }, { key: -1 })).toEqual({
      crate_type: "pallet",
      amount: 1,
      invoice_id: "inv-1",
    });
    expect(() => customSave({ crate_type: "eurobox" }, { key: -1 })).toThrow(RowSaveRefused);
  });

  it("names the crate type and the document on a delete", () => {
    const { result } = renderTable([line("l1", "eurobox")]);
    expect(result.current.tableProps.customDelete({ key: "l1", crate_type: "eurobox" })).toEqual({
      crate_type: "eurobox",
      invoice_id: "inv-1",
    });
  });

  it("reads the document again after a save or a delete", () => {
    const { result, refetchDocument } = renderTable([]);
    expect(result.current.tableProps.onSaveSuccess).toBe(refetchDocument);
    expect(result.current.tableProps.onDeleteSuccess).toBe(refetchDocument);
  });

  it("keeps the reported rows until the document is read again", () => {
    const { result, rerender } = renderTable([line("l1", "eurobox")]);
    const reported: TableRecord[] = [
      { key: "l1", crate_type: "eurobox" },
      { key: "l2", crate_type: "pallet" },
    ];
    act(() => result.current.tableProps.onDataChange(reported));
    expect(result.current.rows).toBe(reported);
    expect(result.current.tableProps.permissions.canAdd).toBe(false);

    rerender({ items: [line("l1", "eurobox")] });
    expect(result.current.rows.map((row) => row.key)).toEqual(["l1"]);
  });

  it("treats a document without crate lines as empty", () => {
    const { result } = renderTable(undefined);
    expect(result.current.rows).toEqual([]);
  });
});
